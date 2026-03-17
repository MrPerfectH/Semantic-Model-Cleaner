import json
from pathlib import Path

from semantic_model_cleaner import analyzer


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PUBLIC_DEMO_DIR = Path(__file__).resolve().parents[1] / "examples" / "public-demo-workspace"


def _analyze_fixture(name: str) -> dict:
    return analyzer.analyze((FIXTURES_DIR / name).resolve())


def _find_item(results: dict, table: str, name: str, item_type: str | None = None) -> dict:
    matches = [
        row for row in results["items"]
        if row["item"].table == table and row["item"].name == name
        and (item_type is None or row["item"].item_type == item_type)
    ]
    assert matches, f"Item not found: {table}[{name}]"
    if item_type is None:
        assert len(matches) == 1, f"Expected one match for {table}[{name}], found {len(matches)}"
    return matches[0]


def test_field_parameter_targets_are_marked_used():
    results = _analyze_fixture("field_parameter_used")

    revenue = _find_item(results, "Sales", "Revenue", "Measure")
    margin = _find_item(results, "Sales", "Margin %", "Measure")

    assert revenue["status"] == "USED (Field Parameter: Metric Parameter)"
    assert margin["status"] == "USED (Field Parameter: Metric Parameter)"
    assert [u.context for u in revenue["usages"]] == ["Field Parameter"]
    assert [u.context for u in margin["usages"]] == ["Field Parameter"]


def test_public_demo_workspace_analyzes_cleanly():
    results = analyzer.analyze(PUBLIC_DEMO_DIR.resolve())

    revenue = _find_item(results, "Sales", "Revenue", "Measure")
    margin = _find_item(results, "Sales", "Margin %", "Measure")

    assert results["summary"]["models"] == ["TestModel.SemanticModel"]
    assert results["summary"]["reports"] == ["TestReport"]
    assert revenue["status"] == "USED (Field Parameter: Metric Parameter)"
    assert margin["status"] == "USED (Field Parameter: Metric Parameter)"
    assert results["warnings"] == []


def test_unused_field_parameter_table_does_not_promote_targets():
    results = _analyze_fixture("field_parameter_unused")

    revenue = _find_item(results, "Sales", "Revenue", "Measure")
    margin = _find_item(results, "Sales", "Margin %", "Measure")

    assert revenue["status"] == "USED"
    assert margin["status"] == "NOT USED"


def test_ambiguous_nameof_target_emits_warning():
    results = _analyze_fixture("nameof_ambiguous_target")

    warnings = results["warnings"]
    assert any(w["code"] == "AMBIGUOUS_NAMEOF_TARGET" for w in warnings)

    measure = _find_item(results, "Sales", "Revenue", "Measure")
    column = _find_item(results, "Sales", "Revenue", "Column")
    assert measure["status"] == "NOT USED"
    assert column["status"] == "NOT USED"


def test_json_output_includes_warnings():
    results = _analyze_fixture("nameof_ambiguous_target")

    payload = json.loads(analyzer.format_json_output(results))

    assert "warnings" in payload
    assert isinstance(payload["warnings"], list)
    assert payload["warnings"][0]["code"] == "AMBIGUOUS_NAMEOF_TARGET"


