"""Fresh, read-only deletion checks shared by UI plans and automation.

This policy validates the selected local scope; it cannot discover remote consumers.
Call again immediately before mutation. The caller must additionally bind previews
and apply to file hashes, since a successful result is not a write authorization token.
"""
from pathlib import Path

from . import analyzer


def evaluate_deletion_policy(
    model_path: Path, report_paths: list[Path], actions: list[dict], *,
    cache: "analyzer.AnalysisCache | None" = None,
) -> dict:
    """Validate deletion with fresh analysis; used by all mutation workflows.

    ``cache`` lets one change plan share the parse of its unchanged inputs
    between this check and its own baseline analysis (#169). It only replays
    files this run already read; it never stands in for the scan itself.
    """
    return _evaluate_deletion_policy(model_path, report_paths, actions, cache=cache)


def _evaluate_deletion_policy(
    model_path: Path, report_paths: list[Path], actions: list[dict], *, analysis: dict | None = None,
    cache: "analyzer.AnalysisCache | None" = None,
) -> dict:
    """Return {ok, errors, violations, scope}; never write project files.

    Each violation has rule_id/table/name/message. Non-delete batches bypass
    analysis. Deletes require a bound, readable selected report scope. An unused
    DAX chain may be removed together, but retained structural and DAX consumers
    block it. Review and inferred items are conservatively protected; inferred
    members of a calculation group or field parameter follow the unit rules.

    Coverage is evaluated against the proposed final state: a shared analysis
    limitation declared inside a model table that the plan removes completely,
    with no retained consumer left, no longer counts (issue #91).
    ``scope["complete"]`` reports that final-state coverage and
    ``scope["cleared_limitations"]`` lists what the plan cleared and why.

    A calculation group or field parameter that the plan removes as a whole,
    with nothing left that uses it, is not blocked by the hidden flag or the
    structure of its own internal columns (issue #103). It gets one
    ``confirmations`` entry with the entity-type reason instead; the plan
    preview asks the user to confirm it. Partial plans keep the item-alone
    reasons, and guards on anything outside the entity are unchanged.
    """
    violations: list[dict] = []
    scope = {"model": str(model_path), "reports": [], "complete": False, "cleared_limitations": []}
    confirmations: dict[str, dict] = {}

    def reject(rule_id: str, message: str, table: str = "", name: str = "", **evidence) -> None:
        violations.append(dict(rule_id=rule_id, table=table, name=name, message=message, **evidence))

    def result() -> dict:
        return {"ok": not violations, "errors": [v["message"] for v in violations],
                "violations": violations, "scope": scope,
                "confirmations": [confirmations[key] for key in sorted(confirmations)]}

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
    # Read-only group previews reuse their one invocation's analysis snapshot.
    # The public entry point always scans afresh before any mutation workflow.
    if analysis is None:
        try:
            analysis = analyzer.analyze(model_path.parent, model_paths=[model_path], report_paths=reports,
                                        cache=cache)
        except (Exception, SystemExit) as exc:
            reject("SMC-D001", f"Fresh analysis failed: {exc}")
            return result()
    scope["complete"] = analysis.get("coverage", {}).get("complete", False)
    for warning in analysis.get("warnings", []):
        if warning.get("code") in {"UNRESOLVED_NAMEOF_TARGET", "AMBIGUOUS_NAMEOF_TARGET"}:
            scope["complete"] = False
            reject("SMC-D002", warning["message"])
    shared_limitations = analysis.get("coverage", {}).get("limitations", [])
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
    items = [row["item"] for row in analysis["items"]]
    by_identity = {analyzer.item_identity(item): item for item in items}

    def dependency_evidence(identity):
        item = by_identity[identity]
        return dict(table=item.table, name=item.name, item_type=item.item_type,
                    source_kind=item.source_kind, file=item.source_file)
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
                    reject("SMC-D006", f"{analyzer.format_item_ref(target[-2:])} is required by retained {analyzer.format_item_ref(source[-2:])}{owner}.", *target[-2:], dependency=dependency_evidence(source),
                           location={'file': by_identity[source].source_file})
    # NAMEOF dependencies live in calculated-table definitions, not item DAX.
    # They remain structural consumers even when the parameter has no report
    # usage. Row deletions alone cannot prove the source definition will vanish
    # (for example, a table can span files); require its removal to be verified
    # in a prior plan before allowing deletion of its targets.
    parameter_warnings = []
    parameters = analyzer.resolve_field_parameter_targets(
        analyzer.parse_field_parameters(model_path, parameter_warnings),
        [row["item"] for row in rows.values()], model_path.name, parameter_warnings,
    )
    for warning in parameter_warnings:
        scope["complete"] = False
        reject("SMC-D002", warning.message)
    for parameter, dependencies in parameters:
        for dependency in dependencies:
            target = analyzer.normalize_key(*dependency.key)
            if target in targets:
                reject("SMC-D006", f"{analyzer.format_item_ref(dependency.key)} is required by NAMEOF in retained "
                       f"field parameter {parameter.table} ({parameter.source_file}).", *dependency.key,
                       dependency={'table': parameter.table, 'name': parameter.table, 'item_type': 'Table',
                                   'file': str(parameter.source_file)}, location={'file': str(parameter.source_file)})
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
    # A Report can reference an existing table but a missing item in it. The
    # last-item writer removes that table; do not turn an existing missing-item
    # problem (including visual property expressions) into a missing table.
    from .plan_diagnostics import location
    for reference in analysis.get("report_references", []):
        if reference.table.casefold() in removed_tables:
            reject("SMC-D006", f"Table {reference.table} is required by a Report Reference in "
                   f"{reference.report}, page {reference.page}, visual {reference.visual_id} "
                   f"({reference.artifact_path}: {reference.source_path}).", reference.table,
                   location=location(reference), dependency={'table': reference.table, 'name': reference.name,
                                                            'item_type': reference.ref_type})
    # Resolved metadata constructs (calculation items, KPI, detail-rows, format-string
    # and coverage expressions, calendar mappings) need their targets while the
    # construct itself remains. Table-owned constructs go only with their table.
    for consumer in analysis.get("metadata_consumers", []):
        owner_table = consumer["table"].casefold()
        if consumer["owner_kind"] in ("measure", "column"):
            owner_removed = analyzer.normalize_key(consumer["table"], consumer["owner_name"]) in targets
        else:
            owner_removed = owner_table in removed_tables
        if owner_removed:
            continue
        for key in consumer["targets"]:
            target = analyzer.normalize_key(*key)
            if target in targets:
                reject("SMC-D006", f"{analyzer.format_item_ref(tuple(key))} is required by retained "
                       f"{consumer['feature']} of {consumer['owner']} ({consumer['location']}).", *key)
    # Calendar declarations survive item-only deletes. When a calendar's column
    # mappings could not be read, protect all its table columns until a
    # whole-table plan removes the declaration as well.
    resolved_calendars = {(consumer["table"].casefold(), consumer["owner_name"].casefold())
                          for consumer in analysis.get("metadata_consumers", [])
                          if consumer["owner_kind"] == "calendar"}
    calendar_tables = {table.casefold() for name, owners in analyzer.parse_calendar_tables(model_path).items()
                       for table in owners if (table.casefold(), name) not in resolved_calendars}
    for key in sorted(targets):
        if (key[0] in calendar_tables and key[0] not in removed_tables
                and rows[key]["item"].item_type in ("Column", "Calculated Column")):
            reject("SMC-D006", f"Keep {analyzer.format_item_ref(rows[key]['item'].key)}: "
                   "its table contains a retained named calendar.", *rows[key]["item"].key)
    # Calculation groups and field parameters are units: one column alone is
    # never removed, whatever its own usage or hidden flag (issue #103).
    for key in sorted(targets):
        unit = rows[key].get("structural_unit")
        if unit and key[0] not in removed_tables:
            item = rows[key]["item"]
            reject("SMC-D006", f"Keep {analyzer.format_item_ref(item.key)}: it is a column of {unit} "
                   f"'{item.table}', which is deleted only as a whole table.", *item.key)
    for source, tables in graphs["tables"].items():
        if not removed(source):
            for table in tables:
                if table.casefold() in removed_tables:
                    owner = "" if source[0] == "model" else f" in {source[0]}"
                    reject("SMC-D006", f"Table {table} is required by retained {analyzer.format_item_ref(source[-2:])}{owner}.", table)
    # Simulated final state (#91): a table is cleared only when the plan removes
    # every model item in it and no retained structural or DAX consumer still
    # needs it. Its own shared limitations vanish with its declaration; every
    # other limitation, including targeted ones whose owner remains, still applies.
    retained_consumer_tables = {v["table"].casefold() for v in violations if v["rule_id"] == "SMC-D006"}
    cleared_tables = removed_tables - retained_consumer_tables
    remaining_limitations = []
    for limitation in shared_limitations:
        if _owned_by_cleared_table(limitation, cleared_tables):
            scope["cleared_limitations"].append(dict(limitation, cleared_reason=_cleared_reason(limitation)))
        else:
            remaining_limitations.append(limitation)
            reject("SMC-D002", limitation["message"])
    if shared_limitations and not remaining_limitations and not any(
            v["rule_id"] == "SMC-D002" for v in violations):
        scope["complete"] = True
    coverage_cleared = scope["complete"] and bool(scope["cleared_limitations"])
    for key in sorted(targets):
        row = rows[key]
        item = row["item"]
        # A target's own missing references (BROKEN) are not use; incoming
        # consumers are checked above and its usage status here.
        usage = analyzer.row_usage_status(row)
        if analyzer.is_used_status(usage) or analyzer.inferred_keep(row):
            reject("SMC-D004", f"Keep {analyzer.format_item_ref(item.key)}: {usage}.", *item.key)
        elif row.get("entity_type_trigger") and item.table.casefold() in cleared_tables:
            # The whole tool entity goes and nothing that remains uses it.
            reasons = _final_state_review_triggers(
                row, coverage_cleared=coverage_cleared, group_cleared=True,
                waived=row.get("entity_internal_triggers", []))
            if reasons:
                reject("SMC-D005", f"Review required for {analyzer.format_item_ref(item.key)}: "
                       + "; ".join(reasons), *item.key)
            confirmations.setdefault(item.table.casefold(), dict(
                kind="entity_type", table=item.table,
                message=analyzer.entity_type_trigger(row["entity_kind"], item.table, after_plan=True)))
        elif row.get("standalone_removal_risk", row["removal_risk"]) == "Review":
            reasons = _final_state_review_triggers(
                row, coverage_cleared=coverage_cleared, group_cleared=item.table.casefold() in cleared_tables)
            if reasons:
                reject("SMC-D005", f"Review required for {analyzer.format_item_ref(item.key)}: "
                       + "; ".join(reasons), *item.key)
    # Keep diagnostics deterministic and avoid duplicate edges from parser paths.
    unique = {(v["rule_id"], v["table"], v["name"], v["message"]): v for v in violations}
    violations[:] = [unique[key] for key in sorted(unique)]
    return result()


