"""Explicit action: remove all Power BI auto-date tables, or none.

The fixture mirrors what Power BI Desktop writes (CRLF, Polish locale names): a
fact table with two date columns, each with a generated ``LocalDateTable_*``,
relationship and ``variation``, plus the ``DateTableTemplate_*`` table.

The per-table checks (``assess()["tables"]``) stay internal and keep their
coverage here; the action itself is all or nothing for the whole group.
"""
import base64
import json
import re

import pytest

from semantic_model_cleaner import auto_date_tables, change_plan

ORDER = "LocalDateTable_8ed55867-002d-48ca-ab64-c88caeda64fe"
SHIP = "LocalDateTable_5322b399-016f-4d3c-b684-4db41be8f5aa"
TEMPLATE = "DateTableTemplate_cc871eef-dce2-4592-aa62-68d4b87609b9"
ORDER_REL = "c6d1fd99-3747-45f9-8701-c75df75e375e"
SHIP_REL = "920bdf0d-8b0c-45c7-ad07-057dcfb956d6"
ALL = {"kind": "auto_date_tables", "remove": "all"}
BLOCKED_USE = "3 auto-date tables detected. Cannot remove all: dependencies were found. Nothing will be removed."
BLOCKED_COVERAGE = ("3 auto-date tables detected. Cannot remove all: coverage could not be confirmed. "
                    "Nothing will be removed.")


def crlf(*lines):
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def date_column(name, relationship, table):
    return [f"\tcolumn {name}", "\t\tdataType: dateTime", "\t\tformatString: Long Date",
            f"\t\tsourceColumn: {name}", "", "\t\tvariation Odmiana", "\t\t\tisDefault",
            f"\t\t\trelationship: {relationship}", f"\t\t\tdefaultHierarchy: {table}.'Hierarchia dat'", "",
            "\t\tannotation SummarizationSetBy = Automatic", ""]


def auto_table(name, tag, *, source, local=True):
    flags = ["\tisHidden", "\tshowAsVariationsOnly"] if local else ["\tisHidden", "\tisPrivate"]
    marker = "__PBI_LocalDateTable" if local else "__PBI_TemplateDateTable"
    return crlf(
        f"table {name}", *flags, f"\tlineageTag: {tag}0000-0000-0000-0000-000000000000", "",
        "\tcolumn Date", "\t\tdataType: dateTime", "\t\tisHidden", f"\t\tlineageTag: {tag}0000-0000-0000-0000-000000000001",
        "\t\tdataCategory: PaddedDateTableDates", "\t\tsummarizeBy: none", "\t\tisNameInferred",
        "\t\tsourceColumn: [Date]", "", "\t\tannotation SummarizationSetBy = User", "",
        "\tcolumn Rok = YEAR([Date])", "\t\tdataType: int64", "\t\tisHidden", "\t\tdataCategory: Years",
        "\t\tsummarizeBy: none", "", "\t\tannotation TemplateId = Year", "",
        "\tcolumn 'Numer miesiąca' = MONTH([Date])", "\t\tdataType: int64", "\t\tisHidden", "\t\tsummarizeBy: none", "",
        "\t\tannotation TemplateId = MonthNumber", "",
        "\tcolumn Miesiąc = FORMAT([Date], \"MMMM\")", "\t\tdataType: string", "\t\tisHidden",
        "\t\tsummarizeBy: none", "\t\tsortByColumn: 'Numer miesiąca'", "", "\t\tannotation TemplateId = Month", "",
        "\thierarchy 'Hierarchia dat'", f"\t\tlineageTag: {tag}0000-0000-0000-0000-000000000002", "",
        "\t\tlevel Rok", "\t\t\tcolumn: Rok", "", "\t\tlevel Miesiąc", "\t\t\tcolumn: Miesiąc", "",
        "\t\tannotation TemplateId = DateHierarchy", "",
        f"\tpartition {name} = calculated", "\t\tmode: import", f"\t\tsource = {source}", "",
        f"\tannotation {marker} = true")


def calendar(column):
    return (f"Calendar(Date(Year(MIN('Sales'[{column}])), 1, 1), "
            f"Date(Year(MAX('Sales'[{column}])), 12, 31))")


def project(tmp_path, *, measure="1", visual=None):
    model = tmp_path / "SCORECARD.SemanticModel"
    report = tmp_path / "SCORECARD.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_bytes(crlf(
        "table Sales", "\tlineageTag: 11111111-1111-1111-1111-111111111111", "",
        f"\tmeasure Total = {measure}", "", "\tcolumn Amount", "\t\tdataType: int64", "\t\tsourceColumn: Amount", "",
        *date_column("OrderDate", ORDER_REL, ORDER), *date_column("ShipDate", SHIP_REL, SHIP),
        "\tpartition Sales = m", "\t\tmode: import", "\t\tsource = let Source = 1 in Source"))
    (tables / f"{ORDER}.tmdl").write_bytes(auto_table(ORDER, "aaaaaaaa", source=calendar("OrderDate")))
    (tables / f"{SHIP}.tmdl").write_bytes(auto_table(SHIP, "bbbbbbbb", source=calendar("ShipDate")))
    (tables / f"{TEMPLATE}.tmdl").write_bytes(
        auto_table(TEMPLATE, "cccccccc", source="Calendar(Date(2015,1,1), Date(2015,1,1))", local=False))
    (model / "definition/model.tmdl").write_bytes(crlf(
        "model Model", "\tculture: pl-PL", "", "annotation __PBI_TimeIntelligenceEnabled = 1", "",
        "ref table Sales", f"ref table {TEMPLATE}", f"ref table {ORDER}", f"ref table {SHIP}", "",
        "ref cultureInfo pl-PL"))
    (model / "definition/relationships.tmdl").write_bytes(crlf(
        f"relationship {ORDER_REL}", "\tjoinOnDateBehavior: datePartOnly", "\tfromColumn: Sales.OrderDate",
        f"\ttoColumn: {ORDER}.Date", "",
        f"relationship {SHIP_REL}", "\tjoinOnDateBehavior: datePartOnly", "\tfromColumn: Sales.ShipDate",
        f"\ttoColumn: {SHIP}.Date", ""))
    (model / "definition.pbism").write_text('{"version": "4.0"}', encoding="utf-8")
    page = report / "definition/pages/p1"
    page.mkdir(parents=True)
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../SCORECARD.SemanticModel"}}}), encoding="utf-8")
    if visual is not None:
        (page / "visuals/v1").mkdir(parents=True)
        (page / "visuals/v1/visual.json").write_text(json.dumps(visual), encoding="utf-8")
    return model, report


