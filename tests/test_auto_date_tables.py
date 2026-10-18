"""Explicit action: review and remove unused Power BI auto-date tables.

The fixture mirrors what Power BI Desktop writes (CRLF, Polish locale names): a
fact table with two date columns, each with a generated ``LocalDateTable_*``,
relationship and ``variation``, plus the ``DateTableTemplate_*`` table.
"""
import json
import re

import pytest

from semantic_model_cleaner import auto_date_tables, change_plan

ORDER = "LocalDateTable_8ed55867-002d-48ca-ab64-c88caeda64fe"
SHIP = "LocalDateTable_5322b399-016f-4d3c-b684-4db41be8f5aa"
TEMPLATE = "DateTableTemplate_cc871eef-dce2-4592-aa62-68d4b87609b9"
ORDER_REL = "c6d1fd99-3747-45f9-8701-c75df75e375e"
SHIP_REL = "920bdf0d-8b0c-45c7-ad07-057dcfb956d6"


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


def template_kept(tables):
    """The template stays, conservatively, while another auto-date table stays."""
    entry = tables[TEMPLATE]
    return not entry["removable"] and [b["code"] for b in entry["blockers"]] == ["template_kept"] \
        and "not been validated in Power BI Desktop" in blocker_text(entry)


def plan_error(model, report, tables):
    with pytest.raises(change_plan.PlanError) as error:
        change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": tables}])
    return str(error.value)


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


def test_unused_generated_tables_are_removed_through_plan_apply_verify_and_restore(tmp_path):
    model, report = project(tmp_path)
    assessment = auto_date_tables.assess(model, [report])
    assert (assessment["found"], assessment["removable_count"], assessment["blocked_count"]) == (3, 3, 0)
    assert assessment["time_intelligence_enabled"] is True
    by_name = {t["table"]: t for t in assessment["tables"]}
    assert by_name[ORDER]["date_column"] == "Sales[OrderDate]" and by_name[TEMPLATE]["kind"] == "template"
    before = snapshot(tmp_path)

    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER, SHIP, TEMPLATE]}])
    assert snapshot(tmp_path) == before, "preview must not write"
    changes = {c["path"]: c["change"] for c in plan["changes"]}
    assert changes == {f"model/definition/tables/{name}.tmdl": "deleted" for name in (ORDER, SHIP, TEMPLATE)} | {
        "model/definition/model.tmdl": "modified", "model/definition/relationships.tmdl": "deleted",
        "model/definition/tables/Sales.tmdl": "modified"}
    assert any("Auto date/time stays on" in text for text in plan["validation"]["confirmations"])
    assert any("2 date column(s) stay" in text for text in plan["validation"]["confirmations"])

    journal = tmp_path.parent / f"{tmp_path.name}-journal"
    assert change_plan.apply_plan(plan, journal)["ok"]
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
    assert auto_date_tables.assess(model, [report])["found"] == 0

    assert change_plan.restore_plan(plan, journal)["ok"]
    assert snapshot(tmp_path) == before


def test_report_hierarchy_use_blocks_only_that_table(tmp_path):
    model, report = project(tmp_path, visual=hierarchy_visual())
    tables = tables_by_name(model, report)
    assert not tables[ORDER]["removable"]
    assert "uses the date hierarchy of Sales[OrderDate]" in blocker_text(tables[ORDER])
    assert tables[SHIP]["removable"]
    assert template_kept(tables)
    with pytest.raises(change_plan.PlanError, match="cannot be removed"):
        change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER]}])


def test_report_query_ref_alone_blocks_its_table(tmp_path):
    visual = {"filterConfig": {"filters": [{"field": {"queryRef": "Sales.ShipDate.Odmiana.Hierarchia dat.Rok"}}]}}
    model, report = project(tmp_path, visual=visual)
    tables = tables_by_name(model, report)
    assert not tables[SHIP]["removable"] and tables[ORDER]["removable"]


