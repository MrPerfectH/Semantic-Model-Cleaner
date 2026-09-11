"""Writer regressions at the PBIR/TMDL and reviewed-plan boundaries."""
import json

import pytest

from semantic_model_cleaner import change_plan, report_writer, tmdl_writer


def ref(kind="Measure", name="Amount", *, entity=None, alias="s"):
    source = {"Entity": entity} if entity else {"Source": alias}
    return {kind: {"Expression": {"SourceRef": source}, "Property": name}}


def query(table, *references):
    return {"From": [{"Name": "s", "Entity": table, "Type": 0}],
            "Select": list(references or [ref()])}


def write_report(tmp_path, payload):
    report = tmp_path / "R.Report"
    file = report / "definition/pages/P/visuals/V/visual.json"
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps(payload, indent=2) + "\n")
    (report / "definition/report.json").write_text("{}")
    return report, file


def rename(report, **kwargs):
    return report_writer.rewrite_model_reference_changes(
        report_paths=[report],
        measure_renames=[{"table": "Sales", "name": "Amount", "target_name": "Revenue"}],
        **kwargs,
    )


MALFORMED_REFERENCE_EXPRESSIONS = [
    pytest.param({}, id="missing-expression"),
    pytest.param({"Expression": None}, id="null-expression"),
    pytest.param({"Expression": "Sales"}, id="string-expression"),
    pytest.param({"Expression": []}, id="list-expression"),
    pytest.param({"Expression": 7}, id="scalar-expression"),
    pytest.param({"Expression": {}}, id="missing-source-ref"),
    pytest.param({"Expression": {"SourceRef": None}}, id="null-source-ref"),
    pytest.param({"Expression": {"SourceRef": "s"}}, id="string-source-ref"),
    pytest.param({"Expression": {"SourceRef": []}}, id="list-source-ref"),
    pytest.param({"Expression": {"SourceRef": 7}}, id="scalar-source-ref"),
    pytest.param({"Expression": {"SourceRef": False}}, id="boolean-source-ref"),
    pytest.param({"Expression": {"SourceRef": {"Entity": ""}}}, id="empty-entity"),
    pytest.param({"Expression": {"SourceRef": {"Entity": "  "}}}, id="blank-entity"),
]


@pytest.mark.parametrize("malformed", MALFORMED_REFERENCE_EXPRESSIONS)
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("kind", ["Measure", "Column"])
def test_malformed_required_source_blocks_report_rewrite(tmp_path, malformed, dry_run, kind):
    report, file = write_report(tmp_path, {"visual": {"query": {"queryState": {"Values": {"projections": [
        {"field": {kind: {"Property": "Amount", **malformed}}, "queryRef": "Sales.Amount"},
    ]}}}}})
    earlier = report / "definition/first.json"
    earlier.write_text(json.dumps(ref(kind, entity="Sales")))
    before = {path: path.read_bytes() for path in (earlier, file)}
    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report], dry_run=dry_run,
        **{f"{kind.lower()}_renames": [{"table": "Sales", "name": "Amount", "target_name": "Revenue"}]})
    assert not result["ok"], result
    assert result["written"] is False
    assert "required reference propagation" in result["error"]
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("malformed", MALFORMED_REFERENCE_EXPRESSIONS)
def test_malformed_measure_source_blocks_reviewed_plan(tmp_path, malformed):
    model = tmp_path / "M.SemanticModel"
    source = model / "definition/tables/Sales.tmdl"
    source.parent.mkdir(parents=True)
    source.write_text("table Sales\n\tmeasure Amount = 1\n")
    report, _ = write_report(tmp_path, {"visual": {"query": {"queryState": {"Values": {"projections": [
        {"field": {"Measure": {"Property": "Amount", **malformed}}, "queryRef": "Sales.Amount"},
    ]}}}}})
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    with pytest.raises(change_plan.PlanError, match="required reference propagation"):
        change_plan.create_plan(model, [report], [{"kind": "rename", "measure_renames": [
            {"table": "Sales", "name": "Amount", "target_name": "Revenue"}]}])
    assert change_plan._inventory(roots) == before