def hierarchy_visual(entity="Sales", prop="OrderDate", source_ref=None):
    source = {"PropertyVariationSource": {"Expression": {"SourceRef": source_ref or {"Entity": entity}},
                                          "Name": "Odmiana", "Property": prop}}
    return {"visual": {"query": {"queryState": {"Category": {"projections": [{"field": {"HierarchyLevel": {
        "Expression": {"Hierarchy": {"Expression": source, "Hierarchy": "Hierarchia dat"}}, "Level": "Rok"}},
        "queryRef": f"{entity}.{prop}.Odmiana.Hierarchia dat.Rok"}]}}}}}


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def tables_by_name(model, report):
    return {t["table"]: t for t in auto_date_tables.assess(model, [report])["tables"]}


def blocker_text(entry):
    return " ".join(b["message"] for b in entry["blockers"])


def bare_lf(data):
    return re.search(rb"(?<!\r)\n", data) is not None


def write_culture(model, payload, *, raw=None, tail="\t\tcontentType: json"):
    """A culture file shaped like Power BI Desktop writes it (CRLF, JSON indented under linguisticMetadata)."""
    text = raw if raw is not None else json.dumps(payload, indent=2, ensure_ascii=False)
    (model / "definition/cultures").mkdir(exist_ok=True)
    path = model / "definition/cultures/pl-PL.tmdl"
    path.write_bytes(crlf("cultureInfo pl-PL", "", "\tlinguisticMetadata =",
                          *("\t\t\t" + line for line in text.splitlines()), *([tail] if tail else []), ""))
    return path


def linguistic(*bindings):
    """Desktop's format: ConceptualEntity = owner table, VariationSource = date column, VariationSet = variation."""
    entities = {f"e{i}": {"Definition": {"Binding": binding}, "State": "Generated",
                          "Terms": [{"rok": {"State": "Generated"}}]} for i, binding in enumerate(bindings)}
    return {"Version": "4.1.0", "Language": "pl-PL", "Entities": entities}


def date_binding(entity="Sales", column="OrderDate", level="Rok"):
    binding = {"ConceptualEntity": entity, "VariationSource": column, "VariationSet": "Odmiana",
               "Hierarchy": "Hierarchia dat"}
    return {**binding, "HierarchyLevel": level} if level else binding


def group(model, report):
    return auto_date_tables.assess(model, [report])["group"]


def blocked(model, report, message=BLOCKED_USE):
    """The whole group is refused: the summary says so and a preview request writes nothing."""
    summary = group(model, report)
    assert (summary["status"], summary["can_remove_all"], summary["message"]) == ("blocked", False, message)
    return summary


def all_plan(model, report):
    return change_plan.create_plan(model, [report], [dict(ALL)])


def plan_error(model, report, operation=ALL):
    before = snapshot(model.parent)
    with pytest.raises(change_plan.PlanError) as error:
        change_plan.create_plan(model, [report], [dict(operation)])
    assert snapshot(model.parent) == before
    return str(error.value)


def journal_of(tmp_path):
    return tmp_path.parent / f"{tmp_path.name}-journal"


def reseal(plan, *, operations=None, changes=None):
    """A saved plan edited and resealed, like an older plan artifact (the digest is not a signature)."""
    plan = json.loads(json.dumps(plan))
    if operations is not None:
        plan["operations"] = operations
    if changes is not None:
        plan["changes"] = changes
        outputs = dict(plan["inputs"])
        for change in changes:
            after = change["after"]
            if after is None:
                outputs.pop(change["path"], None)
            else:
                outputs[change["path"]] = change_plan._digest(base64.b64decode(after))
        plan["outputs"] = outputs
    plan["digest"] = change_plan._seal(plan)
    return plan


def apply_refused(tmp_path, plan, match):
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match=match):
        change_plan.apply_plan(plan, journal_of(tmp_path))
    assert snapshot(tmp_path) == before, "nothing is written"
    assert not (journal_of(tmp_path) / f"{plan['id']}.receipt.json").exists()


def test_all_auto_date_tables_are_removed_through_plan_apply_verify_and_restore(tmp_path):
    model, report = project(tmp_path)
    assessment = auto_date_tables.assess(model, [report])
    assert assessment["found"] == 3 and assessment["time_intelligence_enabled"] is True
    assert assessment["group"] == {
        "found": 3, "status": "removable", "can_remove_all": True, "reasons": [],
        "message": "3 auto-date tables detected. All can be removed.",
        "scope_note": "Checked: this model and 1 selected report. Reports that are not selected, Excel and other "
                      "tools that connect to the published model were not checked.",
        "time_intelligence_enabled": True}
    by_name = {t["table"]: t for t in assessment["tables"]}
    assert by_name[ORDER]["date_column"] == "Sales[OrderDate]" and by_name[TEMPLATE]["kind"] == "template"
    before = snapshot(tmp_path)

    plan = all_plan(model, report)
    assert snapshot(tmp_path) == before, "preview must not write"
    # The plan records the whole group found at preview time.
    assert plan["operations"] == [{**ALL, "tables": sorted([ORDER, SHIP, TEMPLATE])}]
    changes = {c["path"]: c["change"] for c in plan["changes"]}
    assert changes == {f"model/definition/tables/{name}.tmdl": "deleted" for name in (ORDER, SHIP, TEMPLATE)} | {
        "model/definition/model.tmdl": "modified", "model/definition/relationships.tmdl": "deleted",
        "model/definition/tables/Sales.tmdl": "modified"}
    assert any("Auto date/time stays on" in text for text in plan["validation"]["confirmations"])
    assert any("Remove all 3 auto-date table(s). 2 date column(s) stay" in text
               for text in plan["validation"]["confirmations"])

    assert change_plan.apply_plan(plan, journal_of(tmp_path))["ok"]
    assert change_plan.verify_plan(plan)["state"] == "applied"
    sales = (model / "definition/tables/Sales.tmdl").read_bytes()
    model_tmdl = (model / "definition/model.tmdl").read_bytes()
    # Business date columns stay; only the generated variation goes.
    assert b"\tcolumn OrderDate\r\n" in sales and b"\tcolumn ShipDate\r\n" in sales and b"variation" not in sales
    assert b"\t\tsourceColumn: OrderDate\r\n\r\n\t\tannotation SummarizationSetBy = Automatic\r\n" in sales
    assert model_tmdl == crlf("model Model", "\tculture: pl-PL", "", "annotation __PBI_TimeIntelligenceEnabled = 1",
                              "", "ref table Sales", "", "ref cultureInfo pl-PL")
    assert not bare_lf(sales) and not bare_lf(model_tmdl)
    assert auto_date_tables.integrity_problems(model, [report]) == set()
    assert group(model, report)["message"] == "No auto-date tables detected."

    assert change_plan.restore_plan(plan, journal_of(tmp_path))["ok"]
    assert snapshot(tmp_path) == before