def test_report_naming_the_auto_table_blocks_it(tmp_path):
    visual = {"visual": {"query": {"Select": [{"Column": {"Expression": {"SourceRef": {"Entity": ORDER}},
                                                         "Property": "Rok"}}]}}}
    model, report = project(tmp_path, visual=visual)
    entry = tables_by_name(model, report)[ORDER]
    assert not entry["removable"] and entry["blockers"][0]["code"] == "report_reference"


@pytest.mark.parametrize("measure, blocked, code, reason", [
    (f"CALCULATE([Total], '{ORDER}'[Rok] = 2024)", ORDER, "model_reference", "measure Total in table Sales"),
    ("MAX(Sales[ShipDate].[Rok])", SHIP, "variation_dax", "through [ShipDate].["),
])
def test_dax_dependency_blocks_its_table(tmp_path, measure, blocked, code, reason):
    model, report = project(tmp_path, measure=measure)
    tables = tables_by_name(model, report)
    entry = tables[blocked]
    assert not entry["removable"] and entry["blockers"][0]["code"] == code
    assert reason in blocker_text(entry)
    assert {name for name, t in tables.items() if t["removable"]} == {ORDER, SHIP} - {blocked}
    assert template_kept(tables)


def test_ordinary_lookalike_table_is_reported_and_preserved(tmp_path):
    model, report = project(tmp_path)
    lookalike = "LocalDateTable_00000000-0000-0000-0000-000000000000"
    path = model / f"definition/tables/{lookalike}.tmdl"
    path.write_bytes(crlf(f"table {lookalike}", "\tlineageTag: 12121212-0000-0000-0000-000000000000", "",
                          "\tcolumn Date", "\t\tdataType: dateTime", "\t\tsourceColumn: Date", "",
                          f"\tpartition {lookalike} = m", "\t\tmode: import", "\t\tsource = let x = 1 in x"))
    entry = tables_by_name(model, report)[lookalike]
    assert not entry["removable"] and entry["blockers"][0]["code"] == "not_generated"
    assert "no '__PBI_LocalDateTable = true' annotation" in blocker_text(entry)
    original = path.read_bytes()
    with pytest.raises(change_plan.PlanError, match="Not proven to be a generated auto-date table"):
        change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [lookalike]}])
    assert path.read_bytes() == original


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
def test_ambiguous_or_unsupported_metadata_blocks_removal(tmp_path, mutate):
    model, report = project(tmp_path)
    table, reason = mutate(model, report)
    entry = tables_by_name(model, report)[table]
    assert not entry["removable"]
    assert reason in blocker_text(entry)
    # Invalid report JSON is also refused earlier by the shared plan checks.
    with pytest.raises(change_plan.PlanError, match=re.escape(reason) + "|Incomplete or invalid metadata"):
        change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [table]}])


def test_partial_selection_keeps_the_other_generated_structure_byte_for_byte(tmp_path):
    model, report = project(tmp_path)
    ship_file = (model / f"definition/tables/{SHIP}.tmdl").read_bytes()
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER]}])
    assert change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")["ok"]
    assert (model / f"definition/tables/{SHIP}.tmdl").read_bytes() == ship_file
    assert (model / "definition/relationships.tmdl").read_bytes() == crlf(
        f"relationship {SHIP_REL}", "\tjoinOnDateBehavior: datePartOnly", "\tfromColumn: Sales.ShipDate",
        f"\ttoColumn: {SHIP}.Date", "")
    sales = (model / "definition/tables/Sales.tmdl").read_bytes()
    assert sales.count(b"\t\tvariation Odmiana\r\n") == 1 and f"defaultHierarchy: {SHIP}".encode() in sales
    assert f"ref table {SHIP}\r\n".encode() in (model / "definition/model.tmdl").read_bytes()
    assert auto_date_tables.integrity_problems(model, [report]) == set()
    remaining = tables_by_name(model, report)
    assert set(remaining) == {SHIP, TEMPLATE} and all(t["removable"] for t in remaining.values())


def test_stale_plan_is_rejected_and_nothing_is_written(tmp_path):
    model, report = project(tmp_path)
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER]}])
    (report / "definition/report.json").write_text('{"edited": true}', encoding="utf-8")
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match="Stale plan"):
        change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")
    assert snapshot(tmp_path) == before