def test_measure_rename_preserves_valid_non_target_references(tmp_path):
    untouched = [ref(entity="Budget"), ref(name="Keep", entity="Sales"), ref("Column", entity="Sales")]
    report, file = write_report(tmp_path, {"visual": {"query": {"references": [
        ref(entity="Sales"), *untouched]}}})
    result = rename(report)
    assert result["ok"], result
    actual = json.loads(file.read_text())["visual"]["query"]["references"]
    assert actual[0]["Measure"]["Property"] == "Revenue"
    assert actual[1:] == untouched


@pytest.mark.parametrize("hierarchy", [None, "Sales", [], 7, {"Expression": None},
                                         {"Expression": {"SourceRef": None}}])
def test_malformed_hierarchy_source_blocks_required_table_rename(tmp_path, hierarchy):
    report, file = write_report(tmp_path, {"visual": {"query": {"HierarchyLevel": {
        "Expression": {"Hierarchy": hierarchy}, "Level": "Year"}}}})
    before = file.read_bytes()
    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report], table_renames=[{"table": "Sales", "target_table": "Fact Sales"}])
    assert not result["ok"], result
    assert "required reference propagation" in result["error"]
    assert file.read_bytes() == before


@pytest.mark.parametrize("entity", ["", "  "])
def test_empty_query_source_entity_blocks_required_measure_rename(tmp_path, entity):
    report, file = write_report(tmp_path, {"Query": query(entity)})
    before = file.read_bytes()
    result = rename(report)
    assert not result["ok"], result
    assert "required reference propagation" in result["error"]
    assert file.read_bytes() == before


@pytest.mark.parametrize("reverse", [False, True])
def test_measure_rename_reused_alias_never_repoints_entities(tmp_path, reverse):
    queries = [query("Sales"), query("Budget")]
    if reverse:
        queries.reverse()
    report, file = write_report(tmp_path, {"queries": queries})
    before = file.read_bytes()
    preview = rename(report, dry_run=True)
    assert preview["ok"], preview
    assert file.read_bytes() == before
    result = rename(report)
    assert result["ok"], result
    assert result["updated_files"] == preview["updated_files"]
    after = json.loads(file.read_text())["queries"]
    assert [q["From"] for q in after] == [q["From"] for q in queries]
    assert [q["Select"][0]["Measure"]["Property"] for q in after] == (
        ["Amount", "Revenue"] if reverse else ["Revenue", "Amount"])
    assert all("Entity" not in update["kind"]
               for item in result["updated_files"] for update in item["updates"])


def test_nested_filter_reuses_alias_without_changing_visual_binding(tmp_path):
    visual_query = {"SemanticQueryDataShapeCommand": {"Query": query("Sales")},
                    "queryState": {"Values": {"projections": [
                        {"field": ref(), "queryRef": "s.Amount"}]}}}
    payload = {"visual": {"query": visual_query,
                          "objects": {"selector": {"metadata": "s.Amount"}},
                          "filterConfig": {"filters": [{"filter": query("Budget", ref()),
                                                         "field": ref(entity="Budget")}]}}}
    report, file = write_report(tmp_path, payload)
    result = rename(report)
    assert result["ok"], result
    visual = json.loads(file.read_text())["visual"]
    assert visual["query"]["SemanticQueryDataShapeCommand"]["Query"]["From"][0]["Entity"] == "Sales"
    projection = visual["query"]["queryState"]["Values"]["projections"][0]
    assert projection["field"]["Measure"]["Property"] == "Revenue"
    assert projection["queryRef"] == "s.Revenue"
    assert visual["objects"]["selector"]["metadata"] == "s.Revenue"
    assert visual["filterConfig"] == payload["visual"]["filterConfig"]


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("from_entries", [[], [{"Name": "s", "Entity": "Sales"},
                                               {"Name": "s", "Entity": "Budget"}]])