def test_model_without_auto_date_tables_offers_nothing(tmp_path):
    model, report = project(tmp_path)
    assert change_plan.apply_plan(all_plan(model, report), journal_of(tmp_path))["ok"]
    summary = group(model, report)
    assert (summary["status"], summary["found"], summary["can_remove_all"]) == ("none", 0, False)
    assert summary["message"] == "No auto-date tables detected." and summary["reasons"] == []
    assert "No auto-date tables detected" in plan_error(model, report)
    assert not auto_date_tables.remove_all(model, [report])["ok"]


def test_report_hierarchy_use_blocks_the_whole_group(tmp_path):
    model, report = project(tmp_path, visual=hierarchy_visual())
    tables = tables_by_name(model, report)
    assert not tables[ORDER]["removable"]
    assert "uses the date hierarchy of Sales[OrderDate]" in blocker_text(tables[ORDER])
    assert tables[SHIP]["removable"] and tables[TEMPLATE]["removable"], "internal check: only ORDER is used"
    summary = blocked(model, report)
    assert summary["reasons"] == ["1 table: a selected report uses its date hierarchy."]
    error = plan_error(model, report)
    assert BLOCKED_USE in error and "a selected report uses its date hierarchy" in error


def test_report_query_ref_alone_blocks_its_table(tmp_path):
    visual = {"filterConfig": {"filters": [{"field": {"queryRef": "Sales.ShipDate.Odmiana.Hierarchia dat.Rok"}}]}}
    model, report = project(tmp_path, visual=visual)
    tables = tables_by_name(model, report)
    assert not tables[SHIP]["removable"] and tables[ORDER]["removable"]
    blocked(model, report)


def test_report_naming_the_auto_table_blocks_it(tmp_path):
    visual = {"visual": {"query": {"Select": [{"Column": {"Expression": {"SourceRef": {"Entity": ORDER}},
                                                         "Property": "Rok"}}]}}}
    model, report = project(tmp_path, visual=visual)
    entry = tables_by_name(model, report)[ORDER]
    assert not entry["removable"] and entry["blockers"][0]["code"] == "report_reference"
    assert blocked(model, report)["reasons"] == ["1 table: a selected report names it."]


@pytest.mark.parametrize("measure, blocked_table, code, reason", [
    (f"CALCULATE([Total], '{ORDER}'[Rok] = 2024)", ORDER, "model_reference", "measure Total in table Sales"),
    ("MAX(Sales[ShipDate].[Rok])", SHIP, "variation_dax", "through [ShipDate].["),
])
def test_dax_dependency_blocks_the_whole_group(tmp_path, measure, blocked_table, code, reason):
    model, report = project(tmp_path, measure=measure)
    tables = tables_by_name(model, report)
    entry = tables[blocked_table]
    assert not entry["removable"] and entry["blockers"][0]["code"] == code
    assert reason in blocker_text(entry)
    assert {name for name, t in tables.items() if t["removable"]} == {ORDER, SHIP, TEMPLATE} - {blocked_table}
    blocked(model, report)
    assert BLOCKED_USE in plan_error(model, report)


def test_ordinary_lookalike_table_blocks_the_group_and_is_preserved(tmp_path):
    model, report = project(tmp_path)
    lookalike = "LocalDateTable_00000000-0000-0000-0000-000000000000"
    path = model / f"definition/tables/{lookalike}.tmdl"
    path.write_bytes(crlf(f"table {lookalike}", "\tlineageTag: 12121212-0000-0000-0000-000000000000", "",
                          "\tcolumn Date", "\t\tdataType: dateTime", "\t\tsourceColumn: Date", "",
                          f"\tpartition {lookalike} = m", "\t\tmode: import", "\t\tsource = let x = 1 in x"))
    entry = tables_by_name(model, report)[lookalike]
    assert not entry["removable"] and entry["blockers"][0]["code"] == "not_generated"
    assert "no '__PBI_LocalDateTable = true' annotation" in blocker_text(entry)
    summary = blocked(model, report, BLOCKED_COVERAGE.replace("3 auto-date", "4 auto-date"))
    assert summary["reasons"] == ["1 table: its metadata does not exactly match what Power BI generates."]
    assert "coverage could not be confirmed" in plan_error(model, report)


def _extra_relationship_property(model, report):
    path = model / "definition/relationships.tmdl"
    path.write_bytes(path.read_bytes().replace(b"\tfromColumn: Sales.OrderDate", b"\tisActive: false\r\n\tfromColumn: Sales.OrderDate"))
    return ORDER, "non-generated metadata 'isActive'"


def _unmatched_report_hierarchy(model, report):
    visual = report / "definition/pages/p1/visuals/v1"
    visual.mkdir(parents=True)
    (visual / "visual.json").write_text(json.dumps(hierarchy_visual(source_ref={"Source": "unknown"})), encoding="utf-8")
    return ORDER, "could not be matched to a date column"


def _unreadable_report_file(model, report):
    (report / "definition/pages/p1/page.json").write_text("{not json", encoding="utf-8")
    return SHIP, "is not valid JSON"


def _culture_mention(model, report):
    (model / "definition/cultures").mkdir()
    (model / "definition/cultures/pl-PL.tmdl").write_bytes(crlf(
        "cultureInfo pl-PL", "", "\tlinguisticMetadata =", "\t\t\t{", f'\t\t\t  "Entities": {{"x": {{"ConceptualEntity": "{SHIP}"}}}}', "\t\t\t}"))
    return SHIP, "Culture metadata names this table"


