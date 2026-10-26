"""Read-only service feasibility probe; uses the shared service provider."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import time

# Re-export the original developer probe helpers for compatibility.
from .service_provider import (  # noqa: F401
    FABRIC,
    POWERBI,
    RESOURCES,
    MAX_BYTES,
    MAX_PAGES,
    BOUNDARIES,
    ProbeError,
    NoRedirect,
    LiveTransport,
    FixtureTransport,
    Evidence,
    Client,
    guid,
    now,
    token_claims,
    authenticate,
    unpack_definition,
    inspect_models,
    verify_report_binding,
    shutil,
    Target,
    ServiceProvider,
    safe_diagnostics,
)


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


def probe(client, evidence, workspace, model, report_workspaces, *, tenant):
    provider = ServiceProvider(
        Target(tenant, workspace, model, tuple([workspace, *report_workspaces]))
    )
    provider.client, provider.evidence = client, evidence
    inventory = provider.discover()
    if inventory["errors"]:
        raise ProbeError(inventory["errors"][0]["code"])
    candidates = provider.candidates
    evidence.data["selected_model"] = evidence.alias("model", model)
    evidence.limitation("bounded_discovery_not_global")
    connected = []
    for workspace_row in inventory["workspaces"]:
        alias = evidence.alias("workspace", workspace_row["workspace_id"])
        row = {
            "source": alias,
            "enumeration": "completed_for_visible_items"
            if workspace_row["status"] in {"enumerated", "empty"}
            else "incomplete",
        }
        if workspace_row.get("error"):
            row["reason"] = workspace_row["error"]
            evidence.limitation(row["reason"], alias)
        evidence.data["workspaces"].append(row)
    for report in inventory["reports"]:
        report_workspace, identity = report["workspace_id"], report["report_id"]
        row = {
            "source": evidence.alias("report", report_workspace + "/" + identity),
            "workspace": evidence.alias("workspace", report_workspace),
            "discovered_at": report["discovered_at"],
            "status": report["status"],
            "reason": report.get("reason", "exact_direct_model_id"),
        }
        evidence.data["reports"].append(row)
        if report["connection"] == "exact_model_id":
            connected.append((report_workspace, identity, row))
        elif report.get("reason") != "different_direct_model":
            evidence.limitation(row["reason"], row["source"])
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
                tenant=tenant,
            )
            code = 0 if evidence.data["status"] == "bounded_probe_completed" else 2
        if not args.fixture:
            evidence.data["authentication"]["tenant_claim"] = (
                "credential_tenant_with_authenticated_workspace_access"
            )
    except ProbeError as exc:
        evidence.limitation(str(exc))
        if exc.diagnostics:
            evidence.data["failure_diagnostics"] = safe_diagnostics(exc.diagnostics)
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