def test_unresolved_or_ambiguous_required_alias_aborts_all_files(tmp_path, dry_run, from_entries):
    report, file = write_report(tmp_path, {"Query": {"From": from_entries, "Select": [ref()]}})
    earlier = report / "definition/first.json"
    earlier.write_text(json.dumps(ref(entity="Sales")))
    before = {path: path.read_bytes() for path in [earlier, file]}
    result = rename(report, dry_run=dry_run)
    assert not result["ok"], result
    assert result["written"] is False
    assert "alias" in result["error"].lower()
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("references", [
    [ref(), ref(name="Keep")],
    [ref(), ref("Column", "Category")],
    [ref(name="Keep"), ref()],
])
def test_measure_move_shared_alias_with_other_items_blocks(tmp_path, references):
    report, file = write_report(tmp_path, {"Query": query("Sales", *references)})
    before = file.read_bytes()
    result = report_writer.rewrite_measure_table_references(
        report_paths=[report], moves=[{"table": "Sales", "name": "Amount", "target_table": "Measures"}])
    assert not result["ok"], result
    assert result["written"] is False
    assert file.read_bytes() == before


def test_actual_move_changes_only_its_query_and_direct_entity(tmp_path):
    report, file = write_report(tmp_path, {"queries": [query("Sales"), query("Budget")],
                                          "direct": ref(entity="Sales")})
    result = report_writer.rewrite_measure_table_references(
        report_paths=[report], moves=[{"table": "Sales", "name": "Amount", "target_table": "Measures"}])
    assert result["ok"], result
    after = json.loads(file.read_text())
    assert [q["From"][0]["Entity"] for q in after["queries"]] == ["Measures", "Budget"]
    assert after["direct"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Measures"


@pytest.mark.parametrize("name", ["Empty", "Sales' Amount", "A = B"])
@pytest.mark.parametrize("operation", ["rename", "hide", "delete"])
def test_expressionless_measure_edits_preserve_neighbor_blocks(tmp_path, name, operation):
    model = tmp_path / "M.SemanticModel"
    file = model / "definition/tables/Sales.tmdl"
    file.parent.mkdir(parents=True)
    quoted = tmdl_writer._quote_tmdl_name(name)
    preceding = '\tmeasure Inline = "unchanged literal"\n\t\tformatString: 0\n\n'
    target = f"\tmeasure {quoted}\n\t\tformatString: #,0\n\n\t\tdisplayFolder: Empty\n\n"
    following = '\tmeasure Multiline =\n\t\t\t1 +\n\n\t\t\t2\n\t\tformatString: 0.0\n\n'
    file.write_text("table Sales\n" + preceding + target + following)
    if operation == "rename":
        before = file.read_bytes()
        preview = tmdl_writer.rename_measure(model, "Sales", name, "Renamed' Amount", dry_run=True)
        assert preview["ok"], preview
        assert file.read_bytes() == before
        result = tmdl_writer.rename_measure(model, "Sales", name, "Renamed' Amount")
    elif operation == "hide":
        result = tmdl_writer.set_hidden(model, "Sales", name, "Measure")
    else:
        result = tmdl_writer.delete_item(model, "Sales", name, "Measure")
    assert result["ok"], result
    after = file.read_text()
    assert preceding in after
    assert following in after
    if operation == "rename":
        assert "\tmeasure 'Renamed'' Amount'\n" in after
        assert target.replace(f"measure {quoted}", "measure 'Renamed'' Amount'") in after
    elif operation == "hide":
        assert "\t\tisHidden\n" in after
        assert f"\tmeasure {quoted}\n" in after
    else:
        assert f"\tmeasure {quoted}\n" not in after
        assert "displayFolder: Empty" not in after


@pytest.mark.parametrize("operation", ["rename", "move"])
def test_query_scoped_writer_plan_preview_apply_restore(tmp_path, operation):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    for table in ("Sales", "Budget", "Measures"):
        (tables / f"{table}.tmdl").write_text(f"table {table}\n\tmeasure Amount = 1\n" if table != "Measures"
                                             else "table Measures\n\tmeasure Existing = 0\n")
    report, file = write_report(tmp_path, {"visual": {"queries": [query("Sales"), query("Budget")]}})
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    op = ({"kind": "rename", "measure_renames": [{"table": "Sales", "name": "Amount", "target_name": "Revenue"}]}
          if operation == "rename" else
          {"kind": "move", "moves": [{"table": "Sales", "name": "Amount", "target_table": "Measures"}]})
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    plan = change_plan.create_plan(model, [report], [op])
    assert change_plan._inventory(roots) == before
    assert change_plan.apply_plan(plan, tmp_path / "journal")["ok"]
    assert change_plan._hashes(change_plan._inventory(roots)) == plan["outputs"]
    after_queries = json.loads(file.read_text())["visual"]["queries"]
    assert after_queries[0]["From"][0]["Entity"] == ("Sales" if operation == "rename" else "Measures")
    assert after_queries[0]["Select"][0]["Measure"]["Property"] == ("Revenue" if operation == "rename" else "Amount")
    assert after_queries[1] == query("Budget")
    assert change_plan.restore_plan(plan, tmp_path / "journal")["ok"]
    assert change_plan._inventory(roots) == before


@pytest.mark.parametrize("unresolved", [True, False])
def test_reviewed_plan_blocks_incomplete_alias_propagation(tmp_path, unresolved):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text("table Sales\n\tmeasure Amount = 1\n\tmeasure Keep = 2\n")
    (tables / "Measures.tmdl").write_text("table Measures\n\tmeasure Existing = 0\n")
    payload = query("Sales", ref(), ref(name="Keep"))
    if unresolved:
        payload["From"] = []
    report, _ = write_report(tmp_path, {"visual": {"query": payload}})
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    with pytest.raises(change_plan.PlanError, match="alias"):
        change_plan.create_plan(model, [report], [{"kind": "move", "moves": [
            {"table": "Sales", "name": "Amount", "target_table": "Measures"}]}])
    assert change_plan._inventory(roots) == before


def test_measure_rename_preserves_original_table_spelling(tmp_path):
    report, file = write_report(tmp_path, {"Query": query("sales"), "direct": ref(entity="SALES")})
    result = rename(report)
    assert result["ok"], result
    payload = json.loads(file.read_text())
    assert payload["Query"]["From"][0]["Entity"] == "sales"
    assert payload["direct"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "SALES"


def test_move_shared_alias_used_by_bare_source_ref_blocks(tmp_path):
    payload = query("Sales")
    payload["Where"] = [{"Expression": {"SourceRef": {"Source": "s"}}}]
    report, file = write_report(tmp_path, {"Query": payload})
    before = file.read_bytes()
    result = report_writer.rewrite_measure_table_references(
        report_paths=[report], moves=[{"table": "Sales", "name": "Amount", "target_table": "Measures"}])
    assert not result["ok"], result
    assert file.read_bytes() == before


def test_query_ref_outside_independent_query_scopes_blocks_instead_of_guessing(tmp_path):
    report, file = write_report(tmp_path, {"queries": [query("Sales"), query("Budget")],
                                          "selector": {"metadata": "s.Amount"}})
    before = file.read_bytes()
    result = rename(report)
    assert not result["ok"], result
    assert "alias" in result["error"]
    assert file.read_bytes() == before


def test_move_conflicting_selector_alias_blocks(tmp_path):
    report, file = write_report(tmp_path, {"visual": {
        "query": query("Sales"), "objects": {"selector": {"metadata": "s.Keep"}}}})
    before = file.read_bytes()
    result = report_writer.rewrite_measure_table_references(
        report_paths=[report], moves=[{"table": "Sales", "name": "Amount", "target_table": "Measures"}])
    assert not result["ok"], result
    assert file.read_bytes() == before


def test_move_propagates_query_ref_only_alias(tmp_path):
    payload = {"From": [{"Name": "s", "Entity": "Sales"}], "queryRefs": ["s.Amount"]}
    report, file = write_report(tmp_path, {"Query": payload})
    result = report_writer.rewrite_measure_table_references(
        report_paths=[report], moves=[{"table": "Sales", "name": "Amount", "target_table": "Measures"}])
    assert result["ok"], result
    assert json.loads(file.read_text())["Query"]["From"][0]["Entity"] == "Measures"


@pytest.mark.parametrize("query_state_first", [False, True])
def test_combined_table_and_measure_rename_uses_original_alias_binding(tmp_path, query_state_first):
    command = {"Query": query("Sales", ref(), ref("Column", "Category"))}
    state = {"Values": {"projections": [{"field": ref(), "queryRef": "s.Amount"}]}}
    pairs = [("SemanticQueryDataShapeCommand", command), ("queryState", state)]
    report, file = write_report(tmp_path, {"visual": {"query": dict(reversed(pairs) if query_state_first else pairs)}})
    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report], table_renames=[{"table": "Sales", "target_table": "Fact Sales"}],
        measure_renames=[{"table": "Sales", "name": "Amount", "target_name": "Revenue"}])
    assert result["ok"], result
    actual = json.loads(file.read_text())["visual"]["query"]
    actual_query = actual["SemanticQueryDataShapeCommand"]["Query"]
    assert actual_query["From"][0]["Entity"] == "Fact Sales"
    assert actual_query["Select"][0]["Measure"]["Property"] == "Revenue"
    assert actual["queryState"]["Values"]["projections"][0]["queryRef"] == "s.Revenue"