def _extra_template_column(model, report):
    path = model / f"definition/tables/{TEMPLATE}.tmdl"
    path.write_bytes(path.read_bytes().replace(b"\thierarchy", b"\tcolumn Extra = 1\r\n\t\tisHidden\r\n\r\n\thierarchy"))
    return TEMPLATE, "Calculated column Extra is not a generated date part"


@pytest.mark.parametrize("mutate", [_extra_relationship_property, _unmatched_report_hierarchy,
                                    _unreadable_report_file, _culture_mention, _extra_template_column])
def test_ambiguous_or_unsupported_metadata_blocks_the_whole_group(tmp_path, mutate):
    model, report = project(tmp_path)
    table, reason = mutate(model, report)
    entry = tables_by_name(model, report)[table]
    assert not entry["removable"]
    assert reason in blocker_text(entry)
    assert group(model, report)["status"] == "blocked"
    # Invalid report JSON is also refused earlier by the shared plan checks.
    assert re.search("Cannot remove all|Incomplete or invalid metadata", plan_error(model, report))


@pytest.mark.parametrize("operation, message", [
    ({"kind": "auto_date_tables", "tables": [ORDER]}, "a table list is not accepted"),
    ({"kind": "auto_date_tables", "tables": [ORDER, SHIP, TEMPLATE]}, "a table list is not accepted"),
    ({**ALL, "tables": [ORDER]}, "a table list is not accepted"),
    ({**ALL, "tables": [ORDER, SHIP, TEMPLATE]}, "a table list is not accepted"),
    ({"kind": "auto_date_tables", "tables": []}, "a table list is not accepted"),
    ({"kind": "auto_date_tables"}, "Unsupported auto-date table request"),
    ({"kind": "auto_date_tables", "remove": "unused"}, "Unsupported auto-date table request"),
    ({**ALL, "table": ORDER}, "Unsupported auto-date table request"),
])
def test_subset_and_unknown_requests_are_refused_server_side(tmp_path, operation, message):
    model, report = project(tmp_path)
    assert message in plan_error(model, report, operation)


def test_writer_level_removal_has_no_subset_path(tmp_path):
    model, report = project(tmp_path)
    before = snapshot(tmp_path)
    for planned in ([ORDER], [ORDER, SHIP], [TEMPLATE], [ORDER, SHIP, TEMPLATE, "LocalDateTable_x"]):
        result = auto_date_tables.remove_all(model, [report], planned=planned)
        assert not result["ok"] and "changed after the preview" in result["error"]
    assert snapshot(tmp_path) == before
    assert not hasattr(auto_date_tables, "remove_tables") and not hasattr(auto_date_tables, "requested_tables")


def test_stale_plan_is_rejected_and_nothing_is_written(tmp_path):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    (report / "definition/report.json").write_text('{"edited": true}', encoding="utf-8")
    apply_refused(tmp_path, plan, "Stale plan")


def test_consumer_added_after_preview_makes_the_plan_stale(tmp_path):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    (report / "definition/pages/p1/visuals/v1").mkdir(parents=True)
    (report / "definition/pages/p1/visuals/v1/visual.json").write_text(json.dumps(hierarchy_visual()), encoding="utf-8")
    apply_refused(tmp_path, plan, "Stale plan")


def test_auto_date_table_added_after_preview_makes_the_plan_stale(tmp_path):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    extra = "LocalDateTable_99999999-9999-9999-9999-999999999999"
    (model / f"definition/tables/{extra}.tmdl").write_bytes(auto_table(extra, "dddddddd", source=calendar("OrderDate")))
    apply_refused(tmp_path, plan, "Stale plan")


