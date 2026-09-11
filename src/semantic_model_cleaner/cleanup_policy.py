"""Fresh, read-only deletion checks shared by UI plans and automation.

This policy validates the selected local scope; it cannot discover remote consumers.
Call again immediately before mutation. The caller must additionally bind previews
and apply to file hashes, since a successful result is not a write authorization token.
"""
from pathlib import Path

from . import analyzer


def evaluate_deletion_policy(
    model_path: Path, report_paths: list[Path], actions: list[dict]
) -> dict:
    """Return {ok, errors, violations, scope}; never write project files.

    Each violation has rule_id/table/name/message. Non-delete batches bypass
    analysis. Deletes require a bound, readable selected report scope. An unused
    DAX chain may be removed together, but retained structural and DAX consumers
    block it. Review and inferred items are conservatively protected.
    """
    violations: list[dict] = []
    scope = {"model": str(model_path), "reports": [], "complete": False}

    def reject(rule_id: str, message: str, table: str = "", name: str = "") -> None:
        violations.append(dict(rule_id=rule_id, table=table, name=name, message=message))

    def result() -> dict:
        return {"ok": not violations, "errors": [v["message"] for v in violations],
                "violations": violations, "scope": scope}

    deletes = [a for a in actions if isinstance(a, dict) and a.get("action") == "delete"]
    if not deletes:
        return result()
    model_path = Path(model_path).resolve()
    reports = sorted({Path(p).resolve() for p in report_paths})
    if not model_path.is_dir() or not reports:
        reject("SMC-D001", "Deletion requires one existing Semantic Model and selected bound reports.")
        return result()
    for report in reports:
        binding = analyzer.report_binding_status(report, model_path)
        scope["reports"].append({"path": str(report), "binding": binding["status"]})
        if not report.is_dir() or binding["status"] not in analyzer.BOUND_REPORT_STATUSES:
            reject("SMC-D001", f"Cannot verify selected report scope: {report.name} ({binding['status']}).")
        if not (report / "definition").is_dir():
            reject("SMC-D001", f"Report {report.name} has no supported PBIR definition directory.")
    if violations:
        return result()
    try:
        analysis = analyzer.analyze(model_path.parent, model_paths=[model_path], report_paths=reports)
    except (Exception, SystemExit) as exc:
        reject("SMC-D001", f"Fresh analysis failed: {exc}")
        return result()
    scope["complete"] = analysis.get("coverage", {}).get("complete", False)
    for warning in analysis.get("warnings", []):
        if warning.get("code") in {"UNRESOLVED_NAMEOF_TARGET", "AMBIGUOUS_NAMEOF_TARGET"}:
            scope["complete"] = False
            reject("SMC-D002", warning["message"])
    for limitation in analysis.get("coverage", {}).get("limitations", []):
        reject("SMC-D002", limitation["message"])
    rows = {analyzer.normalize_key(*r["item"].key): r for r in analysis["items"]
            if r["item"].source_kind == "model"}
    targets: set[tuple[str, str]] = set()
    for action in deletes:
        table, name = str(action.get("table", "")), str(action.get("name", ""))
        if str(action.get("item_type", "")).casefold() == "table":
            matches = {key for key in rows if key[0] == table.casefold()}
        else:
            key = analyzer.normalize_key(table, name)
            matches = {key} if key in rows and rows[key]["item"].item_type.casefold() == str(action.get("item_type", "")).casefold() else set()
        if not matches:
            reject("SMC-D003", f"Deletion target does not match a current model item: {table}[{name}].", table, name)
        targets.update(matches)
    for key in sorted(targets):
        row = rows[key]
        item = row["item"]
        if analyzer.is_used_status(row["status"]) or row["status"].startswith("BROKEN") or item.is_inferred:
            reject("SMC-D004", f"Keep {analyzer.format_item_ref(item.key)}: {row['status']}.", *item.key)
        elif row["removal_risk"] == "Review":
            reject("SMC-D005", f"Review required for {analyzer.format_item_ref(item.key)}: " + "; ".join(row["review_triggers"]), *item.key)
    items = [row["item"] for row in analysis["items"]]
    graphs = analysis.get("dependency_graphs") or analyzer.scoped_dependency_graphs(items)

    def removed(identity):
        return identity[0] == "model" and analyzer.normalize_key(*identity[-2:]) in targets

    for graph in (graphs["measures"], graphs["columns"]):
        for source, dependencies in graph.items():
            if removed(source):
                continue
            for target in dependencies:
                if removed(target):
                    owner = "" if source[0] == "model" else f" in {source[0]}"
                    reject("SMC-D006", f"{analyzer.format_item_ref(target[-2:])} is required by retained {analyzer.format_item_ref(source[-2:])}{owner}.", *target[-2:])
    # Sort-by and hierarchy declarations must remain valid even when their source
    # column currently has no live report references.
    for item in items:
        target = analyzer.normalize_key(item.table, item.sort_by_column)
        if item.sort_by_column and target in targets and analyzer.normalize_key(*item.key) not in targets:
            reject("SMC-D006", f"{analyzer.format_item_ref(target)} sorts retained {analyzer.format_item_ref(item.key)}.", *target)
    for hierarchy in analyzer.parse_hierarchies(model_path):
        for column in hierarchy.columns:
            target = analyzer.normalize_key(hierarchy.table, column)
            if target in targets:
                reject("SMC-D006", f"{analyzer.format_item_ref(target)} belongs to retained hierarchy {hierarchy.name}.", *target)
    # Removing the last model item may remove its table. Bare-table DAX consumers
    # are not represented by item-to-item edges.
    removed_tables = {key[0] for key in targets if all(k in targets for k in rows if k[0] == key[0])}
    for source, tables in graphs["tables"].items():
        if not removed(source):
            for table in tables:
                if table.casefold() in removed_tables:
                    owner = "" if source[0] == "model" else f" in {source[0]}"
                    reject("SMC-D006", f"Table {table} is required by retained {analyzer.format_item_ref(source[-2:])}{owner}.", table)
    # Keep diagnostics deterministic and avoid duplicate edges from parser paths.
    unique = {(v["rule_id"], v["table"], v["name"], v["message"]): v for v in violations}
    violations[:] = [unique[key] for key in sorted(unique)]
    return result()
