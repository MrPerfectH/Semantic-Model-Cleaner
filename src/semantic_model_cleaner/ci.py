"""Deterministic, read-only CI checks over the same local analyzer as the UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from . import analyzer

SCHEMA_VERSION = "1.0"
# Coverage failures cannot be suppressed by baselines.
COVERAGE_RULES = {"SMC002", "SMC003", "SMC008", "SMC010", "SMC011", "SMC012"}


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def run_check(
    workspace: Path, *, model_path: Path | None = None,
    report_filters: list[str] | None = None, baseline: dict | None = None,
    fail_on: str = "error", report_paths: list[Path] | None = None, policy: dict | None = None,
) -> tuple[int, dict]:
    """Return exit 0 pass, 1 unsuppressed findings, 2 invalid input/analysis failure.

    Paths and finding fingerprints are checkout-relative. Selecting report filters
    narrows the known local scope explicitly; it never claims remote completeness.
    """
    workspace = workspace.resolve()
    payload = {"schema_version": SCHEMA_VERSION, "command": "check", "ok": False,
               "scope": {}, "findings": [], "summary": {}, "errors": []}
    try:
        if not workspace.is_dir():
            raise ValueError("Project directory does not exist.")
        if fail_on not in {"error", "warning"}:
            raise ValueError("fail_on must be error or warning.")
        if baseline is not None and (
            not isinstance(baseline, dict) or baseline.get("schema_version") != SCHEMA_VERSION
            or not isinstance(baseline.get("fingerprints"), list)
            or any(not isinstance(value, str) for value in baseline["fingerprints"])
        ):
            raise ValueError("Baseline must use schema_version 1.0 and a fingerprints array of strings.")
        models = [model_path.resolve()] if model_path else analyzer.discover_models([workspace])
        if len(models) != 1 or not models[0].is_dir():
            raise ValueError("Select exactly one existing Semantic Model with --model.")
        model = models[0]
        from . import review_policy
        repository_policy = review_policy.validate_policy(policy) if policy is not None else review_policy.load_policy(workspace)
        discovered = analyzer.discover_reports([workspace])
        if report_paths is not None:
            if report_filters:
                raise ValueError("Explicit report paths cannot be combined with report filters.")
            discovered = sorted(set(discovered) | {Path(path).resolve() for path in report_paths})
        bindings = [(report, analyzer.report_binding_status(report, model)) for report in discovered]
        bound = [report for report, binding in bindings if binding["status"] in analyzer.BOUND_REPORT_STATUSES]
        reports = sorted({Path(path).resolve() for path in report_paths}) if report_paths is not None else analyzer.filter_reports(bound, report_filters)
        if any(report not in bound for report in reports):
            raise ValueError("Every explicitly selected report must be bound to the Semantic Model.")
        if not reports:
            raise ValueError("No selected reports are bound to the Semantic Model; inspect definition.pbir or report filters.")
        if any(not (report / "definition").is_dir() for report in reports):
            raise ValueError("Selected reports require the supported PBIR definition directory.")
        payload["scope"] = {
            "model": _relative(model, workspace),
            "reports": [_relative(report, workspace) for report in reports],
            "known_bound_report_count": len(bound), "selected_report_count": len(reports),
            "selection_complete": len(reports) == len(bound),
            "external_consumers_verified": False,
            "unverified_report_count": sum(binding["status"] not in {"connected", "connected_by_name", "not_connected"} for _, binding in bindings),
            "bindings": [{"path": _relative(report, workspace), "status": binding["status"],
                          "selected": report in reports} for report, binding in bindings],
        }
        result = analyzer.analyze(workspace, model_paths=[model], report_paths=reports)
        payload["scope"]["scan_complete"] = result.get("coverage", {}).get("complete", False)
        findings: list[dict] = []

        def add(rule: str, severity: str, message: str, path: str = "", table: str = "",
                name: str = "", location: str = "") -> None:
            identity = json.dumps([rule, path, table, name, location], ensure_ascii=False, separators=(",", ":"))
            fingerprint = hashlib.sha256(identity.encode()).hexdigest()
            findings.append({"rule_id": rule, "severity": severity, "message": message,
                             "path": path, "table": table, "name": name, "location": location,
                             "fingerprint": fingerprint, "suppressed": False})

        for row in result["items"]:
            item = row["item"]
            path = _relative(Path(item.source_file), workspace) if item.source_file else _relative(model, workspace)
            if row["status"].startswith("BROKEN"):
                for detail in row.get("broken_dax_ref_details", []):
                    add("SMC001", "error", detail["message"], path, item.table, item.name, detail["ref"])
            elif row["status"] == "NOT USED" and item.source_kind == "model":
                add("SMC004", "warning", f"No usage found in the selected scope; recommendation: {row['removal_risk']}.", path, item.table, item.name)
        report_index = {analyzer.report_display_name(report): report for report in reports}
        for issue in result.get("report_issues", []):
            report = Path(issue["reportPath"]) if issue.get("reportPath") else report_index.get(issue.get("report"))
            path = _relative(report / issue.get("artifactPath", ""), workspace) if report else ""
            issue_type = issue.get("issueType", "")
            if issue_type in {"invalid_report_json", "unsupported_report_format", "ambiguous_extension_identity"}:
                rule, severity = "SMC002", "error"
            elif issue_type.startswith("stale_"):
                rule, severity = "SMC005", "warning"
            else:
                rule, severity = "SMC006", "error" if issue.get("severity") == "error" else "warning"
            add(rule, severity, issue.get("message", issue_type), path,
                issue.get("table", ""), issue.get("name", ""),
                issue_type + ":" + issue.get("sourcePath", ""))
        for metadata in result.get("unsupported_metadata", []):
            add("SMC003", "error" if metadata["unresolved_targets"] else "warning",
                f"Unsupported Metadata: {metadata['area']}; " +
                ("dependency coverage is unresolved." if metadata["unresolved_targets"] else
                 "review referenced items: " + ", ".join(metadata["targets"])),
                _relative(model / metadata["source_file"], workspace), location=metadata["area"])
        for warning in result.get("warnings", []):
            add("SMC007", "warning", warning.get("message", "Analyzer warning"),
                _relative(model, workspace), warning.get("table", ""), warning.get("name", ""), warning.get("code", ""))
        for report, binding in bindings:
            if binding["status"] not in {"connected", "connected_by_name", "not_connected"}:
                add("SMC008", "error", f"Discovered report binding is unverified ({binding['status']}); this report was excluded.",
                    _relative(report / "definition.pbir", workspace))
        naming = review_policy.naming_proposals(model, repository_policy) if repository_policy["naming_rules"] else {"proposals": [], "conflicts": []}
        sources = {(row["item"].table, row["item"].name): row["item"].source_file for row in result["items"] if row["item"].source_kind == "model"}
        for proposal in naming["proposals"]:
            source = sources.get((proposal["table"], proposal["name"]))
            if proposal["item_type"] == "Table":
                source = next((path for (table, _), path in sources.items() if table == proposal["table"]), None)
            add("SMC009", "warning", f"Naming rules propose {proposal['name']} → {proposal['target_name']}; preview before applying.",
                _relative(Path(source), workspace) if source else _relative(model, workspace),
                proposal["table"], proposal["name"], proposal["item_type"] + ":" + proposal["target_name"])
        for conflict in naming["conflicts"]:
            add("SMC010", "error", conflict, _relative(model, workspace), location=conflict)
        from .metadata_validation import validate_report_paths
        schema = validate_report_paths(reports, workspace=workspace)
        payload['schema_validation'] = {key: value for key, value in schema.items() if key != 'files'}
        for record in schema['files']:
            if record['status'] == 'invalid':
                for error in record['errors']:
                    add('SMC011', 'error', error['message'], record['path'],
                        location=str(record.get('schema')) + ':' + error['path'] + ':' + error['keyword'])
            elif record['status'] == 'not_validated':
                add('SMC012', 'warning', 'Declared schema not validated: ' + record['reason'], record['path'],
                    location=str(record.get('schema') or 'missing-schema'))
            if record.get('truncated'):
                add('SMC011', 'error', 'Schema error list is incomplete; fix errors and rerun.', record['path'], location='truncated')
        suppressed = set(baseline.get("fingerprints", [])) if baseline else set()
        unique = {finding["fingerprint"]: finding for finding in findings}
        findings = sorted(unique.values(), key=lambda f: (f["rule_id"], f["path"], f["table"], f["name"], f["location"]))
        for finding in findings:
            finding["suppressed"] = finding["rule_id"] not in COVERAGE_RULES and finding["fingerprint"] in suppressed
        findings = review_policy.annotate_findings(workspace, findings, payload["scope"], repository_policy)
        payload["policy"] = {"schema_version": repository_policy["schema_version"], "digest": repository_policy["digest"],
                             "decision_count": len(repository_policy["decisions"]), "naming_rule_count": len(repository_policy["naming_rules"])}
        failures = [f for f in findings if not f["suppressed"] and (f["severity"] == "error" or fail_on == "warning")]
        payload.update(ok=not failures, findings=findings, summary={
            "finding_count": len(findings), "failure_count": len(failures),
            "suppressed_count": sum(f["suppressed"] for f in findings),
            "fail_on": fail_on,
            "accepted_decision_count": sum(f.get("review_status") == "accepted" for f in findings),
            "stale_decision_count": sum(f.get("review_status") == "stale" for f in findings),
            "expired_decision_count": sum(f.get("review_status") == "expired" for f in findings),
        })
        return (1 if failures else 0), payload
    except (Exception, SystemExit) as exc:
        payload["errors"] = [str(exc)]
        return 2, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smc check", description="Read-only, local model/report CI checks.")
    parser.add_argument("project_path", nargs="?", default=".")
    parser.add_argument("--model", help="Semantic Model path (relative to project_path).")
    parser.add_argument("--report", action="append", help="Report-name substring filter; repeat to select reports.")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--fail-on", choices=("error", "warning"), default="error")
    parser.add_argument("--policy", type=Path, help="Repository review policy JSON (default: project/.smc-policy.json).")
    parser.add_argument("--baseline", type=Path, help="Suppress matching existing findings, except incomplete coverage.")
    parser.add_argument("--write-baseline", type=Path, help="Write current baseline; exit code still reflects this check.")
    args = parser.parse_args(argv)
    root = Path(args.project_path)
    baseline = None
    try:
        if args.baseline:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        from .review_policy import load_policy
        if args.policy and not (root / args.policy).is_file():
            raise ValueError("Explicit policy file does not exist.")
        repository_policy = load_policy(root, args.policy) if args.policy else None
        code, payload = run_check(root, policy=repository_policy, model_path=(root / args.model) if args.model else None,
                                  report_filters=args.report, baseline=baseline, fail_on=args.fail_on)
        if args.write_baseline and code != 2:
            target = args.write_baseline.resolve()
            artifact_roots = [
                *(path.resolve() for path in analyzer.discover_models([root])),
                *(path.resolve() for path in analyzer.discover_reports([root])),
                (root / payload["scope"]["model"]).resolve(),
            ]
            # Include explicit artifacts outside discovery roots and resolved
            # symlink destinations. A baseline must never become model/report
            # metadata merely because an output path was entered incorrectly.
            if any(target == artifact or target.is_relative_to(artifact) for artifact in artifact_roots) or any(
                parent.name.casefold().endswith((".semanticmodel", ".report"))
                for parent in target.parents
            ):
                raise ValueError("Baseline output must be outside Semantic Model and Report artifact folders.")
            args.write_baseline.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "fingerprints": sorted(f["fingerprint"] for f in payload["findings"] if f["rule_id"] not in COVERAGE_RULES),
            }, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        code, payload = 2, {"schema_version": SCHEMA_VERSION, "command": "check", "ok": False,
                            "scope": {}, "findings": [], "summary": {}, "errors": [str(exc)]}
    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Check {'passed' if code == 0 else 'failed'} (exit {code}).")
        for error in payload["errors"]:
            print(error)
        for finding in payload["findings"]:
            print(f"{finding['rule_id']} {finding['severity']} {finding['path']}: {finding['message']}" +
                  (" [baseline]" if finding["suppressed"] else ""))
    return code