def test_apply_checks_the_group_again_on_the_server(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    real = auto_date_tables.assess

    def now_blocked(*args, **kwargs):
        result = real(*args, **kwargs)
        for entry in result["tables"]:
            entry["removable"] = False
            entry["blockers"] = [{"code": "report_hierarchy", "message": "Now used by a report.", "location": ""}]
        return result  # "group" is stale on purpose: the gate recomputes it.

    monkeypatch.setattr(auto_date_tables, "assess", now_blocked)
    apply_refused(tmp_path, plan, "checked again before apply.*Cannot remove all: dependencies were found")


def test_apply_refuses_a_group_that_grew_after_the_preview(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    real = auto_date_tables.assess

    def new_local_table(*args, **kwargs):
        result = real(*args, **kwargs)
        result["tables"].append({**result["tables"][0], "table": "LocalDateTable_99999999-9999-9999-9999-999999999999"})
        return result

    monkeypatch.setattr(auto_date_tables, "assess", new_local_table)
    apply_refused(tmp_path, plan, r"checked again before apply.*changed after the preview \(3 planned, 4 now\)")


def test_legacy_partial_plan_is_refused_at_apply(tmp_path):
    """A per-table plan saved by an earlier version: old operation shape, partial change set."""
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    order_file = f"model/definition/tables/{ORDER}.tmdl"
    partial = [c for c in plan["changes"] if c["path"] == order_file]
    legacy = reseal(plan, operations=[{"kind": "auto_date_tables", "tables": [ORDER]}], changes=partial)
    change_plan._check(legacy)  # A well-formed saved plan; only the auto-date gate refuses it.
    apply_refused(tmp_path, legacy, "checked again before apply.*Partial removal is no longer supported")
    path = journal_of(tmp_path) / "legacy.plan.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")
    apply_refused(tmp_path, change_plan.load_plan(path), "Partial removal is no longer supported")


@pytest.mark.parametrize("edit, match", [
    # New operation shape, but only part of the group in the change set.
    (lambda plan: {"changes": [c for c in plan["changes"] if c["path"].endswith(f"{ORDER}.tmdl")]},
     "does not remove 2 of the 3 auto-date tables"),
    (lambda plan: {"changes": [c for c in plan["changes"] if not c["path"].endswith(f"{TEMPLATE}.tmdl")]},
     "does not remove 1 of the 3 auto-date tables"),
    # Planned group narrowed to a subset.
    (lambda plan: {"operations": [{**ALL, "tables": [ORDER]}]}, r"changed after the preview \(1 planned, 3 now\)"),
    (lambda plan: {"operations": [{**ALL, "tables": [ORDER, SHIP, TEMPLATE], "extra": 1}]},
     "Partial removal is no longer supported"),
    # A change outside the generated metadata.
    (lambda plan: {"changes": [*plan["changes"], {"path": "report-1/definition/report.json", "change": "modified",
                                                   "before": base64.b64encode(b"{}").decode(),
                                                   "after": base64.b64encode(b'{"x": 1}').decode()}]},
     "changes files outside the auto-date tables' generated metadata: report-1/definition/report.json"),
])
def test_resealed_plan_must_remove_exactly_the_current_group(tmp_path, edit, match):
    model, report = project(tmp_path)
    plan = all_plan(model, report)
    apply_refused(tmp_path, reseal(plan, **edit(plan)), "checked again before apply.*" + match)


@pytest.mark.parametrize("operations, message", [
    ([{"kind": "auto_date_tables", "tables": ["Sales"]}], "a table list is not accepted"),
    ([ALL, {"kind": "actions", "actions": [{"action": "hide", "table": "Sales", "name": "Amount", "item_type": "Column"}]}],
     "plan of their own"),
])
def test_plan_rejects_invalid_requests(tmp_path, operations, message):
    model, report = project(tmp_path)
    with pytest.raises(change_plan.PlanError, match=message):
        change_plan.create_plan(model, [report], operations)


def test_general_delete_policy_still_refuses_auto_date_items(tmp_path):
    model, report = project(tmp_path)
    actions = [{"action": "delete", "table": ORDER, "name": name, "item_type": kind}
               for name, kind in (("Date", "Column"), ("Rok", "Calculated Column"),
                                  ("Numer miesiąca", "Calculated Column"), ("Miesiąc", "Calculated Column"))]
    with pytest.raises(change_plan.PlanError, match="USED"):
        change_plan.create_plan(model, [report], [{"kind": "actions", "actions": actions}])


def test_removal_without_a_report_is_blocked(tmp_path):
    model, _ = project(tmp_path)
    result = auto_date_tables.assess(model, [])
    assert result["found"] == 3 and not any(t["removable"] for t in result["tables"])
    summary = result["group"]
    assert summary["message"] == BLOCKED_COVERAGE
    assert summary["reasons"][0].startswith("Select at least one report")
    assert summary["scope_note"].startswith("Checked: this model and 0 selected reports.")


def test_writer_level_removal_refuses_a_blocked_group(tmp_path):
    model, report = project(tmp_path, measure=f"COUNTROWS('{SHIP}')")
    before = snapshot(tmp_path)
    result = auto_date_tables.remove_all(model, [report])
    assert not result["ok"] and BLOCKED_USE in result["error"]
    assert "1 table: the model or a saved DAX query names it." in result["error"]
    assert snapshot(tmp_path) == before


def test_web_summary_is_group_level_and_plan_lifecycle(tmp_path, monkeypatch):
    from semantic_model_cleaner import webapp
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path.parent / f"{tmp_path.name}-state"))
    client = webapp.app.test_client()
    used, clean = tmp_path / "used", tmp_path / "clean"
    used.mkdir(), clean.mkdir()
    model, report = project(used, visual=hierarchy_visual())
    scope = {"model_path": str(model), "report_paths": [str(report)]}
    summary = client.post("/api/auto-date-tables", json=scope).get_json()
    assert set(summary) == {"ok", "scope", "found", "status", "can_remove_all", "message", "reasons", "scope_note",
                            "time_intelligence_enabled"}, "no per-table data in the UI response"
    assert (summary["status"], summary["message"]) == ("blocked", BLOCKED_USE)
    before = snapshot(used)
    response = client.post("/api/plans", json={**scope, "operations": [dict(ALL)]})
    assert response.status_code == 400 and BLOCKED_USE in response.get_json()["error"]
    for subset in ([SHIP], [SHIP, TEMPLATE]):
        response = client.post("/api/plans", json={**scope, "operations": [{"kind": "auto_date_tables", "tables": subset}]})
        assert response.status_code == 400 and "a table list is not accepted" in response.get_json()["error"]
    assert snapshot(used) == before

    model, report = project(clean)
    scope = {"model_path": str(model), "report_paths": [str(report)]}
    summary = client.post("/api/auto-date-tables", json=scope).get_json()
    assert (summary["status"], summary["can_remove_all"]) == ("removable", True)
    response = client.post("/api/plans", json={**scope, "operations": [{"kind": "auto_date_tables", "tables": [SHIP]}]})
    assert response.status_code == 400 and "a table list is not accepted" in response.get_json()["error"]
    preview = client.post("/api/plans", json={**scope, "operations": [dict(ALL)]})
    assert preview.status_code == 200, preview.get_json()
    plan = preview.get_json()["plan"]
    assert client.post(f"/api/plans/{plan['id']}/apply").get_json()["ok"]
    assert not any((model / f"definition/tables/{name}.tmdl").exists() for name in (ORDER, SHIP, TEMPLATE))
    assert client.post("/api/auto-date-tables", json=scope).get_json()["status"] == "none"
    assert client.post(f"/api/plans/{plan['id']}/restore").get_json()["ok"]
    assert all((model / f"definition/tables/{name}.tmdl").exists() for name in (ORDER, SHIP, TEMPLATE))


def test_summary_action_is_wired_into_the_workspace():
    from pathlib import Path
    source = Path(auto_date_tables.__file__).parent
    template = (source / "templates/index_v2.html").read_text(encoding="utf-8")
    script = (source / "static/auto-date-tables.js").read_text(encoding="utf-8")
    assert "auto-date-tables.js" in template
    assert "Preview removal of all auto-date tables" in script
    assert "'/api/auto-date-tables'" in script and "{ kind: 'auto_date_tables', remove: 'all' }" in script
    assert "smcReviewOperations" in script, "removal must use the shared reviewed-plan workflow"
    for per_table in ("checkbox", "tables:", "requires_tables", "Select all", "removable_count"):
        assert per_table not in script, f"no per-table selection in the UI: {per_table}"


def test_operations_schema_accepts_only_the_whole_group():
    from semantic_model_cleaner.operations_contract import parse_operations
    assert parse_operations({"schema_version": "1.0", "operations": [dict(ALL)]}) == [ALL]
    for operation in ({**ALL, "tables": [ORDER]}, {"kind": "auto_date_tables", "tables": [ORDER]},
                      {"kind": "auto_date_tables"}, {**ALL, "remove": "unused"}):
        with pytest.raises(ValueError, match="Invalid operations"):
            parse_operations({"schema_version": "1.0", "operations": [operation]})


# --- Review round 1 (3219863): F1 linguistic bindings ------------------------------------------


