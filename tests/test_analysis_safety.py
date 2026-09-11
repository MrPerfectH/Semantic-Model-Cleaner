"""Regression tests for conservative coverage and shared deletion policy."""
import json

import pytest

from semantic_model_cleaner import analyzer
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


@pytest.fixture
def project(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    report = tmp_path / "Executive.Report"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\tcolumn Amount\n\t\tdataType: decimal\n"
        "\tcolumn Spare\n\t\tdataType: string\n", encoding="utf-8")
    (report / "definition").mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps({
        "datasetReference": {"byPath": {"path": "../Sales.SemanticModel"}}
    }), encoding="utf-8")
    (report / "definition/report.json").write_text('{}', encoding="utf-8")
    return tmp_path, model, report


def analyze(project):
    root, model, report = project
    return analyzer.analyze(root, model_paths=[model], report_paths=[report])


def row(result, name):
    return next(row for row in result["items"] if row["item"].name == name)


def delete(name, item_type="Column"):
    return {"action": "delete", "table": "Sales", "name": name, "item_type": item_type}


def test_invalid_json_downgrades_safe_until_repaired(project):
    _, _, report = project
    path = report / "definition/report.json"
    path.write_text('{invalid', encoding="utf-8")
    result = analyze(project)
    assert not result["coverage"]["complete"]
    assert row(result, "Spare")["removal_risk"] == "Review"
    assert any("Executive/definition/report.json" in t for t in row(result, "Spare")["review_triggers"])
    assert not json.loads(analyzer.format_json_output(result))["coverage"]["complete"]
    path.write_text('{}', encoding="utf-8")
    assert row(analyze(project), "Spare")["removal_risk"] == "Safe"


def test_calculation_item_unqualified_reference_is_resolved(project):
    _, model, _ = project
    (model / "definition/tables/Time.tmdl").write_text(
        "table Time\n\tcalculationGroup\n\t\tcalculationItem Current = [Revenue]\n", encoding="utf-8")
    refs = analyzer.parse_unsupported_metadata_refs(model)
    assert refs[0].item_keys == {("Sales", "Revenue")}
    assert not refs[0].unresolved_targets
    result = analyze(project)
    assert row(result, "Revenue")["removal_risk"] == "Review"
    assert row(result, "Spare")["removal_risk"] == "Safe"


@pytest.mark.parametrize("expression", ["SELECTEDMEASURE()", "[Unknown]", "[Revenue] + [Unknown]", "Sales[Unknown]"])
def test_unknown_calculation_group_coverage_is_retained(project, expression):
    _, model, _ = project
    (model / "definition/tables/Time.tmdl").write_text(
        "table Time\n\tcalculationGroup\n\t\tcalculationItem Current = " + expression + "\n", encoding="utf-8")
    result = analyze(project)
    assert not result["coverage"]["complete"]
    assert row(result, "Spare")["removal_risk"] == "Review"


def test_policy_blocks_live_report_reference_and_leaves_files_unchanged(project):
    _, model, report = project
    path = report / "definition/pages/P/visuals/V/visual.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"visual": {"query": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Spare"}}}}), encoding="utf-8")
    source = model / "definition/tables/Sales.tmdl"
    before = source.read_bytes()
    result = evaluate_deletion_policy(model, [report], [delete("Spare")])
    assert not result["ok"]
    assert any(v["rule_id"] == "SMC-D004" for v in result["violations"])
    assert source.read_bytes() == before


def test_policy_allows_unused_chain_but_blocks_retained_dependent(project):
    _, model, report = project
    result = evaluate_deletion_policy(model, [report], [delete("Amount")])
    assert not result["ok"]
    assert any(v["rule_id"] == "SMC-D006" for v in result["violations"])
    assert evaluate_deletion_policy(model, [report], [delete("Amount"), delete("Revenue", "Measure")])["ok"]


def test_policy_reanalyzes_and_blocks_missing_or_invalid_scope(project):
    _, model, report = project
    assert evaluate_deletion_policy(model, [report], [delete("Spare")])["ok"]
    (report / "definition/report.json").write_text('{invalid', encoding="utf-8")
    assert not evaluate_deletion_policy(model, [report], [delete("Spare")])["ok"]
    assert not evaluate_deletion_policy(model, [], [delete("Spare")])["ok"]
    (report / "definition.pbir").unlink()
    assert not evaluate_deletion_policy(model, [report], [delete("Spare")])["ok"]
    assert evaluate_deletion_policy(model, [], [{"action": "hide"}])["ok"]


def test_policy_blocks_retained_sort_by_and_hierarchy(project):
    _, model, report = project
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tcolumn Label\n\t\tsortByColumn: Spare\n", encoding="utf-8")
    assert not evaluate_deletion_policy(model, [report], [delete("Spare")])["ok"]
    source.write_text(source.read_text() + "\thierarchy Geo\n\t\tlevel Spare\n\t\t\tcolumn: Spare\n", encoding="utf-8")
    result = evaluate_deletion_policy(model, [report], [delete("Spare"), delete("Label")])
    assert any("hierarchy" in v["message"] for v in result["violations"])


def test_detail_metadata_reads_known_properties_and_description_comments(project):
    _, model, _ = project
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(
        'table Sales\n\t/// Amount in local currency.\n\t/// Before tax.\n'
        '\tcolumn Amount\n\t\tdataType: decimal\n\t\tsourceColumn: AmountRaw\n\t\tformatString: 0.00\n', encoding="utf-8")
    item = analyzer.parse_model_items(model)[0]
    assert item.data_type == "decimal"
    assert item.source_column == "AmountRaw"
    assert item.description == "Amount in local currency.\nBefore tax."
    assert item.format_string == "0.00"


def test_policy_rejects_unknown_or_malformed_target(project):
    _, model, report = project
    for action in [delete("Absent"), {**delete("Spare"), "item_type": None}]:
        result = evaluate_deletion_policy(model, [report], [action])
        assert not result["ok"]
        assert result["violations"][0]["rule_id"] == "SMC-D003"