def test_apply_checks_the_tables_again_on_the_server(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER]}])
    real = auto_date_tables.assess

    def now_blocked(*args, **kwargs):
        result = real(*args, **kwargs)
        for entry in result["tables"]:
            entry["removable"] = False
            entry["blockers"] = [{"code": "report_hierarchy", "message": "Now used by a report.", "location": ""}]
        return result

    monkeypatch.setattr(auto_date_tables, "assess", now_blocked)
    journal = tmp_path.parent / f"{tmp_path.name}-journal"
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match="checked again before apply.*Now used by a report"):
        change_plan.apply_plan(plan, journal)
    assert snapshot(tmp_path) == before
    assert not (journal / f"{plan['id']}.receipt.json").exists()


@pytest.mark.parametrize("operations, message", [
    ([{"kind": "auto_date_tables", "tables": ["Sales"]}], "not an auto-date table"),
    ([{"kind": "auto_date_tables", "tables": []}], "Select at least one"),
    ([{"kind": "auto_date_tables", "tables": [ORDER, ORDER.lower()]}], "selected once"),
    ([{"kind": "auto_date_tables", "tables": [ORDER]},
      {"kind": "actions", "actions": [{"action": "hide", "table": "Sales", "name": "Amount", "item_type": "Column"}]}],
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
    assert result["found"] == 3 and result["removable_count"] == 0
    assert "Select at least one report" in result["scope_blockers"][0]


def test_writer_level_removal_refuses_blocked_tables(tmp_path):
    model, report = project(tmp_path, measure=f"COUNTROWS('{SHIP}')")
    before = snapshot(tmp_path)
    result = auto_date_tables.remove_tables(model, [report], [SHIP])
    assert not result["ok"] and "measure Total in table Sales" in result["error"]
    assert snapshot(tmp_path) == before


def test_web_assessment_and_plan_lifecycle(tmp_path, monkeypatch):
    from semantic_model_cleaner import webapp
    model, report = project(tmp_path, visual=hierarchy_visual())
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path.parent / f"{tmp_path.name}-state"))
    client = webapp.app.test_client()
    scope = {"model_path": str(model), "report_paths": [str(report)]}
    summary = client.post("/api/auto-date-tables", json=scope).get_json()
    assert (summary["found"], summary["removable_count"], summary["blocked_count"]) == (3, 1, 2)
    blocked = client.post("/api/plans", json={**scope, "operations": [{"kind": "auto_date_tables", "tables": [ORDER]}]})
    assert blocked.status_code == 400 and "uses the date hierarchy" in blocked.get_json()["error"]
    preview = client.post("/api/plans", json={**scope, "operations": [{"kind": "auto_date_tables", "tables": [SHIP]}]})
    assert preview.status_code == 200, preview.get_json()
    plan = preview.get_json()["plan"]
    assert client.post(f"/api/plans/{plan['id']}/apply").get_json()["ok"]
    assert not (model / f"definition/tables/{SHIP}.tmdl").exists()
    assert client.post(f"/api/plans/{plan['id']}/restore").get_json()["ok"]
    assert (model / f"definition/tables/{SHIP}.tmdl").exists()


def test_summary_action_is_wired_into_the_workspace():
    from pathlib import Path
    source = Path(auto_date_tables.__file__).parent
    template = (source / "templates/index_v2.html").read_text(encoding="utf-8")
    script = (source / "static/auto-date-tables.js").read_text(encoding="utf-8")
    assert "auto-date-tables.js" in template
    assert "Review and remove unused auto-date tables" in script
    assert "'/api/auto-date-tables'" in script and "kind: 'auto_date_tables'" in script
    assert "smcReviewOperations" in script, "removal must use the shared reviewed-plan workflow"
    assert "requires_tables" in script and "Select every auto-date table to remove the template" in script


# --- Review round 1 (3219863): F1 linguistic bindings ------------------------------------------


@pytest.mark.parametrize("binding", [
    date_binding(),
    date_binding(level=None),
    date_binding(entity="SALES", column="orderdate"),  # Case-insensitive owner match.
    # Reviewer's variant: date column in ConceptualProperty, variation name in VariationSource.
    {"ConceptualEntity": "Sales", "ConceptualProperty": "OrderDate", "VariationSource": "Odmiana",
     "VariationSet": "Hierarchia dat", "Hierarchy": "Hierarchia dat", "HierarchyLevel": "Rok"},
])
def test_linguistic_date_hierarchy_binding_blocks_its_table_and_keeps_the_culture(tmp_path, binding):
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
    assert tables[SHIP]["removable"] and template_kept(tables)
    assert "binds the date hierarchy" in plan_error(model, report, [ORDER])
    assert "Kept while 1 other auto-date table(s) cannot be removed" in plan_error(model, report, [SHIP, TEMPLATE])
    # The reviewer's variant names a variation in VariationSource, which the generic check reports before and after.
    integrity = auto_date_tables.integrity_problems(model, [report])
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [SHIP]}])
    assert change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")["ok"]
    assert culture.read_bytes() == before, "linguistic metadata is never edited"
    assert auto_date_tables.integrity_problems(model, [report]) == integrity
    assert integrity == set() or "VariationSource" not in binding or binding["VariationSource"] == "Odmiana"


