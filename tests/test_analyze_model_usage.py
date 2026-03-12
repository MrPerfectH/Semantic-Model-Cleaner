import json
from pathlib import Path

from semantic_model_cleaner import analyzer


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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


def test_unresolved_field_parameter_targets_do_not_emit_warnings(tmp_path):
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
    assert warnings == []


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
