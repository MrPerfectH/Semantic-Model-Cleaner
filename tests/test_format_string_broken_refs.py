"""A missing target in a measure format string breaks that measure, not model coverage.

Also covers bare known-table references in metadata expressions: they protect
that table's columns while the owner remains instead of every unused item.
"""
import json

import pytest

from semantic_model_cleaner import analyzer, webapp
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


FORMAT_MESSAGE = " in the format string expression (formatStringDefinition)"


def project(tmp_path, carrier, extra=None):
    model = tmp_path / "Test.SemanticModel"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Unrelated.tmdl").write_text(
        "table Unrelated\n\tcolumn parent_functional_location\n\t\tdataType: string\n", encoding="utf-8")
    (tables / "Scorecard.tmdl").write_text(
        "table Scorecard\n\tcolumn Name\n\t\tdataType: string\n\tcolumn Unit\n\t\tdataType: string\n",
        encoding="utf-8")
    (tables / "Carrier.tmdl").write_text(carrier, encoding="utf-8")
    for name, text in (extra or {}).items():
        (tables / name).write_text(text, encoding="utf-8")
    report = tmp_path / "Test.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps(
        {"datasetReference": {"byPath": {"path": "../Test.SemanticModel"}}}), encoding="utf-8")
    (report / "definition" / "report.json").write_text("{}", encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    return model, report, analysis


def row(analysis, name):
    return next(r for r in analysis["items"] if r["item"].name == name)


def measure(body, fmt):
    return f"table Carrier\n\tmeasure Value = {body}\n\t\tformatStringDefinition = {fmt}\n"


@pytest.mark.parametrize("fmt, ref, message", [
    ("IF(SELECTEDVALUE('Scorecard Measures'[id]) = 2, \"0.0%\", \"0\")", "Scorecard Measures[id]",
     "Missing column (table not found): Scorecard Measures[id]"),
    ("IF(MAX(Scorecard[DB Order]) = 1, \"0%\", \"0\")", "Scorecard[DB Order]",
     "Missing column: Scorecard[DB Order]"),
    ("IF(COUNTROWS('Gone') > 0, \"0%\", \"0\")", "Gone", "Missing table: Gone"),
])
def test_missing_format_string_target_marks_owner_broken_without_shared_gap(tmp_path, fmt, ref, message):
    _, _, analysis = project(tmp_path, measure("1", fmt))
    assert analysis["coverage"]["complete"]
    assert analysis["analysis_limitations"] == []
    owner = row(analysis, "Value")
    assert owner["status"] == "BROKEN (1 missing ref)"
    detail = owner["broken_dax_ref_details"][0]
    assert detail["ref"] == ref
    assert detail["message"] == message + FORMAT_MESSAGE
    assert detail["expression"] == "format string expression"
    # The missing reference is a diagnostic, not a review reason: the unused
    # owner itself is deletable (it stays labelled Broken).
    assert owner["review_triggers"] == []
    assert owner["usage_status"] == "NOT USED"
    assert owner["removal_risk"] == "Safe"
    # Unrelated unused items are no longer downgraded by the broken measure.
    assert row(analysis, "parent_functional_location")["removal_risk"] == "Safe"
    assert row(analysis, "parent_functional_location")["analysis_limitation_ids"] == []


def test_format_string_reason_reaches_api_and_json_export(tmp_path):
    _, _, analysis = project(tmp_path, measure("1", "IF(MAX('Scorecard Measures'[id]) = 2, \"0%\", \"0\")"))
    expected = [{"kind": "column", "ref": "Scorecard Measures[id]",
                 "message": "Missing column (table not found): Scorecard Measures[id]" + FORMAT_MESSAGE,
                 "expression": "format string expression"}]
    api_item = next(item for item in webapp._serialize_results(analysis)["items"] if item["name"] == "Value")
    assert api_item["brokenDaxRefDetails"] == expected
    assert api_item["brokenDaxRefs"] == ["Scorecard Measures[id]"]
    exported = json.loads(analyzer.format_json_output(analysis))
    assert next(item for item in exported["items"] if item["name"] == "Value")["brokenDaxRefDetails"] == expected


def test_reference_missing_in_body_and_format_string_names_both(tmp_path):
    _, _, analysis = project(tmp_path, measure("MAX(Gone[x]) + [Lost]", "IF(MAX(Gone[x]) = 1, \"0\", \"0%\")"))
    details = {d["ref"]: d for d in row(analysis, "Value")["broken_dax_ref_details"]}
    assert details["Gone[x]"]["message"] == (
        "Missing column (table not found): Gone[x] in the measure expression and its format string expression")
    # A body-only reference keeps the existing wording and no expression marker.
    assert details["[Lost]"] == {"kind": "measure", "ref": "[Lost]", "message": "Missing measure: [Lost]"}


def test_valid_format_string_target_stays_protected_next_to_missing_one(tmp_path):
    model, report, analysis = project(
        tmp_path, measure("1", "IF(MAX(Scorecard[Unit]) = \"%\" && MAX(Gone[x]) = 1, \"0%\", \"0\")"))
    assert analysis["coverage"]["complete"]
    unit = row(analysis, "Unit")
    assert unit["removal_risk"] == "Caution"
    assert unit["review_triggers"] == [
        "Required by retained measure format-string expression of measure 'Carrier'[Value] "
        "(definition/tables/Carrier.tmdl:3)"]
    assert row(analysis, "Name")["removal_risk"] == "Safe"
    policy = evaluate_deletion_policy(model, [report], [
        {"action": "delete", "item_type": "Column", "table": "Scorecard", "name": "Unit"}])
    assert not policy["ok"] and any(v["rule_id"] == "SMC-D006" for v in policy["violations"])


@pytest.mark.parametrize("fmt", [
    "IF([Unknown] > 0, \"0%\", \"0\")",                 # unqualified name matching no measure
    "SELECTEDMEASUREFORMATSTRING()",                    # dynamic
    "IF(MAX(Gone[x]) = 1, SELECTEDMEASUREFORMATSTRING(), \"0\")",  # missing ref does not hide a dynamic gap
])
def test_ambiguous_or_dynamic_format_strings_still_fail_closed(tmp_path, fmt):
    _, _, analysis = project(tmp_path, measure("1", fmt))
    assert not analysis["coverage"]["complete"]
    assert row(analysis, "parent_functional_location")["removal_risk"] == "Review"


def test_ambiguous_measure_name_in_format_string_fails_closed(tmp_path):
    _, _, analysis = project(tmp_path, measure("1", "IF([Twin] > 0, \"0%\", \"0\")"), extra={
        "A.tmdl": "table A\n\tmeasure Twin = 1\n", "B.tmdl": "table B\n\tmeasure Twin = 2\n"})
    assert not analysis["coverage"]["complete"]


def test_missing_target_outside_format_string_keeps_shared_gap_with_accurate_text(tmp_path):
    # A KPI target is not part of the measure item, so its owner is not marked broken.
    _, _, analysis = project(tmp_path, (
        "table Carrier\n\tmeasure Value = 1\n\t\tkpi\n"
        "\t\t\ttargetExpression = MAX(Gone[x]) + MAX(Scorecard[Unit])\n"))
    assert not analysis["coverage"]["complete"]
    assert row(analysis, "Value")["status"] == "NOT USED"
    (limitation,) = analysis["analysis_limitations"]
    assert limitation["scope"] == "shared"
    assert limitation["targets"] == ["Scorecard[Unit]"]
    assert limitation["missing_targets"] == ["Gone[x]"]
    assert "were resolved" not in limitation["checked"]
    assert limitation["checked"] == (
        "References matched to model items: Scorecard[Unit]. "
        "Coverage remains incomplete; see each item's cleanup recommendation. "
        "References to items that do not exist in the model: Gone[x].")


def test_self_table_detail_rows_protects_only_that_table(tmp_path):
    model, report, analysis = project(
        tmp_path, "table Carrier\n\tdefaultDetailRowsDefinition = 'Carrier'\n"
        "\tcolumn Code\n\t\tdataType: string\n\tcolumn Label\n\t\tdataType: string\n")
    assert analysis["coverage"]["complete"]
    assert analysis["analysis_limitations"] == []
    assert row(analysis, "parent_functional_location")["removal_risk"] == "Safe"
    assert row(analysis, "Name")["removal_risk"] == "Safe"
    code = row(analysis, "Code")
    # Protected, but the expression does not make the column count as used.
    assert code["status"] == "NOT USED"
    assert code["removal_risk"] == "Caution"
    assert code["review_triggers"] == [
        "Required by retained table default detail rows expression of table 'Carrier' "
        "(definition/tables/Carrier.tmdl:2), which references the whole table 'Carrier'"]
    column_only = evaluate_deletion_policy(model, [report], [
        {"action": "delete", "item_type": "Column", "table": "Carrier", "name": "Code"}])
    assert not column_only["ok"] and any(v["rule_id"] == "SMC-D006" for v in column_only["violations"])
    # The table-owned expression goes with its table.
    assert evaluate_deletion_policy(model, [report], [
        {"action": "delete", "item_type": "table", "table": "Carrier", "name": ""}])["ok"]


def test_bare_table_consumer_keeps_transitive_dependencies(tmp_path):
    model, report, analysis = project(
        tmp_path, "table Carrier\n\tmeasure Value = 1\n\t\tdetailRowsDefinition = Lookup\n",
        extra={"Lookup.tmdl": "table Lookup\n\tcolumn Key\n\t\tdataType: string\n"
                              "\tcolumn Label = RELATED(Scorecard[Name])\n"})
    assert analysis["coverage"]["complete"]
    assert row(analysis, "Name")["removal_risk"] == "Caution"  # needed by the protected calculated column
    for action in ({"action": "delete", "item_type": "table", "table": "Lookup", "name": ""},
                   {"action": "delete", "item_type": "Column", "table": "Scorecard", "name": "Name"}):
        policy = evaluate_deletion_policy(model, [report], [action])
        assert not policy["ok"] and any(v["rule_id"] == "SMC-D006" for v in policy["violations"])


def test_bare_reference_to_table_without_columns_fails_closed(tmp_path):
    _, _, analysis = project(
        tmp_path, "table Carrier\n\tmeasure Value = 1\n\t\tdetailRowsDefinition = ROW(\"n\", COUNTROWS(Metrics))\n",
        extra={"Metrics.tmdl": "table Metrics\n\tmeasure Total = 1\n"})
    assert not analysis["coverage"]["complete"]
    assert row(analysis, "parent_functional_location")["removal_risk"] == "Review"
