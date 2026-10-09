"""Retained metadata table consumers must never permit destructive cleanup."""
import json

import pytest

from semantic_model_cleaner import analyzer
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy
from semantic_model_cleaner.tmdl_declarations import extract_feature_expressions


def project(tmp_path, expression):
    model = tmp_path / "Test.SemanticModel"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tcolumn Amount\n\t\tdataType: int64\n"
        "\tcolumn Category\n\t\tdataType: string\n", encoding="utf-8")
    (tables / "Metrics.tmdl").write_text(
        "table Metrics\n\tmeasure Revenue = 1\n"
        f"\t\tdetailRowsDefinition = {expression}\n", encoding="utf-8")
    report = tmp_path / "Test.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps({
        "datasetReference": {"byPath": {"path": "../Test.SemanticModel"}}
    }), encoding="utf-8")
    (report / "definition" / "report.json").write_text("{}", encoding="utf-8")
    return model, report


@pytest.mark.parametrize("name", ["Fiscal 4-4-5", "FiscalCalendar"])
def test_named_calendar_resolves_to_owner_columns_without_global_gap(tmp_path, name):
    model, report = project(tmp_path, 'ROW("x", 1)')
    tables = model / "definition/tables"
    with (tables / "Sales.tmdl").open("a") as out:
        out.write(f"\n\tcalendar '{name}'\n\t\tcalendarColumnGroup = date\n\t\t\tprimaryColumn: Amount\n")
    (tables / "Time.tmdl").write_text(
        f"table Time\n\tcalculationGroup\n\t\tcalculationItem YTD = TOTALYTD(SELECTEDMEASURE(), '{name}')\n")
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert analysis["coverage"]["complete"]
    revenue = next(row for row in analysis["items"] if row["item"].name == "Revenue")
    assert revenue["removal_risk"] == "Safe"
    refs = analyzer.parse_unsupported_metadata_refs(model)
    consumer = next(ref for ref in refs if ref.feature == "calculation item expression")
    assert consumer.item_keys == {("Sales", "Amount"), ("Sales", "Category")}
    assert not consumer.unresolved_targets
    policy = evaluate_deletion_policy(model, [report], [{"action": "delete", "table": "Sales",
        "name": "Category", "item_type": "Column"}])
    assert not policy["ok"] and any(v["rule_id"] == "SMC-D006" for v in policy["violations"])
    assert evaluate_deletion_policy(model, [report], [{"action": "delete", "table": "Metrics",
        "name": "Revenue", "item_type": "Measure"}])["ok"]


@pytest.mark.parametrize("case", ["missing", "duplicate", "table_collision"])
def test_calendar_ambiguity_keeps_shared_coverage_guard(tmp_path, case):
    model, report = project(tmp_path, 'ROW("x", 1)')
    tables = model / "definition/tables"
    if case != "missing":
        with (tables / "Sales.tmdl").open("a") as out:
            out.write("\n\tcalendar Fiscal\n")
    if case == "duplicate":
        with (tables / "Metrics.tmdl").open("a") as out:
            out.write("\n\tcalendar Fiscal\n")
    if case == "table_collision":
        (tables / "Fiscal.tmdl").write_text("table Fiscal\n\tcolumn Date\n")
    (tables / "Time.tmdl").write_text(
        "table Time\n\tcalculationGroup\n\t\tcalculationItem YTD = TOTALYTD(SELECTEDMEASURE(), 'Fiscal')\n")
    assert not analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])["coverage"]["complete"]


def test_calendar_words_in_comments_or_dax_are_not_declarations(tmp_path):
    model, _ = project(tmp_path, 'ROW("calendar Fiscal", 1)')
    with (model / "definition/tables/Sales.tmdl").open("a") as out:
        out.write('\n\t// calendar Fiscal\n\tmeasure Label = "calendar Fiscal"\n')
    assert analyzer.parse_calendar_tables(model) == {}


@pytest.mark.parametrize("expression", [
    "'Sales'",
    "Sales",
    "sales",
    "FILTER('Sales', TRUE())",
    "FILTER(Sales, Sales[Amount] > 0)",
    "FILTER('Sales', 'Sales'[Amount] > 0)",
    'SELECTCOLUMNS(Sales, "Value", Sales[Amount])',
])
def test_metadata_table_consumers_block_column_and_table_deletion(tmp_path, expression):
    model, report = project(tmp_path, expression)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert not analysis["coverage"]["complete"]
    # Category is never named explicitly, but returning Sales still needs it.
    category = next(row for row in analysis["items"] if row["item"].name == "Category")
    assert category["removal_risk"] == "Review"
    for item_type, name in [("Column", "Category"), ("table", "")]:
        policy = evaluate_deletion_policy(model, [report], [{
            "action": "delete", "item_type": item_type, "table": "Sales", "name": name,
        }])
        assert not policy["ok"]
        assert any(v["rule_id"] == "SMC-D002" for v in policy["violations"])
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("expression", [
    'ROW("Value", 1)',
    'ROW("Value", "Sales")',
    'ROW("Value", "\'Sales\'")',
    'ROW("Value", 1) /* Sales and \'Sales\' are comments */',
])
def test_literal_only_metadata_does_not_block_unrelated_table(tmp_path, expression):
    model, report = project(tmp_path, expression)
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert analysis["coverage"]["complete"]
    assert evaluate_deletion_policy(model, [report], [{
        "action": "delete", "item_type": "table", "table": "Sales", "name": "",
    }])["ok"]


def test_dynamic_metadata_still_blocks_unrelated_table(tmp_path):
    model, report = project(tmp_path, 'ROW("Value", SELECTEDMEASURE())')
    assert not evaluate_deletion_policy(model, [report], [{
        "action": "delete", "item_type": "table", "table": "Sales", "name": "",
    }])["ok"]


@pytest.mark.parametrize("coverage", [
    "\t\tdataCoverageDefinition = Sales[Amount] > 0\n",
    "\t\tdataCoverageDefinition =\n\t\t\tSales[Amount] > 0\n",
    "\t\tdataCoverageDefinition = ```\n\t\t\tSales[Amount] > 0\n\t\t\t```\n",
])
def test_partition_coverage_blocks_deleting_referenced_column(tmp_path, coverage):
    model, report = project(tmp_path, 'ROW("Value", 1)')
    path = model / "definition" / "tables" / "Sales.tmdl"
    path.write_text(path.read_text(encoding="utf-8") +
                    "\tpartition Cold = m\n\t\tmode: directQuery\n"
                    "\t\tsource = let Source = 1 in Source\n" + coverage, encoding="utf-8")
    features, _ = extract_feature_expressions(path.read_text(encoding="utf-8"))
    assert len(features) == 1
    assert features[0].construct == "partition/dataCoverageDefinition"
    assert features[0].owner == "partition 'Cold' in 'Sales'"
    assert features[0].expression == "Sales[Amount] > 0"
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    amount = next(row for row in analysis["items"] if row["item"].name == "Amount")
    assert amount["removal_risk"] == "Review"
    assert any("partition 'Cold'" in trigger for trigger in amount["review_triggers"])
    assert not evaluate_deletion_policy(model, [report], [{
        "action": "delete", "item_type": "Column", "table": "Sales", "name": "Amount",
    }])["ok"]


def test_coverage_words_inside_partition_source_are_not_declarations():
    features, _ = extract_feature_expressions(
        "table Sales\n\tpartition Cold = m\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\tlet dataCoverageDefinition = 1 in dataCoverageDefinition\n")
    assert features == []