@pytest.mark.parametrize("binding", [
    date_binding(),
    date_binding(level=None),
    date_binding(entity="SALES", column="orderdate"),  # Case-insensitive owner match.
    # Reviewer's variant: date column in ConceptualProperty, variation name in VariationSource.
    {"ConceptualEntity": "Sales", "ConceptualProperty": "OrderDate", "VariationSource": "Odmiana",
     "VariationSet": "Hierarchia dat", "Hierarchy": "Hierarchia dat", "HierarchyLevel": "Rok"},
])
def test_linguistic_date_hierarchy_binding_blocks_the_group_and_keeps_the_culture(tmp_path, binding):
    model, report = project(tmp_path)
    culture = write_culture(model, linguistic({"ConceptualEntity": "Sales", "ConceptualProperty": "Amount"}, binding))
    before = culture.read_bytes()
    tables = tables_by_name(model, report)
    entry = tables[ORDER]
    assert not entry["removable"] and [b["code"] for b in entry["blockers"]] == ["linguistic_hierarchy"]
    assert "culture pl-PL binds the date hierarchy of Sales[OrderDate]" in blocker_text(entry)
    # Location = the second binding's ConceptualEntity line in the culture file.
    lines = [i for i, text in enumerate(culture.read_text(encoding="utf-8").splitlines(), 1) if '"ConceptualEntity"' in text]
    assert entry["blockers"][0]["location"] == f"model/definition/cultures/pl-PL.tmdl:{lines[1]}"
    assert tables[SHIP]["removable"] and tables[TEMPLATE]["removable"]
    assert blocked(model, report)["reasons"] == ["1 table: Q&A linguistic metadata binds its date hierarchy."]
    assert "Q&A linguistic metadata binds its date hierarchy" in plan_error(model, report)
    assert not auto_date_tables.remove_all(model, [report])["ok"]
    assert culture.read_bytes() == before, "linguistic metadata is never edited"


def test_json_escaped_linguistic_binding_blocks(tmp_path):
    model, report = project(tmp_path)
    raw = json.dumps(linguistic(date_binding()), indent=2).replace('"Sales"', '"Sale\\u0073"').replace(
        '"OrderDate"', '"Order\\u0044ate"')
    assert "Sale\\u0073" in raw and json.loads(raw)["Entities"]["e0"]["Definition"]["Binding"]["ConceptualEntity"] == "Sales"
    write_culture(model, None, raw=raw)
    assert [b["code"] for b in tables_by_name(model, report)[ORDER]["blockers"]] == ["linguistic_hierarchy"]
    blocked(model, report)


def test_linguistic_bindings_that_do_not_use_a_date_hierarchy_do_not_block(tmp_path):
    model, report = project(tmp_path)
    culture = write_culture(model, linguistic({"ConceptualEntity": "Sales", "ConceptualProperty": "OrderDate"},
                                              {"ConceptualEntity": "Sales"}, date_binding(entity="Other")))
    before = culture.read_bytes()
    assert all(t["removable"] for t in tables_by_name(model, report).values())
    assert group(model, report)["can_remove_all"]
    assert change_plan.apply_plan(all_plan(model, report), journal_of(tmp_path))["ok"]
    assert culture.read_bytes() == before


@pytest.mark.parametrize("raw, tail, reason", [
    ('{"Version": "4.1.0", "Entities": {', "\t\tcontentType: json", "cannot be read as JSON"),
    ("<Linguistic />", "\t\tcontentType: xml", "cannot be read as JSON"),
    (json.dumps(linguistic(date_binding())), "\t\tcontentType: xml", "unsupported content after the JSON payload"),
    ('{"Entities": {"a": {"Definition": {"Binding": {"ConceptualEntity": "Sales", "ConceptualEntity": "Other",'
     ' "VariationSource": "OrderDate"}}}}}', "", "repeats a key"),
    (json.dumps(linguistic({"ConceptualEntity": 7, "VariationSource": "OrderDate"})), "", "names no table and column"),
    (json.dumps(linguistic({"VariationSource": "OrderDate", "VariationSet": "Odmiana"})), "", "names no table and column"),
])
def test_unreadable_or_unsupported_linguistic_metadata_fails_closed(tmp_path, raw, tail, reason):
    model, report = project(tmp_path)
    culture = write_culture(model, None, raw=raw, tail=tail)
    before = culture.read_bytes()
    tables = tables_by_name(model, report)
    for name in (ORDER, SHIP):
        assert not tables[name]["removable"] and "linguistic_metadata" in [b["code"] for b in tables[name]["blockers"]]
        assert reason in blocker_text(tables[name])
    summary = blocked(model, report, BLOCKED_COVERAGE)
    assert summary["reasons"] == ["2 tables: Q&A linguistic metadata could not be checked."]
    assert "coverage could not be confirmed" in plan_error(model, report)
    assert culture.read_bytes() == before


def test_post_removal_integrity_check_catches_lost_linguistic_bindings(tmp_path, monkeypatch):
    """Defence in depth: if assessment ever misses a binding, the write path still refuses."""
    model, report = project(tmp_path)
    write_culture(model, linguistic(date_binding()))
    real = auto_date_tables.assess

    def misses_bindings(*args, **kwargs):
        result = real(*args, **kwargs)
        for entry in result["tables"]:
            entry["removable"], entry["blockers"] = True, []
        return result

    monkeypatch.setattr(auto_date_tables, "assess", misses_bindings)
    result = auto_date_tables.remove_all(model, [report])
    assert not result["ok"]
    assert "linguistic metadata still binds the removed date hierarchy of Sales[OrderDate]" in result["error"]
    # The removed variation is gone afterwards, so only pre-removal ownership can find the binding.
    assert auto_date_tables.integrity_problems(model, [report], removed_owners={("sales", "orderdate")})


# --- F2 variation DAX after an earlier '[' and in compact JSON ---------------------------------


def extension(dax, indent=None):
    return json.dumps({"name": "extension", "entities": [{"name": "Sales", "measures": [
        {"name": "Y", "expression": dax}]}]}, indent=indent)


