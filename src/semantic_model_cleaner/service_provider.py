"""Shared read-only Fabric/Power BI transport and definition boundary.

Used by the feasibility probe and experimental service workflows.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

FABRIC = "https://api.fabric.microsoft.com/v1"
POWERBI = "https://api.powerbi.com/v1.0/myorg"
RESOURCES = {
    "fabric": "https://api.fabric.microsoft.com",
    "powerbi": "https://analysis.windows.net/powerbi/api",
}
MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 100
KNOWN_SCOPES = {
    "Workspace.Read.All",
    "Workspace.ReadWrite.All",
    "SemanticModel.Read.All",
    "SemanticModel.ReadWrite.All",
    "Item.Read.All",
    "Item.ReadWrite.All",
    "Report.Read.All",
    "Report.ReadWrite.All",
}
BOUNDARIES = [
    "Only direct Power BI Report consumers visible in explicitly selected workspaces are searched.",
    "Unknown or inaccessible workspaces/reports cannot be counted; absence is not proof of non-use.",
    "Indirect/composite models, dashboards, Excel, XMLA and other consumers are outside scope.",
    "Impact-analysis UI visibility does not grant API discovery or definition access.",
    "Retrievals are separate observations, not a transactionally consistent snapshot.",
    "Metadata analysis does not validate rendering, DAX execution or data correctness.",
    "Encrypted sensitivity labels block definition retrieval; generic API errors do not prove encryption.",
]


def now():
    return datetime.now(timezone.utc).isoformat()


class ProbeError(Exception):
    """Only fixed, non-sensitive codes may escape the boundary."""


def guid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ProbeError("invalid_identity") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiveTransport:
    def __init__(self, tokens):
        self.tokens = tokens
        self.opener = build_opener(NoRedirect())

    def __call__(self, method, url):
        service = "fabric" if url.startswith(FABRIC + "/") else "powerbi"
        request = Request(
            url,
            method=method,
            headers={
                "Authorization": "Bearer " + self.tokens[service],
                "Accept": "application/json",
            },
            data=b"" if method == "POST" else None,
        )
        try:
            try:
                response = self.opener.open(request, timeout=30)
            except HTTPError as exc:
                response = exc
            with response:
                payload = response.read(MAX_BYTES + 1)
                if len(payload) > MAX_BYTES:
                    raise ProbeError("response_size_limit")
                status = response.code
                headers = dict(response.headers.items())
                try:
                    body = json.loads(payload) if payload else {}
                except (ValueError, UnicodeError):
                    if status >= 400:
                        return status, headers, {}
                    raise ProbeError("invalid_response_json") from None
                if not isinstance(body, dict):
                    raise ProbeError("invalid_response_shape")
                return status, headers, body
        except (URLError, TimeoutError, OSError):
            raise ProbeError("network_unavailable") from None


class FixtureTransport:
    def __init__(self, fixture):
        self.responses = iter(fixture["responses"])

    def __call__(self, method, url):
        try:
            row = next(self.responses)
        except StopIteration:
            raise ProbeError("fixture_exhausted") from None
        if (method, url) != (row["method"], row["url"]):
            raise ProbeError("fixture_request_mismatch")
        return row.get("status", 200), row.get("headers", {}), row.get("body", {})


class Evidence:
    def __init__(self, mode):
        self.identities = {}
        self.data = {
            "schema_version": 1,
            "evidence_kind": mode,
            "started_at": now(),
            "status": "incomplete",
            "live_acceptance": "unverified",
            "global_completeness": False,
            "selected_scope_complete": False,
            "boundaries": BOUNDARIES,
            "requests": [],
            "workspaces": [],
            "reports": [],
            "analysis_limitations": [],
            "report_health": {"issue_count": 0, "checked": False},
            "permission_observations": {
                "workspace_roles": "unverified",
                "item_permissions": "unverified",
                "tenant_configuration": "unverified",
                "non_admin_owner": "unverified",
                "definition_access_denial": "unverified",
                "encrypted_items": "unverified",
                "note": "API success observes a capability; it does not establish role or ownership.",
            },
        }

    def alias(self, kind, identity):
        key = (kind, identity)
        if key not in self.identities:
            count = sum(k[0] == kind for k in self.identities) + 1
            self.identities[key] = f"{kind}-{count}"
        return self.identities[key]

    def limitation(self, code, owner="selected-scope"):
        row = {
            "code": code,
            "owner": owner,
            "scope": "shared",
            "checked": "Only successful operations and parser counts recorded in this evidence were checked.",
            "unchecked": "The capability identified by this code is incomplete or outside the selected scope.",
            "effect": "No Use Found In Scope requires Review; cleanup safety is not established.",
        }
        if row not in self.data["analysis_limitations"]:
            self.data["analysis_limitations"].append(row)


class Client:
    def __init__(self, transport, evidence, *, sleep=time.sleep, max_seconds=300, progress=None):
        self.transport, self.evidence, self.sleep = transport, evidence, sleep
        self.deadline = time.monotonic() + max_seconds
        self.progress = progress or (lambda *_: None)

    def pause(self, headers):
        try:
            delay = max(1, int(headers.get("retry-after", "1")))
        except ValueError:
            raise ProbeError("invalid_retry_after") from None
        if delay > 60 or time.monotonic() + delay >= self.deadline:
            raise ProbeError("retry_budget_exceeded")
        for _ in range(delay):
            self.progress("Waiting for service")
            self.sleep(1)

    def request(self, method, url, operation, owner):
        # Fixed read operations only, including the read-only POST getDefinition.
        parsed = urlsplit(url)
        uuid = r"[0-9a-fA-F-]{36}"
        allowed = (
            parsed.scheme == "https"
            and not parsed.fragment
            and (
                (
                    parsed.netloc == "api.fabric.microsoft.com"
                    and (
                        method == "GET"
                        and re.fullmatch(
                            rf"/v1/(workspaces/{uuid}/semanticModels|operations/{uuid}(/result)?)",
                            parsed.path,
                        )
                        or method == "POST"
                        and re.fullmatch(
                            rf"/v1/workspaces/{uuid}/(semanticModels|reports)/{uuid}/getDefinition",
                            parsed.path,
                        )
                    )
                )
                or (
                    parsed.netloc == "api.powerbi.com"
                    and method == "GET"
                    and re.fullmatch(rf"/v1.0/myorg/groups/{uuid}/reports", parsed.path)
                )
            )
        )
        if not allowed:
            raise ProbeError("request_outside_read_allowlist")
        for attempt in range(4):
            self.progress(operation)
            if time.monotonic() >= self.deadline:
                raise ProbeError("request_budget_exceeded")
            receipt = {
                "method": method,
                "operation": operation,
                "owner": owner,
                "status": None,
                "at": now(),
            }
            self.evidence.data["requests"].append(receipt)
            try:
                status, headers, body = self.transport(method, url)
            except ProbeError as exc:
                receipt["failure"] = str(exc)
                raise
            finally:
                receipt["finished_at"] = now()
            receipt["status"] = status
            headers = {k.lower(): v for k, v in headers.items()}
            if status == 429 and attempt < 3:
                self.pause(headers)
                continue
            if status not in (200, 202):
                code = {
                    401: "authentication_rejected",
                    403: "access_denied",
                    404: "not_found_or_inaccessible",
                    429: "rate_limited",
                }.get(status, "api_request_failed")
                if body.get("errorCode") == "OperationNotSupportedForItem":
                    code = "definition_not_supported_possible_encryption"
                raise ProbeError(code)
            return status, headers, body
        raise ProbeError("rate_limited")

    def items(self, url, operation, owner):
        original = urlsplit(url)
        seen = set()
        for _ in range(MAX_PAGES):
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.netloc, parsed.path, parsed.fragment) != (
                original.scheme,
                original.netloc,
                original.path,
                "",
            ) or url in seen:
                raise ProbeError("invalid_pagination")
            seen.add(url)
            status, _, body = self.request("GET", url, operation, owner)
            if status != 200 or not isinstance(body.get("value"), list):
                raise ProbeError("invalid_collection")
            for row in body["value"]:
                if not isinstance(row, dict):
                    raise ProbeError("invalid_collection")
                yield row
            next_url = (
                body.get("continuationUri")
                or body.get("@odata.nextLink")
                or body.get("odata.nextLink")
            )
            if not next_url and body.get("continuationToken"):
                next_url = original._replace(
                    query=urlencode({"continuationToken": body["continuationToken"]})
                ).geturl()
            if not next_url:
                return
            if not isinstance(next_url, str):
                raise ProbeError("invalid_pagination")
            url = next_url
        raise ProbeError("pagination_limit")

    def definition(self, workspace, kind, identity, owner):
        url = f"{FABRIC}/workspaces/{workspace}/{kind}/{identity}/getDefinition"
        if kind == "semanticModels":
            url += "?format=TMDL"
        status, headers, body = self.request("POST", url, "get_definition", owner)
        if status == 200:
            return body
        operation = headers.get("location")
        if not operation and headers.get("x-ms-operation-id"):
            operation = FABRIC + "/operations/" + guid(headers["x-ms-operation-id"])
        if not isinstance(operation, str) or not re.fullmatch(
            re.escape(FABRIC) + r"/operations/[0-9a-fA-F-]{36}", operation
        ):
            raise ProbeError("invalid_operation_location")
        for _ in range(60):
            self.pause(headers)
            _, headers, body = self.request("GET", operation, "operation_state", owner)
            state = body.get("status")
            if state in {"Failed", "Cancelled", "Canceled"}:
                raise ProbeError("definition_operation_failed")
            if state == "Succeeded":
                result_url = headers.get("location", operation + "/result")
                if result_url != operation + "/result":
                    raise ProbeError("invalid_operation_location")
                status, _, result = self.request("GET", result_url, "operation_result", owner)
                if status != 200:
                    raise ProbeError("definition_result_incomplete")
                return result
            if state not in {"NotStarted", "Running"}:
                raise ProbeError("unknown_operation_state")
        raise ProbeError("operation_poll_limit")


def token_claims(token, service):
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        tenant, subject = guid(claims["tid"]), guid(claims["oid"])
        if float(claims["exp"]) <= time.time() + 30:
            raise ProbeError("token_expired")
        audiences = {RESOURCES[service], RESOURCES[service] + "/"}
        if service == "powerbi":
            audiences.add("00000009-0000-0000-c000-000000000000")
        if claims.get("aud") not in audiences:
            raise ProbeError("token_audience_mismatch")
        scopes = sorted(set(claims.get("scp", "").split()) & KNOWN_SCOPES)
        return tenant, subject, scopes, "delegated_user" if claims.get("scp") else "application"
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ProbeError("token_claims_unavailable") from None


def authenticate():
    tokens, observations = {}, {}
    for service in RESOURCES:
        token = os.environ.get("SMC_" + service.upper() + "_TOKEN")
        if not token:
            if not shutil.which("az"):
                raise ProbeError("linux_sign_in_required")
            try:
                result = subprocess.run(
                    [
                        "az",
                        "account",
                        "get-access-token",
                        "--resource",
                        RESOURCES[service],
                        "--output",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
                token = json.loads(result.stdout)["accessToken"]
            except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                raise ProbeError("linux_sign_in_required") from None
        observations[service] = token_claims(token, service)
        tokens[service] = token
    if observations["fabric"][:2] != observations["powerbi"][:2]:
        raise ProbeError("credential_identity_mismatch")
    return tokens, observations


def unpack_definition(body, destination, kind):
    """Validate all paths before writing into a private temporary directory."""
    definition = body.get("definition")
    if not isinstance(definition, dict) or not isinstance(definition.get("parts"), list):
        raise ProbeError("invalid_definition")
    files, total = {}, 0
    for part in definition["parts"]:
        if not isinstance(part, dict):
            raise ProbeError("invalid_definition")
        path = part.get("path")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or ":" in path
            or "\x00" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))
        ):
            raise ProbeError("unsafe_definition_path")
        pure = PurePosixPath(path)
        if pure.is_absolute() or path.casefold() in {p.casefold() for p in files}:
            raise ProbeError("unsafe_definition_path")
        if part.get("payloadType") != "InlineBase64":
            raise ProbeError("unsupported_payload_type")
        try:
            data = base64.b64decode(part["payload"], validate=True)
        except (ValueError, KeyError, TypeError):
            raise ProbeError("invalid_definition_payload") from None
        total += len(data)
        if total > MAX_BYTES:
            raise ProbeError("definition_size_limit")
        files[path] = data
    if kind == "model":
        if (
            definition.get("format") not in {None, "TMDL"}
            or "definition/model.tmdl" not in files
            or "model.bim" in files
        ):
            raise ProbeError("unsupported_model_format")
        format_name = "TMDL"
    else:
        if "report.json" in files:
            raise ProbeError("unsupported_legacy_report")
        if (
            definition.get("format") not in {None, "PBIR"}
            or not {"definition.pbir", "definition/report.json", "definition/pages/pages.json"}
            <= files.keys()
        ):
            raise ProbeError("unsupported_or_incomplete_report")
        try:
            pages = json.loads(files["definition/pages/pages.json"].decode("utf-8-sig"))
            order = pages["pageOrder"]
            if not isinstance(order, list) or any(
                not isinstance(page, str)
                or "/" in page
                or f"definition/pages/{page}/page.json" not in files
                for page in order
            ):
                raise ProbeError("incomplete_report_pages")
        except (ValueError, UnicodeError, KeyError, TypeError):
            raise ProbeError("invalid_report_page_inventory") from None
        format_name = "PBIR"
    for path in files:
        if any(str(parent) in files for parent in PurePosixPath(path).parents):
            raise ProbeError("unsafe_definition_path")
    digest = hashlib.sha256()
    for path, data in sorted(files.items()):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest.update(path.encode() + b"\0" + data + b"\0")
    return {
        "format": format_name,
        "parts": len(files),
        "bytes": total,
        "sha256": digest.hexdigest(),
        "retrieved_at": now(),
    }


def inspect_models(client, workspace, evidence):
    alias = evidence.alias("workspace", workspace)
    rows = list(
        client.items(f"{FABRIC}/workspaces/{workspace}/semanticModels", "list_models", alias)
    )
    models = {}
    for row in rows:
        identity = guid(row.get("id"))
        if row.get("workspaceId") and guid(row["workspaceId"]) != workspace:
            raise ProbeError("model_workspace_mismatch")
        models[identity] = {
            "id": identity,
            "display_name": row.get("displayName", ""),
            "alias": evidence.alias("model", identity),
        }
    return list(models.values())


def verify_report_binding(path, model):
    """Fail closed if the retrieved definition cannot confirm the inventory binding.

    Do not infer deployment identity from Initial Catalog/display names or byPath.
    This also detects rebinds between discovery and definition retrieval.
    """
    try:
        reference = json.loads((path / "definition.pbir").read_text(encoding="utf-8-sig"))[
            "datasetReference"
        ]
        if "byPath" in reference:
            raise ProbeError("report_binding_unverified")
        connection = reference["byConnection"]
        identities = []
        if connection.get("pbiModelDatabaseName"):
            identities.append(guid(connection["pbiModelDatabaseName"]))
        for match in re.finditer(
            r"(?:^|;)\s*semanticmodelid\s*=\s*([^;]+)",
            connection.get("connectionString", ""),
            re.IGNORECASE,
        ):
            identities.append(guid(match.group(1).strip()))
        if not identities:
            raise ProbeError("report_binding_unverified")
        if any(identity != model for identity in identities):
            raise ProbeError("report_binding_changed_or_conflicting")
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise ProbeError("report_binding_unverified") from None


# Public experimental contract; richer local results must not be posted as public evidence.
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Target:
    tenant_id: str
    workspace_id: str
    model_id: str
    report_workspace_ids: tuple[str, ...]

    def __post_init__(self):
        for name in ("tenant_id", "workspace_id", "model_id"):
            object.__setattr__(self, name, guid(getattr(self, name)))
        scope = tuple(dict.fromkeys(guid(w) for w in self.report_workspace_ids))
        if not scope:
            raise ProbeError("explicit_report_workspace_scope_required")
        object.__setattr__(self, "report_workspace_ids", scope)

    def to_dict(self):
        return asdict(self)


def limitation(
    code, owner, *, checked="Successful operations recorded in this result.", unchecked=None
):
    return {
        "id": f"service:{code}:{owner}",
        "code": code,
        "feature": code.replace("_", " "),
        "owner": owner,
        "scope": "shared",
        "checked": checked,
        "unchecked": unchecked or "This capability was not established for the selected scope.",
        "effect": "Items with No Use Found In Scope require Review. No cleanup is authorized.",
    }


def new_result(action, target, mode):
    return {
        "schema_version": "service-validation/1",
        "command": f"service {action}",
        "experimental": True,
        "live_acceptance": "unverified",
        "evidence_kind": mode,
        "target": target.to_dict(),
        "started_at": now(),
        "status": "running",
        "global_completeness": False,
        "selected_scope_complete": False,
        "boundaries": list(BOUNDARIES),
        "workspaces": [],
        "reports": [],
        "analysis_limitations": [],
        "requests": [],
        "errors": [],
        "report_health": {"checked": False, "findings": []},
        "cleanup_available": False,
    }


def error_hint(code):
    return {
        "linux_sign_in_required": "Install Azure CLI if needed and sign in locally with az login --use-device-code --allow-no-subscriptions. No credentials are transferred from another machine.",
        "selected_tenant_mismatch": "The credential tenant differs from the selected tenant. Sign in to the intended tenant explicitly; the target was not changed.",
        "access_denied": "Check existing workspace visibility and item read/write permissions and required delegated scopes. The application does not grant access.",
        "authentication_rejected": "Renew the local sign-in for the selected tenant; no tenant fallback was attempted.",
        "token_expired": "Renew the local tokens or Azure CLI sign-in for the same selected tenant.",
        "definition_not_supported_possible_encryption": "Definition retrieval is unsupported. Encrypted labels can block it; this response alone does not establish encryption.",
        "selected_model_not_visible_in_workspace": "Inspect the exact workspace and choose a visible model ID; names are not matched.",
        "request_budget_exceeded": "The bounded request budget expired. Retry the same explicit target later.",
        "cancelled": "The operation was cancelled. No results are available for cleanup.",
    }.get(
        code,
        "Inspect Analysis Limitations and the documented API permissions. Retry only after resolving the reported capability gap.",
    )


class ServiceProvider:
    """One fresh run, one explicit target; no persistent definition cache."""

    def __init__(self, target, *, fixture=None, progress=None):
        self.target, self.progress = target, progress or (lambda *_: None)
        self.mode = "fixture" if fixture else "live"
        self.evidence = Evidence(self.mode)
        self.fixture = fixture
        self.client = None

    def connect(self):
        self.progress("Checking selected tenant")
        if self.fixture:
            try:
                data = json.loads(Path(self.fixture).read_text(encoding="utf-8"))
                tenant = guid(data["tenant_id"])
                transport = FixtureTransport(data)
            except (OSError, ValueError, KeyError, TypeError):
                raise ProbeError("invalid_fixture") from None
        else:
            tokens, observations = authenticate()
            tenant = observations["fabric"][0]
            transport = LiveTransport(tokens)
        if tenant != self.target.tenant_id:
            raise ProbeError("selected_tenant_mismatch")
        self.client = Client(
            transport,
            self.evidence,
            sleep=(lambda _: None) if self.fixture else time.sleep,
            progress=self.progress,
        )

    def models(self):
        if self.client is None:
            self.connect()
        return inspect_models(self.client, self.target.workspace_id, self.evidence)

    def discover(self):
        result = new_result("discover", self.target, self.mode)
        try:
            models = self.models()
            self.candidates = models
            if self.target.model_id not in {m["id"] for m in models}:
                raise ProbeError("selected_model_not_visible_in_workspace")
            result["model_name"] = next(
                m["display_name"] for m in models if m["id"] == self.target.model_id
            )
            for workspace in self.target.report_workspace_ids:
                self.progress(
                    "Discovering Reports",
                    len(result["workspaces"]),
                    len(self.target.report_workspace_ids),
                )
                ws = {
                    "workspace_id": workspace,
                    "status": "enumerating",
                    "started_at": now(),
                    "visible_report_count": 0,
                    "connected_report_count": 0,
                }
                result["workspaces"].append(ws)
                seen = {}
                try:
                    for item in self.client.items(
                        f"{POWERBI}/groups/{workspace}/reports",
                        "list_reports",
                        self.evidence.alias("workspace", workspace),
                    ):
                        identity = guid(item.get("id"))
                        if identity in seen:
                            if seen[identity] != item:
                                raise ProbeError("conflicting_report_identity")
                            continue
                        seen[identity] = item
                        row = {
                            "workspace_id": workspace,
                            "report_id": identity,
                            "name": item.get("name", ""),
                            "discovered_at": now(),
                            "service_url": f"https://app.powerbi.com/groups/{workspace}/reports/{identity}",
                            "status": "unknown",
                            "connection": "unknown",
                            "definition": None,
                        }
                        result["reports"].append(row)
                        ws["visible_report_count"] += 1
                        model_id = item.get("datasetId")
                        if model_id:
                            row["direct_model_id"] = guid(model_id)
                        if item.get("reportType") != "PowerBIReport":
                            row.update(
                                status="excluded", reason="unsupported_or_unknown_report_type"
                            )
                        elif not model_id:
                            row["reason"] = "direct_model_identity_missing"
                        elif guid(model_id) != self.target.model_id:
                            row.update(
                                status="excluded",
                                connection="other_model",
                                reason="different_direct_model",
                            )
                        elif (
                            item.get("datasetWorkspaceId")
                            and guid(item["datasetWorkspaceId"]) != self.target.workspace_id
                        ):
                            row["reason"] = "model_workspace_conflict"
                        else:
                            row.update(status="discovered", connection="exact_model_id")
                            ws["connected_report_count"] += 1
                        if (
                            row["status"] in {"unknown", "excluded"}
                            and row.get("reason") != "different_direct_model"
                        ):
                            result["analysis_limitations"].append(
                                limitation(row["reason"], identity)
                            )
                    ws["status"] = "empty" if not seen else "enumerated"
                except ProbeError as exc:
                    ws.update(
                        status="denied"
                        if str(exc) in {"access_denied", "not_found_or_inaccessible"}
                        else "partial",
                        error=str(exc),
                    )
                    result["analysis_limitations"].append(limitation(str(exc), workspace))
                ws["finished_at"] = now()
            result["selected_scope_complete"] = not result["analysis_limitations"]
            result["status"] = (
                "complete_within_selected_scope"
                if result["selected_scope_complete"]
                else "incomplete"
            )
        except ProbeError as exc:
            result["status"] = "failed"
            result["errors"].append({"code": str(exc), "message": error_hint(str(exc))})
            result["analysis_limitations"].append(limitation(str(exc), "selected_target"))
        result["requests"] = self.evidence.data["requests"]
        result["finished_at"] = now()
        result["known_connected_report_count"] = sum(
            r["connection"] == "exact_model_id" for r in result["reports"]
        )
        result["unknown_downstream_report_count"] = None
        return result


def public_summary(result):
    """Strict allowlist for shareable evidence: no source IDs, names, paths or payloads."""
    summary = {
        "schema_version": result["schema_version"],
        "command": result["command"],
        "experimental": True,
        "evidence_kind": result["evidence_kind"],
        "live_acceptance": "unverified",
        "status": result["status"],
        "started_at": result["started_at"],
        "finished_at": result.get("finished_at"),
        "global_completeness": False,
        "selected_scope_complete": result["selected_scope_complete"],
        "searched_workspace_count": len(result["workspaces"]),
        "known_connected_report_count": result.get("known_connected_report_count", 0),
        "unknown_downstream_report_count": None,
        "report_states": {
            state: sum(r["status"] == state for r in result["reports"])
            for state in sorted({r["status"] for r in result["reports"]})
        },
        "limitation_codes": sorted({r["code"] for r in result["analysis_limitations"]}),
        "error_codes": [e["code"] for e in result["errors"]],
        "boundaries": result["boundaries"],
    }
    summary["report_health_finding_count"] = len(result["report_health"]["findings"])
    summary["definition_receipts"] = [
        {
            key: row["definition"][key]
            for key in ("format", "sha256", "retrieved_at", "cached")
            if key in row["definition"]
        }
        for row in result["reports"]
        if row.get("definition")
    ]
    if result.get("model_definition"):
        summary["model_definition"] = {
            key: result["model_definition"][key]
            for key in ("format", "sha256", "retrieved_at", "cached")
        }
    if result.get("comparison"):
        summary["comparison_counts"] = {
            key: len(result["comparison"][key])
            for key in ("pre_existing", "introduced", "resolved")
        }
        summary["validation_limits"] = result.get("validation_limits", [])
    if result.get("candidate"):
        summary["candidate"] = {
            key: result["candidate"][key]
            for key in ("sha256", "captured_at", "unchanged_after_run")
        }
    return summary


def result_exit(result):
    if result["status"] in {"failed", "cancelled"} or not result["selected_scope_complete"]:
        return 2
    if result["report_health"]["findings"]:
        return 1
    return 0
