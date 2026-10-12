"""Read-only, bounded service feasibility probe (#116); not a cleanup workflow.

Run with ``python -m semantic_model_cleaner.service_probe --help``.
Credentials and service definitions are never included in public evidence.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
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
    def __init__(self, transport, evidence, *, sleep=time.sleep, max_seconds=300):
        self.transport, self.evidence, self.sleep = transport, evidence, sleep
        self.deadline = time.monotonic() + max_seconds

    def pause(self, headers):
        try:
            delay = max(1, int(headers.get("retry-after", "1")))
        except ValueError:
            raise ProbeError("invalid_retry_after") from None
        if delay > 60 or time.monotonic() + delay >= self.deadline:
            raise ProbeError("retry_budget_exceeded")
        self.sleep(delay)

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


def analyze_snapshot(root, model_path, report_paths, evidence):
    from . import analyzer

    # Existing analyzer receives explicit service-ID-selected paths, avoiding name binding.
    # Its internal findings stay private; public projection has counts only, no Safe actions.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        result = analyzer.analyze(
            root, model_paths=[model_path], report_paths=report_paths, allow_model_only=True
        )
    evidence.data["analysis"] = {
        "model_item_count": len(result["items"]),
        "report_reference_count": len(result["report_references"]),
        "reports_scanned": len(report_paths),
        "parser_coverage_complete": result["coverage"]["complete"],
        "analysis_limitation_count": len(result["analysis_limitations"]),
        "no_use_found_in_scope_count": sum(row["status"] == "NOT USED" for row in result["items"]),
        "recommendation_for_no_use_found": "Review",
        "cleanup_actions_available": False,
    }
    evidence.data["report_health"] = {
        "checked": bool(report_paths),
        "issue_count": len(result["report_issues"]),
    }
    if result["analysis_limitations"]:
        evidence.limitation("existing_parser_analysis_limitations")
    return result


def probe(client, evidence, workspace, model, report_workspaces):
    candidates = inspect_models(client, workspace, evidence)
    if model not in {r["id"] for r in candidates}:
        raise ProbeError("selected_model_not_visible_in_workspace")
    evidence.data["selected_model"] = evidence.alias("model", model)
    evidence.limitation("bounded_discovery_not_global")
    connected = []
    for report_workspace in dict.fromkeys([workspace, *report_workspaces]):
        owner = evidence.alias("workspace", report_workspace)
        ws = {"source": owner, "enumeration": "incomplete"}
        evidence.data["workspaces"].append(ws)
        seen = {}
        try:
            for report in client.items(
                f"{POWERBI}/groups/{report_workspace}/reports", "list_reports", owner
            ):
                identity = guid(report.get("id"))
                if identity in seen:
                    if seen[identity] != report:
                        raise ProbeError("conflicting_report_identity")
                    continue
                seen[identity] = report
                row = {
                    "source": evidence.alias("report", report_workspace + "/" + identity),
                    "workspace": owner,
                    "discovered_at": now(),
                    "status": "excluded",
                    "reason": "different_direct_model",
                }
                evidence.data["reports"].append(row)
                dataset = report.get("datasetId")
                if report.get("reportType") != "PowerBIReport":
                    row.update(status="excluded", reason="unsupported_or_unknown_report_type")
                    evidence.limitation(row["reason"], row["source"])
                elif not dataset:
                    row.update(status="unknown", reason="direct_model_identity_missing")
                    evidence.limitation(row["reason"], row["source"])
                elif guid(dataset) == model:
                    # datasetWorkspaceId is not guaranteed by Get Reports In Group.
                    if (
                        report.get("datasetWorkspaceId")
                        and guid(report["datasetWorkspaceId"]) != workspace
                    ):
                        row.update(status="unknown", reason="model_workspace_conflict")
                        evidence.limitation(row["reason"], row["source"])
                    else:
                        row.update(status="discovered", reason="exact_direct_model_id")
                        connected.append((report_workspace, identity, row))
            ws["enumeration"] = "completed_for_visible_items"
        except ProbeError as exc:
            ws["reason"] = str(exc)
            evidence.limitation(str(exc), owner)
    with tempfile.TemporaryDirectory(prefix="smc-service-probe-") as temporary:
        root = Path(temporary)
        model_path = root / "Selected.SemanticModel"
        evidence.data["model_definition"] = unpack_definition(
            client.definition(workspace, "semanticModels", model, evidence.alias("model", model)),
            model_path,
            "model",
        )
        paths = []
        for report_workspace, identity, row in connected:
            try:
                path = root / (row["source"] + ".Report")
                body = client.definition(report_workspace, "reports", identity, row["source"])
                row["retrieved_at"] = now()
                row["definition"] = unpack_definition(body, path, "report")
                verify_report_binding(path, model)
                row["status"] = "retrieved"
                paths.append(path)
            except ProbeError as exc:
                row.update(
                    status="inaccessible"
                    if str(exc) in {"access_denied", "not_found_or_inaccessible"}
                    else "not_analyzed",
                    reason=str(exc),
                )
                evidence.limitation(str(exc), row["source"])
        try:
            result = analyze_snapshot(root, model_path, paths, evidence)
        except Exception:
            # Parser errors can include model names, expressions, paths or source text.
            raise ProbeError("existing_analysis_failed") from None
        for _, _, row in connected:
            if row["status"] == "retrieved":
                row["status"] = "analyzed"
        evidence.data["status"] = (
            "bounded_probe_completed" if paths and result["coverage"]["complete"] else "incomplete"
        )
        if any(ws["enumeration"] == "incomplete" for ws in evidence.data["workspaces"]) or any(
            r["status"] in {"inaccessible", "not_analyzed", "unknown"}
            for r in evidence.data["reports"]
        ):
            evidence.data["status"] = "incomplete"
        if not paths:
            evidence.limitation("no_supported_connected_report_analyzed")
        evidence.data["selected_scope_complete"] = evidence.data[
            "status"
        ] == "bounded_probe_completed" and all(
            row["code"] == "bounded_discovery_not_global"
            for row in evidence.data["analysis_limitations"]
        )
        if not evidence.data["selected_scope_complete"]:
            evidence.data["status"] = "incomplete"
    return candidates


def write_json(path, value):
    # Refuse overwrites and symlinks; public and private outputs both start owner-only.
    with open(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
    ) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "run"])
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument(
        "--tenant-id", help="Required for run; inspect derives the credential tenant."
    )
    parser.add_argument("--model-id", help="Exact ID selected after inspect; required for run.")
    parser.add_argument("--report-workspace-id", action="append", default=[])
    parser.add_argument("--evidence", type=Path, required=True, help="New sanitized JSON file.")
    parser.add_argument(
        "--private-output",
        type=Path,
        required=True,
        help="New private directory for IDs/candidate names; never publish.",
    )
    parser.add_argument(
        "--fixture", type=Path, help="Replay synthetic HTTP responses; makes NO live requests."
    )
    args = parser.parse_args(argv)
    if args.action == "run" and (not args.tenant_id or not args.model_id):
        parser.error("run requires --tenant-id and --model-id selected after inspect")
    if args.evidence.exists() or args.private_output.exists():
        parser.error("output paths must not already exist")
    evidence = Evidence("fixture" if args.fixture else "live_attempt")
    candidates = []
    code = 2
    try:
        args.private_output.mkdir(mode=0o700)
        workspace = guid(args.workspace_id)
        evidence.data["selected_workspace"] = evidence.alias("workspace", workspace)
        expected_tenant = guid(args.tenant_id) if args.tenant_id else None
        if args.fixture:
            fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
            tenant = guid(fixture["tenant_id"])
            transport = FixtureTransport(fixture)
            evidence.data["authentication"] = "synthetic_fixture_only"
        else:
            tokens, observations = authenticate()
            tenant = observations["fabric"][0]
            transport = LiveTransport(tokens)
            evidence.data["authentication"] = {
                "tenant_claim": "matched_credentials_pending_API_acceptance",
                "credential_scopes": {key: value[2] for key, value in observations.items()},
                "identity_kind": observations["fabric"][3],
                "claim_note": "Claims are decoded locally, not signature-verified here; API validates bearer tokens.",
            }
        if expected_tenant and tenant != expected_tenant:
            raise ProbeError("selected_tenant_mismatch")
        evidence.data["tenant"] = evidence.alias("tenant", tenant)
        client = Client(transport, evidence, sleep=(lambda _: None) if args.fixture else time.sleep)
        if args.action == "inspect":
            candidates = inspect_models(client, workspace, evidence)
            evidence.data.update(status="candidates_inspected", candidate_count=len(candidates))
            code = 0
        else:
            candidates = probe(
                client,
                evidence,
                workspace,
                guid(args.model_id),
                [guid(w) for w in args.report_workspace_id],
            )
            code = 0 if evidence.data["status"] == "bounded_probe_completed" else 2
        if not args.fixture:
            evidence.data["authentication"]["tenant_claim"] = (
                "credential_tenant_with_authenticated_workspace_access"
            )
    except ProbeError as exc:
        evidence.limitation(str(exc))
    except Exception:
        evidence.limitation("probe_input_or_runtime_failure")
    evidence.data["finished_at"] = now()
    evidence.data["report_counts"] = dict(
        Counter(row["status"] for row in evidence.data["reports"])
    )
    try:
        write_json(
            args.private_output / "identities.json",
            {
                "source_identities": [
                    {"kind": kind, "id": identity, "alias": alias}
                    for (kind, identity), alias in evidence.identities.items()
                ],
                "model_candidates": candidates,
            },
        )
        write_json(args.evidence, evidence.data)
    except OSError:
        print("Could not write evidence; use new output paths in an existing writable parent.")
        return 2
    print(
        f"{evidence.data['status']}; {evidence.data['evidence_kind']}; live acceptance unverified"
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