@pytest.mark.parametrize("measure, ext", [
    ('"[" & MAX(\'Sales\'[OrderDate].[Rok]) & "]"', None),
    ("1", extension("MAX('Sales'[OrderDate].[Rok])")),  # Compact JSON: '[' of the array comes first.
    ("1", extension('"[" & MAX(\'Sales\'[OrderDate].[Rok])', indent=2)),
    ("1", extension("MAX('Sales'[OrderDate]\n.[Rok])")),  # F3: JSON \n between the parts.
])
def test_variation_dax_after_an_unclosed_bracket_blocks_its_table(tmp_path, measure, ext):
    model, report = project(tmp_path, measure=measure)
    if ext is not None:
        (report / "definition/reportExtensions.json").write_text(ext, encoding="utf-8")
    tables = tables_by_name(model, report)
    assert not tables[ORDER]["removable"]
    assert [b["code"] for b in tables[ORDER]["blockers"]] == ["variation_dax"]
    expected = (f"SCORECARD.Report/definition/reportExtensions.json:"
                f"{next(i for i, t in enumerate(ext.splitlines(), 1) if 'expression' in t)}"
                if ext else "model/definition/tables/Sales.tmdl:4")
    assert tables[ORDER]["blockers"][0]["location"] == expected
    assert tables[SHIP]["removable"], "unused control stays removable in the internal check"
    assert "DAX may use its date hierarchy" in plan_error(model, report)


# --- F3 JSON escapes and malformed JSON ---------------------------------------------------------


def test_json_escaped_table_name_in_a_report_blocks_with_its_file_and_line(tmp_path):
    model, report = project(tmp_path)
    visual = report / "definition/pages/p1/visuals/v1"
    visual.mkdir(parents=True)
    document = json.dumps({"visual": {"query": {"Select": [{"Column": {"Expression": {"SourceRef": {
        "Entity": ORDER}}, "Property": "Rok"}}]}}}, indent=2).replace(ORDER, ORDER.replace("-", "\\u002d"))
    assert ORDER not in document
    (visual / "visual.json").write_text(document, encoding="utf-8")
    line = next(i for i, text in enumerate(document.splitlines(), 1) if "Entity" in text)
    tables = tables_by_name(model, report)
    assert [b["code"] for b in tables[ORDER]["blockers"]] == ["report_reference"]
    assert tables[ORDER]["blockers"][0]["location"] == f"SCORECARD.Report/definition/pages/p1/visuals/v1/visual.json:{line}"
    assert tables[SHIP]["removable"]
    blocked(model, report)


def test_malformed_report_json_blocks_every_table(tmp_path):
    model, report = project(tmp_path)
    (report / "definition/reportExtensions.json").write_text('{"entities": [', encoding="utf-8")
    tables = tables_by_name(model, report)
    assert not any(t["removable"] for t in tables.values())
    assert all("reportExtensions.json is not valid JSON" in blocker_text(t) for t in tables.values())
    summary = blocked(model, report, BLOCKED_COVERAGE)
    assert any("reportExtensions.json is not valid JSON" in reason for reason in summary["reasons"])


# --- F5 the template goes only together with every other auto-date table --------------------------


def test_template_stays_when_any_other_auto_date_table_is_used(tmp_path):
    model, report = project(tmp_path, measure="MAX(Sales[OrderDate].[Rok])")
    template = (model / f"definition/tables/{TEMPLATE}.tmdl").read_bytes()
    tables = tables_by_name(model, report)
    assert tables[TEMPLATE]["removable"] and "requires_tables" not in tables[TEMPLATE]
    blocked(model, report)
    assert not auto_date_tables.remove_all(model, [report])["ok"]
    assert (model / f"definition/tables/{TEMPLATE}.tmdl").read_bytes() == template


# --- Review round 2 (fdab600): N1 key letter case ------------------------------------------------


@pytest.mark.parametrize("payload, key", [
    # Reviewer probe A1.
    (linguistic({"ConceptualEntity": "Sales", "variationSource": "OrderDate", "variationSet": "Odmiana",
                 "Hierarchy": "Hierarchia dat"}), "variationSource"),
    (linguistic({"conceptualEntity": "Sales", "VariationSource": "OrderDate", "VariationSet": "Odmiana"}),
     "conceptualEntity"),
    (linguistic({"ConceptualEntity": "Sales", "conceptualproperty": "OrderDate", "VariationSource": "Odmiana"}),
     "conceptualproperty"),
    # Nested under a shape this check does not know, next to an ordinary binding.
    ({"Version": "4.1.0", "Entities": {"e0": {"Definition": {"Binding": {"ConceptualEntity": "Sales"}},
                                              "Extra": [{"Inner": {"VARIATIONSET": "Odmiana"}}]}}}, "VARIATIONSET"),
])
def test_linguistic_keys_in_another_letter_case_fail_closed(tmp_path, payload, key):
    model, report = project(tmp_path)
    culture = write_culture(model, payload)
    before = culture.read_bytes()
    line = next(i for i, text in enumerate(culture.read_text(encoding="utf-8").splitlines(), 1) if f'"{key}"' in text)
    tables = tables_by_name(model, report)
    for name in (ORDER, SHIP):
        assert not tables[name]["removable"]
        assert [b["code"] for b in tables[name]["blockers"]] == ["linguistic_metadata"]
        assert f"key {key} in an unsupported letter case (model/definition/cultures/pl-PL.tmdl:{line})" \
            in blocker_text(tables[name])
    blocked(model, report, BLOCKED_COVERAGE)
    assert "Q&A linguistic metadata could not be checked" in plan_error(model, report)
    assert culture.read_bytes() == before


def test_linguistic_key_letter_case_check_ignores_values_and_escaped_exact_keys(tmp_path):
    """Control: the exact key names stay supported, also JSON-escaped; key-like values are only text."""
    model, report = project(tmp_path)
    raw = json.dumps(linguistic({"ConceptualEntity": "Sales", "ConceptualProperty": "variationSource"},
                                {"ConceptualEntity": "Other", "VariationSource": "OrderDate"}),
                     indent=2).replace('"VariationSource"', '"Variation\\u0053ource"')
    write_culture(model, None, raw=raw)
    assert all(t["removable"] for t in tables_by_name(model, report).values())
    assert group(model, report)["can_remove_all"]


# --- N2 DAX comments between the parts of a variation reference ----------------------------------