def test_json_escaped_linguistic_binding_blocks(tmp_path):
    model, report = project(tmp_path)
    raw = json.dumps(linguistic(date_binding()), indent=2).replace('"Sales"', '"Sale\\u0073"').replace(
        '"OrderDate"', '"Order\\u0044ate"')
    assert "Sale\\u0073" in raw and json.loads(raw)["Entities"]["e0"]["Definition"]["Binding"]["ConceptualEntity"] == "Sales"
    write_culture(model, None, raw=raw)
    assert [b["code"] for b in tables_by_name(model, report)[ORDER]["blockers"]] == ["linguistic_hierarchy"]


def test_linguistic_bindings_that_do_not_use_a_date_hierarchy_do_not_block(tmp_path):
    model, report = project(tmp_path)
    write_culture(model, linguistic({"ConceptualEntity": "Sales", "ConceptualProperty": "OrderDate"},
                                    {"ConceptualEntity": "Sales"}, date_binding(entity="Other")))
    tables = tables_by_name(model, report)
    assert all(t["removable"] for t in tables.values())


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
    assert template_kept(tables)
    assert reason in plan_error(model, report, [ORDER, SHIP, TEMPLATE])
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
    result = auto_date_tables.remove_tables(model, [report], [ORDER])
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
    assert tables[SHIP]["removable"], "unused control stays removable"
    assert "through [OrderDate]" in plan_error(model, report, [ORDER])


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


def test_malformed_report_json_blocks_every_table(tmp_path):
    model, report = project(tmp_path)
    (report / "definition/reportExtensions.json").write_text('{"entities": [', encoding="utf-8")
    tables = tables_by_name(model, report)
    assert not any(t["removable"] for t in tables.values())
    assert all("reportExtensions.json is not valid JSON" in blocker_text(t) for t in tables.values())


# --- F5 template only together with every other auto-date table ----------------------------------


@pytest.mark.parametrize("selection", [[TEMPLATE], [ORDER, TEMPLATE]])
def test_template_cannot_be_removed_while_auto_date_tables_stay(tmp_path, selection):
    model, report = project(tmp_path)
    tables = tables_by_name(model, report)
    assert tables[TEMPLATE]["removable"] and tables[TEMPLATE]["requires_tables"] == sorted([ORDER, SHIP])
    before = snapshot(tmp_path)
    assert "select every auto-date table to remove the template" in plan_error(model, report, selection)
    result = auto_date_tables.remove_tables(model, [report], selection)
    assert not result["ok"] and "not been validated in Power BI Desktop" in result["error"]
    assert snapshot(tmp_path) == before


