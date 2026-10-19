"""A broken item's own missing references do not make it used or undeletable.

Broken stays a diagnostic (status label, broken refs, Issues: Broken). Deletion
eligibility comes from usage and incoming evidence only: report use, retained
DAX/metadata consumers, relationships, review reasons and coverage gaps.
Synthetic temporary projects only; nothing is applied to real models.
"""
import json

import pytest

from semantic_model_cleaner import analyzer, insights, webapp
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


def project(tmp_path, carrier, extra=None, visual_measure=None):
    model = tmp_path / "Test.SemanticModel"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Scorecard.tmdl").write_text(
        "table Scorecard\n\tcolumn Name\n\t\tdataType: string\n", encoding="utf-8")
    (tables / "Carrier.tmdl").write_text(carrier, encoding="utf-8")
    for name, text in (extra or {}).items():
        (tables / name).write_text(text, encoding="utf-8")
    report = tmp_path / "Test.Report"
    (report / "definition" / "pages" / "Page").mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps(
        {"datasetReference": {"byPath": {"path": "../Test.SemanticModel"}, "byConnection": None}}),
        encoding="utf-8")
    (report / "definition" / "report.json").write_text("{}", encoding="utf-8")
    (report / "definition" / "pages" / "Page" / "page.json").write_text('{"displayName":"Page"}', encoding="utf-8")
    if visual_measure:
        visual = report / "definition" / "pages" / "Page" / "visuals" / "v1" / "visual.json"
        visual.parent.mkdir(parents=True)
        table, name = visual_measure
        visual.write_text(json.dumps({"visual": {"visualType": "card", "query": {"queryState": {"Values": {
            "projections": [{"field": {"Measure": {"Expression": {"SourceRef": {"Entity": table}},
                                                   "Property": name}}}]}}}}}), encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    return model, report, analysis


def row(analysis, name):
    return next(r for r in analysis["items"] if r["item"].name == name)


def api_item(analysis, model, name):
    return next(i for i in webapp._serialize_results(analysis, model_paths=[model])["items"] if i["name"] == name)


def api_table(analysis, model, name):
    return next(t for t in webapp._serialize_results(analysis, model_paths=[model])["tables"] if t["name"] == name)


def delete(model, report, *targets):
    return evaluate_deletion_policy(model, [report], [
        {"action": "delete", "item_type": kind, "table": table, "name": name} for kind, table, name in targets])


def rules(policy):
    return {v["rule_id"] for v in policy["violations"]}


def insight(tmp_path, name):
    root, model, reports, scope = insights.select_scope(tmp_path)
    return next(r for r in insights.Insights(root, model, reports, scope).items(search=name)["items"]["items"]
                if r["name"] == name)


BROKEN_MEASURE = "table Carrier\n\tmeasure Value = [Lost] + SUM(Gone[x])\n"


@pytest.mark.parametrize("carrier, kind, name, broken_status", [
    (BROKEN_MEASURE, "Measure", "Value", "BROKEN (2 missing refs)"),
    ("table Carrier\n\tmeasure Value = 1\n\t\tformatStringDefinition = IF(MAX('Scorecard Measures'[id]) = 2, \"0%\", \"0\")\n",
     "Measure", "Value", "BROKEN (1 missing ref)"),
    ("table Carrier\n\tcolumn Key\n\t\tdataType: string\n\tcolumn Calc = [Missing] + 1\n",
     "Calculated Column", "Calc", "BROKEN (1 missing ref)"),
])
def test_unused_broken_item_is_safe_and_deletable_without_hiding_broken(tmp_path, carrier, kind, name, broken_status):
    model, report, analysis = project(tmp_path, carrier)
    broken = row(analysis, name)
    assert broken["status"] == broken_status  # diagnostic label unchanged
    assert broken["broken_dax_ref_details"]
    assert broken["usage_status"] == "NOT USED"
    assert broken["removal_risk"] == "Safe"
    assert broken["review_triggers"] == []
    assert analysis["summary"]["broken"] == 1
    item = api_item(analysis, model, name)
    assert (item["usageState"], item["issueState"], item["deleteSafety"]) == ("Unused", "Broken", "Safe")
    assert item["brokenDaxRefDetails"] == broken["broken_dax_ref_details"]
    assert item["status"] == broken_status
    assert item["usageStatus"] == "NOT USED"
    assert delete(model, report, (kind, "Carrier", name))["ok"]
    assert insight(tmp_path, name)["cleanup"] == "Safe"
    assert insight(tmp_path, name)["status_code"] == "broken"


def test_broken_measure_used_by_report_stays_blocked(tmp_path):
    model, report, analysis = project(tmp_path, BROKEN_MEASURE, visual_measure=("Carrier", "Value"))
    broken = row(analysis, "Value")
    assert broken["status"] == "BROKEN (2 missing refs)"
    assert broken["usage_status"] == "USED"
    assert broken["removal_risk"] == ""
    item = api_item(analysis, model, "Value")
    assert (item["usageState"], item["issueState"], item["deleteSafety"]) == ("Used", "Broken", "Blocked")
    policy = delete(model, report, ("Measure", "Carrier", "Value"))
    assert not policy["ok"] and "SMC-D004" in rules(policy)
    assert insight(tmp_path, "Value")["cleanup"] == "Blocked"
    assert api_table(analysis, model, "Carrier")["cleanupRecommendation"] == "Blocked"


def test_broken_measure_reached_through_used_consumer_is_indirect_and_blocked(tmp_path):
    model, report, analysis = project(
        tmp_path, BROKEN_MEASURE + "\tmeasure Shown = [Value] * 2\n", visual_measure=("Carrier", "Shown"))
    broken = row(analysis, "Value")
    assert broken["usage_status"].startswith("INDIRECT")
    assert api_item(analysis, model, "Value")["usageState"] == "Indirect"
    assert api_item(analysis, model, "Value")["deleteSafety"] == "Blocked"
    policy = delete(model, report, ("Measure", "Carrier", "Value"))
    assert {"SMC-D004", "SMC-D006"} <= rules(policy)


def test_retained_unused_consumer_blocks_broken_measure_until_removed_together(tmp_path):
    model, report, analysis = project(tmp_path, BROKEN_MEASURE + "\tmeasure Total = [Value] * 2\n")
    broken = row(analysis, "Value")
    assert broken["usage_status"] == "NOT USED"
    assert broken["removal_risk"] == "Caution"
    assert api_item(analysis, model, "Value")["deleteSafety"] == "Blocked"
    alone = delete(model, report, ("Measure", "Carrier", "Value"))
    assert not alone["ok"] and rules(alone) == {"SMC-D006"}
    assert any("required by retained Carrier[Total]" in v["message"] for v in alone["violations"])
    assert delete(model, report, ("Measure", "Carrier", "Value"), ("Measure", "Carrier", "Total"))["ok"]


def test_retained_metadata_consumer_blocks_broken_measure(tmp_path):
    model, report, analysis = project(
        tmp_path, BROKEN_MEASURE + "\tmeasure Other = 1\n\t\tformatStringDefinition = IF([Value] > 0, \"0%\", \"0\")\n")
    assert row(analysis, "Value")["removal_risk"] == "Caution"
    policy = delete(model, report, ("Measure", "Carrier", "Value"))
    assert not policy["ok"] and "SMC-D006" in rules(policy)


def test_hidden_broken_measure_needs_review_not_auto_safe(tmp_path):
    model, report, analysis = project(tmp_path, BROKEN_MEASURE + "\t\tisHidden\n")
    broken = row(analysis, "Value")
    assert broken["removal_risk"] == "Review"
    assert broken["review_triggers"] == ["Item is hidden"]
    assert api_item(analysis, model, "Value")["deleteSafety"] == "Review"
    policy = delete(model, report, ("Measure", "Carrier", "Value"))
    assert not policy["ok"] and rules(policy) == {"SMC-D005"}


def test_unresolved_metadata_gap_keeps_broken_unused_measure_fail_closed(tmp_path):
    model, report, analysis = project(tmp_path, BROKEN_MEASURE, extra={
        "Dynamic.tmdl": "table Dynamic\n\tmeasure Fmt = 1\n\t\tformatStringDefinition = SELECTEDMEASUREFORMATSTRING()\n"})
    assert not analysis["coverage"]["complete"]
    broken = row(analysis, "Value")
    assert broken["removal_risk"] == "Review"
    assert broken["analysis_limitation_ids"]
    assert api_item(analysis, model, "Value")["deleteSafety"] == "Review"
    policy = delete(model, report, ("Measure", "Carrier", "Value"))
    assert not policy["ok"] and "SMC-D002" in rules(policy)


def test_relationship_column_with_broken_sibling_stays_used(tmp_path):
    model, report, analysis = project(
        tmp_path, "table Carrier\n\tcolumn Key\n\t\tdataType: string\n\tcolumn Calc = [Missing] + 1\n",
        extra={"Dim.tmdl": "table Dim\n\tcolumn Key\n\t\tdataType: string\n"})
    (model / "definition" / "relationships.tmdl").write_text(
        "relationship r1\n\tfromColumn: Carrier.Key\n\ttoColumn: Dim.Key\n", encoding="utf-8")
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert row(analysis, "Calc")["removal_risk"] == "Safe"
    assert next(r for r in analysis["items"] if r["item"].key == ("Carrier", "Key"))["status"] == "USED (Relationship)"
    summary = next(t for t in analysis["table_summaries"] if t["name"] == "Carrier")
    assert summary["cleanup_recommendation"] == "Blocked"
    policy = delete(model, report, ("table", "Carrier", ""))
    assert not policy["ok"] and "SMC-D004" in rules(policy)


def test_table_is_not_kept_only_by_its_orphan_broken_measure(tmp_path):
    model, report, analysis = project(tmp_path, BROKEN_MEASURE)
    summary = next(t for t in analysis["table_summaries"] if t["name"] == "Carrier")
    assert summary["cleanup_recommendation"] == "Safe"
    table = api_table(analysis, model, "Carrier")
    assert table["cleanupRecommendation"] == "Safe"
    assert table["issueCounts"]["Broken"] == 1
    assert table["cleanupCounts"]["Safe"] == 1
    assert delete(model, report, ("table", "Carrier", ""))["ok"]


def test_broken_measure_reading_existing_table_does_not_keep_either(tmp_path):
    model, report, analysis = project(tmp_path, "table Carrier\n\tmeasure Value = SUM(Scorecard[Gone])\n")
    assert row(analysis, "Value")["removal_risk"] == "Safe"
    assert delete(model, report, ("table", "Scorecard", ""), ("Measure", "Carrier", "Value"))["ok"]
    assert delete(model, report, ("Measure", "Carrier", "Value"))["ok"]
    assert next(t for t in analysis["table_summaries"] if t["name"] == "Scorecard")["cleanup_recommendation"] == "Safe"