@pytest.mark.parametrize("measure", [
    "MAX('Sales'[OrderDate] /* c */ .[Rok])",  # Reviewer probe B1.
    "MAX('Sales'[OrderDate] -- c\r\n\t\t.[Rok])",  # Reviewer probe B2.
    "MAX('Sales'[OrderDate] // c\r\n\t\t.[Rok])",
    "MAX('Sales'[OrderDate]./* c */[Rok])",
    "MAX('Sales'[OrderDate] /* a ] . [ */ /* b\r\n\t\t*/ -- c\r\n\t\t. // d\r\n\t\t[Rok])",
    "MAX('Sales'[OrderDate] /* never closed",  # Malformed: fail closed.
])
def test_comments_inside_a_variation_reference_block_its_table(tmp_path, measure):
    model, report = project(tmp_path, measure=measure)
    tables = tables_by_name(model, report)
    assert [b["code"] for b in tables[ORDER]["blockers"]] == ["variation_dax"]
    assert tables[ORDER]["blockers"][0]["location"] == "model/definition/tables/Sales.tmdl:4"
    assert tables[SHIP]["removable"], "unused control stays removable in the internal check"
    assert BLOCKED_USE in plan_error(model, report)


@pytest.mark.parametrize("dax", ["MAX('Sales'[OrderDate] /* c */\n.[Rok])", "MAX('Sales'[OrderDate] -- c\n.[Rok])"])
def test_comments_inside_a_json_escaped_variation_reference_block_its_table(tmp_path, dax):
    model, report = project(tmp_path)
    ext = extension(dax, indent=2)
    (report / "definition/reportExtensions.json").write_text(ext, encoding="utf-8")
    line = next(i for i, text in enumerate(ext.splitlines(), 1) if "expression" in text)
    tables = tables_by_name(model, report)
    assert [b["code"] for b in tables[ORDER]["blockers"]] == ["variation_dax"]
    assert tables[ORDER]["blockers"][0]["location"] == f"SCORECARD.Report/definition/reportExtensions.json:{line}"
    assert tables[SHIP]["removable"]
    blocked(model, report)


@pytest.mark.parametrize("measure", [
    "MAX('Sales'[OrderDate] /* c */ + 1)",
    "MAX('Sales'[OrderDate]) /* .[Rok] */",
    "MAX('Sales'[OrderDate]) -- .[Rok]",
    "MAX('Sales'[OrderDate] -- .[Rok]",  # The line comment runs to the end; no reference follows.
])
def test_comments_without_a_variation_reference_do_not_block(tmp_path, measure):
    model, report = project(tmp_path, measure=measure)
    assert all(t["removable"] for t in tables_by_name(model, report).values())
    assert group(model, report)["can_remove_all"]


# --- N3 saved DAX query files (.dax) --------------------------------------------------------------


def write_query(root, text, name="Query 1.dax"):
    path = root / "DAXQueries" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.parametrize("artifact, query, code, line", [
    ("model", f"DEFINE\r\n\tVAR x = 1\r\nEVALUATE\r\n\t'{ORDER}'\r\n", "model_reference", 4),
    ("model", "EVALUATE\r\n\tROW(\"y\", MAX('Sales'[OrderDate].[Rok]))\r\n", "variation_dax", 2),  # Reviewer probe E1.
    ("report", "EVALUATE\r\n\tROW(\"y\", MAX('Sales'[OrderDate] /* c */ .[Rok]))\r\n", "variation_dax", 2),
])
def test_saved_dax_query_use_blocks_the_group_and_the_query_is_never_edited(tmp_path, artifact, query, code, line):
    model, report = project(tmp_path)
    root, prefix = (model, "model") if artifact == "model" else (report, "SCORECARD.Report")
    path = write_query(root, query)
    before = path.read_bytes()
    tables = tables_by_name(model, report)
    entry = tables[ORDER]
    assert [b["code"] for b in entry["blockers"]] == [code]
    assert entry["blockers"][0]["location"] == f"{prefix}/DAXQueries/Query 1.dax:{line}"
    assert "Saved DAX query" in blocker_text(entry)
    assert tables[SHIP]["removable"]
    blocked(model, report)
    assert BLOCKED_USE in plan_error(model, report)
    assert path.read_bytes() == before


@pytest.mark.parametrize("artifact", ["model", "report"])
def test_unrelated_saved_dax_queries_are_plan_inputs_and_never_edited(tmp_path, artifact):
    model, report = project(tmp_path)
    path = write_query(model if artifact == "model" else report, "EVALUATE\r\n\tSales\r\n")
    before = path.read_bytes()
    original = snapshot(tmp_path)
    plan = all_plan(model, report)
    assert f"{'model' if artifact == 'model' else 'report-1'}/DAXQueries/Query 1.dax" in plan["inputs"]
    assert not any(c["path"].endswith(".dax") for c in plan["changes"])
    assert change_plan.apply_plan(plan, journal_of(tmp_path))["ok"]
    assert change_plan.verify_plan(plan)["state"] == "applied"
    assert path.read_bytes() == before
    assert change_plan.restore_plan(plan, journal_of(tmp_path))["ok"]
    assert snapshot(tmp_path) == original


def _add_query_use(model):
    write_query(model, "EVALUATE ROW(\"y\", MAX('Sales'[OrderDate].[Rok]))\r\n", "Query 2.dax")


def _edit_query(model):
    write_query(model, "EVALUATE ROW(\"y\", MAX('Sales'[OrderDate].[Rok]))\r\n")


def _remove_query(model):
    (model / "DAXQueries/Query 1.dax").unlink()


@pytest.mark.parametrize("edit", [_add_query_use, _edit_query, _remove_query])
def test_saved_dax_queries_changed_after_preview_make_the_plan_stale(tmp_path, edit):
    model, report = project(tmp_path)
    write_query(model, "EVALUATE Sales\r\n")
    plan = all_plan(model, report)
    assert plan["inputs"]["model/DAXQueries/Query 1.dax"] == plan["outputs"]["model/DAXQueries/Query 1.dax"]
    edit(model)
    apply_refused(tmp_path, plan, "Stale plan")
    assert change_plan.verify_plan(plan)["state"] == "changed"


def test_saved_dax_queries_stay_outside_other_plan_kinds(tmp_path):
    model, report = project(tmp_path)
    write_query(model, "EVALUATE Sales\r\n")
    plan = change_plan.create_plan(model, [report], [{"kind": "actions", "actions": [
        {"action": "hide", "table": "Sales", "name": "Amount", "item_type": "Column"}]}])
    assert not any(key.endswith(".dax") for key in [*plan["inputs"], *plan["outputs"]])