def test_unused_hidden_column_includes_review_triggers(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    pages_dir = report / "definition" / "pages" / "Page 1"
    tables_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    (tables_dir / "Date.tmdl").write_text(
        "table Date\n"
        "\tcolumn DateKey\n"
        "\t\tisHidden\n",
        encoding="utf-8",
    )
    (pages_dir / "page.json").write_text('{"displayName":"Overview"}', encoding="utf-8")

    results = analyzer.analyze(workspace.resolve())
    date_key = _find_item(results, "Date", "DateKey", "Column")

    assert date_key["status"] == "NOT USED"
    assert date_key["removal_risk"] == "Review"
    assert date_key["review_triggers"] == ["Item is hidden"]

    payload = json.loads(analyzer.format_json_output(results))
    payload_item = next(item for item in payload["items"] if item["table"] == "Date" and item["name"] == "DateKey")
    assert payload_item["reviewTriggers"] == ["Item is hidden"]


def test_dax_dependency_graph_excludes_self_references():
    item = analyzer.ModelItem(
        item_type="Measure",
        table="Sales",
        name="Revenue",
        dax_body="[Revenue] + 1",
    )

    deps = analyzer.build_dax_dependency_graph([item])

    assert deps[item.key] == set()


def test_unresolved_field_parameter_targets_emit_warnings(tmp_path):
    warnings = []
    info = analyzer.FieldParameterInfo(
        table="FP PNL",
        source_file=tmp_path / "FP PNL.tmdl",
        targets=[("_Measures", "Summary Actuals")],
    )
    items = [
        analyzer.ModelItem(item_type="Measure", table="Sales", name="Revenue"),
    ]

    resolved = analyzer.resolve_field_parameter_targets([info], items, "Model.SemanticModel", warnings)

    assert resolved == [(info, [])]
    assert len(warnings) == 1
    assert warnings[0].code == "UNRESOLVED_NAMEOF_TARGET"
    assert "NAMEOF target _Measures[Summary Actuals] from field parameter table FP PNL does not resolve" in warnings[0].message


def test_commented_dax_refs_are_excluded_from_dependencies_but_exposed():
    target = analyzer.ModelItem(item_type="Measure", table="_Measures", name="Total Other SG&A")
    source = analyzer.ModelItem(
        item_type="Measure",
        table="_Measures",
        name="EBIT - Actuals",
        dax_body="// [Total Other SG&A]\nCALCULATE([Transaction Amount - USD])",
    )
    base = analyzer.ModelItem(item_type="Measure", table="_Measures", name="Transaction Amount - USD")

    deps = analyzer.build_dax_dependency_graph([target, source, base])
    commented = analyzer.extract_dax_commented_refs(source.dax_body)

    assert target.key not in deps[source.key]
    assert base.key in deps[source.key]
    assert "[Total Other SG&A]" in commented


def test_table_summaries_capture_role_patterns_and_single_column_measures(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    pages_dir = report / "definition" / "pages" / "Page 1"
    tables_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn OrderDateKey\n"
        "\tcolumn Amount\n"
        "\tmeasure Order Date Count = DISTINCTCOUNT(Sales[OrderDateKey])\n",
        encoding="utf-8",
    )
    (tables_dir / "Date.tmdl").write_text(
        "table Date\n"
        "\tcolumn DateKey\n"
        "\t\tisKey\n"
        "\tcolumn CalendarDate\n",
        encoding="utf-8",
    )
    (model / "definition" / "relationships.tmdl").write_text(
        "relationship SalesToDate\n"
        "\tfromColumn: Sales.OrderDateKey\n"
        "\ttoColumn: Date.DateKey\n"
        "\tfromCardinality: many\n"
        "\ttoCardinality: one\n"
        "\tisActive: true\n",
        encoding="utf-8",
    )
    (pages_dir / "page.json").write_text('{"displayName":"Overview"}', encoding="utf-8")

    results = analyzer.analyze(workspace.resolve())
    table_summaries = {row["name"]: row for row in results["table_summaries"]}

    assert table_summaries["Date"]["role_label"] == "dimension-like"
    assert table_summaries["Sales"]["role_label"] == "fact-like"
    assert table_summaries["Date"]["relationship_only_columns"] == ["Date[DateKey]"]
    assert table_summaries["Sales"]["single_column_measures"] == [
        {"measure": "Sales[Order Date Count]", "column": "Sales[OrderDateKey]"}
    ]


def test_broken_measure_refs_are_flagged(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    pages_dir = report / "definition" / "pages" / "Page 1"
    tables_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tmeasure Revenue = [Missing Measure] + SUM('Missing Table'[Amount])\n",
        encoding="utf-8",
    )
    (pages_dir / "page.json").write_text('{"displayName":"Overview"}', encoding="utf-8")

    results = analyzer.analyze(workspace.resolve())
    revenue = _find_item(results, "Sales", "Revenue", "Measure")

    assert revenue["status"] == "BROKEN (2 missing refs)"
    assert revenue["broken_dax_refs"] == ["[Missing Measure]", "Missing Table[Amount]"]
    assert revenue["broken_dax_ref_details"] == [
        {"kind": "measure", "ref": "[Missing Measure]", "message": "Missing measure: [Missing Measure]"},
        {"kind": "column", "ref": "Missing Table[Amount]", "message": "Missing column (table not found): Missing Table[Amount]"},
    ]
    assert results["summary"]["broken"] == 1

    payload = json.loads(analyzer.format_json_output(results))
    payload_item = next(item for item in payload["items"] if item["table"] == "Sales" and item["name"] == "Revenue")
    assert payload_item["brokenDaxRefs"] == ["[Missing Measure]", "Missing Table[Amount]"]
    assert payload_item["brokenDaxRefDetails"] == [
        {"kind": "measure", "ref": "[Missing Measure]", "message": "Missing measure: [Missing Measure]"},
        {"kind": "column", "ref": "Missing Table[Amount]", "message": "Missing column (table not found): Missing Table[Amount]"},
    ]


def test_bare_table_refs_are_flagged_as_broken(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    report.mkdir(parents=True)

    (tables_dir / "Measures.tmdl").write_text(
        "table Measures\n"
        "\tmeasure Row Count = COUNTROWS('Account')\n",
        encoding="utf-8",
    )

    (report / "definition.pbir").write_text('{"version":"4.0"}', encoding="utf-8")
    (report / "report.json").write_text('{"sections":[]}', encoding="utf-8")

    results = analyzer.analyze(workspace)
    row_count = _find_item(results, "Measures", "Row Count", "Measure")

    assert row_count["status"] == "BROKEN (1 missing ref)"
    assert row_count["broken_dax_refs"] == ["Account"]
    assert row_count["broken_dax_ref_details"] == [
        {"kind": "table", "ref": "Account", "message": "Missing table: Account"},
    ]
    assert results["summary"]["broken"] == 1


def test_valid_quoted_column_refs_do_not_trigger_false_broken_table_refs(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Forecast.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    report.mkdir(parents=True)

    (tables_dir / "Date.tmdl").write_text(
        "table Date\n"
        "\tcolumn Month\n"
        "\t\tsummarizeBy: none\n",
        encoding="utf-8",
    )
    (tables_dir / "Measures.tmdl").write_text(
        "table Measures\n"
        "\tmeasure Forecast Amount - USD - March =\n"
        "\t\tCALCULATE(\n"
        "\t\t\t[Forecast Amount - USD - March (view)],\n"
        "\t\t\tKEEPFILTERS('Date'[Month] IN { 4, 5, 6, 7, 8, 9, 10, 11, 12 })\n"
        "\t\t)\n"
        "\t\t+\n"
        "\t\tCALCULATE(\n"
        "\t\t\t[Transaction Amount - USD],\n"
        "\t\t\tKEEPFILTERS('Date'[Month] IN { 1, 2, 3 })\n"
        "\t\t)\n"
        "\tmeasure Forecast Amount - USD - March (view) = 1\n"
        "\tmeasure Transaction Amount - USD = 1\n",
        encoding="utf-8",
    )

    (report / "definition.pbir").write_text('{"version":"4.0"}', encoding="utf-8")
    (report / "report.json").write_text('{"sections":[]}', encoding="utf-8")

    results = analyzer.analyze(workspace)
    row = _find_item(results, "Measures", "Forecast Amount - USD - March", "Measure")

    assert row["status"] != "BROKEN (1 missing ref)"
    assert row["broken_dax_refs"] == []


def test_inline_calculated_columns_are_parsed_and_do_not_false_flag_measures(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Forecast.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    report.mkdir(parents=True)

    (tables_dir / "Date.tmdl").write_text(
        "table Date\n"
        "\tcolumn 'HasActuals USD' = CALCULATE(IF(ISBLANK([Transaction Amount - D365 - USD]), 0, 1), ALLEXCEPT('Date', 'Date'[YearMonth]))\n"
        "\tcolumn YearMonthNumber = 'Date'[Year]*12+'Date'[Month]\n"
        "\tcolumn Year\n"
        "\tcolumn Month\n"
        "\tcolumn YearMonth\n",
        encoding="utf-8",
    )
    (tables_dir / "Measures.tmdl").write_text(
        "table Measures\n"
        "\tmeasure Forecast Amount - USD - September - Dynamic (vena) =\n"
        "\t\tVAR _ForecastCutoff =\n"
        "\t\t\tCALCULATE(\n"
        "\t\t\t\tMAX('Date'[YearMonthNumber]),\n"
        "\t\t\t\t'Date'[HasActuals USD] = 1,\n"
        "\t\t\t\tREMOVEFILTERS('Date')\n"
        "\t\t\t)\n"
        "\t\tRETURN CALCULATE([Base Measure], KEEPFILTERS('Date'[YearMonthNumber] <= _ForecastCutoff))\n"
        "\tmeasure Base Measure = 1\n"
        "\tmeasure Transaction Amount - D365 - USD = 1\n",
        encoding="utf-8",
    )

    (report / "definition.pbir").write_text('{\"version\":\"4.0\"}', encoding="utf-8")
    (report / "report.json").write_text('{\"sections\":[]}', encoding="utf-8")

    parsed = analyzer.parse_model_items(model)
    parsed_refs = {(item.table, item.name, item.item_type) for item in parsed}
    assert ("Date", "HasActuals USD", "Calculated Column") in parsed_refs
    assert ("Date", "YearMonthNumber", "Calculated Column") in parsed_refs

    results = analyzer.analyze(workspace)
    measure = _find_item(results, "Measures", "Forecast Amount - USD - September - Dynamic (vena)", "Measure")
    assert measure["broken_dax_refs"] == []


def test_field_parameter_tables_warn_on_unresolved_nameof_targets(tmp_path):
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Forecast.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    pages_dir = report / "definition" / "pages" / "Page 1"
    tables_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    (tables_dir / "_Measures.tmdl").write_text(
        "table _Measures\n"
        "\tmeasure 'Summary Actuals' = 1\n"
        "\tmeasure 'Summary Budget' = 1\n"
        "\tmeasure 'Summary FC2' = 1\n",
        encoding="utf-8",
    )
    (tables_dir / "FP PNL.tmdl").write_text(
        "table 'FP PNL'\n"
        "\tcolumn 'FP PNL'\n"
        "\t\tsummarizeBy: none\n"
        "\tcolumn 'FP PNL Fields'\n"
        "\t\tsummarizeBy: none\n"
        "\tpartition 'FP PNL' = calculated\n"
        "\t\tsource = ```\n"
        "\t\t\t{\n"
        "\t\t\t    (\"Summary Actuals\", NAMEOF('_Measures'[Summary Actuals]), 1, \"MTH\"),\n"
        "\t\t\t    (\"Summary Budget\", NAMEOF('_Measures'[Summary Budget]), 2, \"MTH\"),\n"
        "\t\t\t    //(\"Summary FC1\", NAMEOF('_Measures'[Summary FC1]), 3, \"MTH\"),\n"
        "\t\t\t    (\"Summary Missing Active\", NAMEOF('_Measures'[Summary Missing Active]), 4, \"MTH\"),\n"
        "\t\t\t    (\"Summary Actuals\", NAMEOF('_Measures'[Summary Actuals]), 5, \"BUD\")\n"
        "\t\t\t    // (\"6\", NAMEOF('_Measures'[Summary Missing]), 6, \"BUD\")\n"
        "\t\t\t}\n"
        "\t\t\t```\n",
        encoding="utf-8",
    )
    (pages_dir / "page.json").write_text('{"displayName":"Overview"}', encoding="utf-8")

    results = analyzer.analyze(workspace.resolve())

    unresolved = [w for w in results["warnings"] if w["code"] == "UNRESOLVED_NAMEOF_TARGET"]
    assert len(unresolved) == 1
    assert "_Measures[Summary Missing Active]" in unresolved[0]["message"]
    assert "_Measures[Summary FC1]" not in unresolved[0]["message"]
    assert "_Measures[Summary Missing]" not in unresolved[0]["message"]

    table_summary = next(table for table in results["table_summaries"] if table["name"] == "FP PNL")
    assert table_summary["field_parameter_issues"] == [unresolved[0]["message"]]
    assert table_summary["signals"][0] == "Broken field parameter: 1 unresolved NAMEOF target."