def test_apply_refuses_the_template_when_another_auto_date_table_now_stays(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER, SHIP, TEMPLATE]}])
    real = auto_date_tables.assess

    def new_local_table(*args, **kwargs):
        result = real(*args, **kwargs)
        result["tables"].append({**result["tables"][0], "table": "LocalDateTable_99999999-9999-9999-9999-999999999999"})
        return result

    monkeypatch.setattr(auto_date_tables, "assess", new_local_table)
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match="checked again before apply.*select every auto-date table"):
        change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")
    assert snapshot(tmp_path) == before


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
    assert template_kept(tables)
    assert "unsupported letter case" in plan_error(model, report, [ORDER, SHIP, TEMPLATE])
    assert culture.read_bytes() == before


def test_linguistic_key_letter_case_check_ignores_values_and_escaped_exact_keys(tmp_path):
    """Control: the exact key names stay supported, also JSON-escaped; key-like values are only text."""
    model, report = project(tmp_path)
    raw = json.dumps(linguistic({"ConceptualEntity": "Sales", "ConceptualProperty": "variationSource"},
                                {"ConceptualEntity": "Other", "VariationSource": "OrderDate"}),
                     indent=2).replace('"VariationSource"', '"Variation\\u0053ource"')
    write_culture(model, None, raw=raw)
    assert all(t["removable"] for t in tables_by_name(model, report).values())


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
    assert tables[SHIP]["removable"], "unused control stays removable"
    assert "through [OrderDate]" in plan_error(model, report, [ORDER])


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


@pytest.mark.parametrize("measure", [
    "MAX('Sales'[OrderDate] /* c */ + 1)",
    "MAX('Sales'[OrderDate]) /* .[Rok] */",
    "MAX('Sales'[OrderDate]) -- .[Rok]",
    "MAX('Sales'[OrderDate] -- .[Rok]",  # The line comment runs to the end; no reference follows.
])
def test_comments_without_a_variation_reference_do_not_block(tmp_path, measure):
    model, report = project(tmp_path, measure=measure)
    assert all(t["removable"] for t in tables_by_name(model, report).values())


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
def test_saved_dax_query_use_blocks_its_table_and_the_query_is_never_edited(tmp_path, artifact, query, code, line):
    model, report = project(tmp_path)
    root, prefix = (model, "model") if artifact == "model" else (report, "SCORECARD.Report")
    path = write_query(root, query)
    before = path.read_bytes()
    tables = tables_by_name(model, report)
    entry = tables[ORDER]
    assert [b["code"] for b in entry["blockers"]] == [code]
    assert entry["blockers"][0]["location"] == f"{prefix}/DAXQueries/Query 1.dax:{line}"
    assert "Saved DAX query" in blocker_text(entry)
    assert tables[SHIP]["removable"] and template_kept(tables)
    assert "Saved DAX query" in plan_error(model, report, [ORDER])
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [SHIP]}])
    assert f"{'model' if artifact == 'model' else 'report-1'}/DAXQueries/Query 1.dax" in plan["inputs"]
    assert not any(c["path"].endswith(".dax") for c in plan["changes"])
    assert change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")["ok"]
    assert change_plan.verify_plan(plan)["state"] == "applied"
    assert path.read_bytes() == before


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
    plan = change_plan.create_plan(model, [report], [{"kind": "auto_date_tables", "tables": [ORDER]}])
    assert plan["inputs"]["model/DAXQueries/Query 1.dax"] == plan["outputs"]["model/DAXQueries/Query 1.dax"]
    edit(model)
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match="Stale plan"):
        change_plan.apply_plan(plan, tmp_path.parent / f"{tmp_path.name}-journal")
    assert snapshot(tmp_path) == before
    assert change_plan.verify_plan(plan)["state"] == "changed"


def test_saved_dax_queries_stay_outside_other_plan_kinds(tmp_path):
    model, report = project(tmp_path)
    write_query(model, "EVALUATE Sales\r\n")
    plan = change_plan.create_plan(model, [report], [{"kind": "actions", "actions": [
        {"action": "hide", "table": "Sales", "name": "Amount", "item_type": "Column"}]}])
    assert not any(key.endswith(".dax") for key in [*plan["inputs"], *plan["outputs"]])