def test_unknown_source_ref_shape_blocks_without_rewriting_custom_metadata(tmp_path):
    payload = {"visual": {"customMetadata": {"SourceRef": {"Entity": "Sales"}}}}
    report, file = write_report(tmp_path, payload)
    before = file.read_bytes()
    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report], table_renames=[{"table": "Sales", "target_table": "Fact Sales"}])
    assert not result["ok"], result
    assert "unsupported SourceRef" in result["error"]
    assert file.read_bytes() == before


@pytest.mark.parametrize("operation", ["rename", "hide", "delete"])
def test_expressionless_measure_reviewed_plan_round_trip(tmp_path, operation):
    model = tmp_path / "M.SemanticModel"
    file = model / "definition/tables/Sales.tmdl"
    file.parent.mkdir(parents=True)
    file.write_text("table Sales\n\tmeasure 'Empty'' Measure'\n\t\tformatString: 0\n\n\tmeasure Existing = 1\n")
    report, _ = write_report(tmp_path, {})
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    op = ({"kind": "rename", "measure_renames": [
        {"table": "Sales", "name": "Empty' Measure", "target_name": "Renamed"}]}
        if operation == "rename" else {"kind": "actions", "actions": [
            {"action": operation, "table": "Sales", "name": "Empty' Measure", "item_type": "Measure"}]})
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    plan = change_plan.create_plan(model, [report], [op])
    assert change_plan._inventory(roots) == before
    assert change_plan.apply_plan(plan, tmp_path / "journal")["ok"]
    assert change_plan._hashes(change_plan._inventory(roots)) == plan["outputs"]
    content = file.read_text()
    assert "\tmeasure Existing = 1\n" in content
    if operation == "rename":
        assert "\tmeasure Renamed\n" in content
    elif operation == "hide":
        assert "\t\tisHidden\n" in content
    else:
        assert "Empty'' Measure" not in content
    assert change_plan.restore_plan(plan, tmp_path / "journal")["ok"]
    assert change_plan._inventory(roots) == before