# Informational reasons appended after the Review decision; their guards are
# evaluated separately (SMC-D006) against the final state.
_RETAINED_DECLARATION_PREFIXES = analyzer._RETAINED_DECLARATION_PREFIXES


def _owned_by_cleared_table(limitation: dict, cleared_tables: set[str]) -> bool:
    """True only for model metadata declared inside a table the plan fully removes.

    Report-scan gaps and model-level constructs (no owning table) never qualify.
    """
    table = str(limitation.get("table") or "")
    return (limitation.get("kind") == "unsupported_metadata" and bool(table)
            and bool(limitation.get("owner")) and table.casefold() in cleared_tables)


def _cleared_reason(limitation: dict) -> str:
    owner = limitation["table"]
    if "calculation item" in str(limitation.get("owner", "")):
        return (f"Coverage gap owned by '{owner}' is cleared because the plan removes the calculation "
                f"group and every retained parent-table consumer.")
    return (f"Coverage gap owned by '{owner}' is cleared because the plan removes the table and every "
            f"retained consumer.")


def _final_state_review_triggers(row: dict, *, coverage_cleared: bool, group_cleared: bool,
                                 waived: list[str] = ()) -> list[str]:
    """Review reasons that still hold once the plan's removals are applied.

    The plan itself can resolve the collapsed shared coverage reason (when
    final-state coverage is complete), calculation-group structure reasons (when
    the whole group goes with all its consumers) and, for a whole tool entity,
    the ``waived`` internal reasons such as the hidden flag of its own columns.
    Every other item-specific reason (key, perspective, targeted metadata) remains.
    Starts from the item-alone reasons, never from the entity-type summary.
    """
    triggers = row.get("standalone_review_triggers", row["review_triggers"])
    resolved = set(waived)
    if coverage_cleared and row.get("shared_limitation_trigger"):
        resolved.add(row["shared_limitation_trigger"])
    if group_cleared:
        resolved.update(row.get("calculation_group_triggers", []))
    if not resolved:
        return list(triggers)
    # Retained sort/hierarchy declarations are re-checked as SMC-D006 against the
    # final state, so they are not repeated as Review reasons here.
    return [t for t in triggers
            if t not in resolved and not t.startswith(_RETAINED_DECLARATION_PREFIXES)]
