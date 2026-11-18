"""Refactor regressions found by a real 45-table rename (smc feedback 2026-11-18)."""
import json

import pytest

from semantic_model_cleaner import change_plan


def project(tmp_path, visual, extensions=None):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text("table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n",
                                       encoding="utf-8")
    (tables / "Cost.tmdl").write_text("table Cost\n\tcolumn Value\n", encoding="utf-8")
    path = report / "definition/pages/P/visuals/V/visual.json"
    path.parent.mkdir(parents=True)
    path.write_text(visual, encoding="utf-8")
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    if extensions is not None:
        (report / "definition/reportExtensions.json").write_text(extensions, encoding="utf-8")
    (report / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}), encoding="utf-8")
    return model, report


def rename(old, new):
    return [{"kind": "rename", "table_renames": [{"table": old, "target_table": new}]}]


def after(plan, suffix):
    change = next(c for c in plan["changes"] if c["path"].endswith(suffix))
    return change_plan._decoded(change["after"]).decode("utf-8")


def visual_json(**extra):
    payload = {"visual": {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": [
        {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Revenue"}},
         "queryRef": "Sales.Revenue"}]}}}}}
    payload["visual"].update(extra)
    return json.dumps(payload, indent=2)


def test_a_stale_reference_is_not_introduced_by_a_table_taking_its_name(tmp_path):
    stale = {"objects": {"columnWidth": [{"selector": {"metadata": "Region.Level_1"}}]}}
    model, report = project(tmp_path, visual_json(**stale))
    plan = change_plan.create_plan(model, [report], rename("Cost", "Region"))
    assert any(c["path"].endswith("Region.tmdl") for c in plan["changes"])


def test_a_new_broken_reference_is_still_rejected(tmp_path):
    model, report = project(tmp_path, visual_json())
    ops = [{"kind": "actions", "actions": [
        {"action": "delete", "table": "Sales", "name": "Revenue", "item_type": "Measure"}]}]
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, [report], ops)


def test_table_rename_rewrites_report_extension_query_strings(tmp_path):
    visual = visual_json(objects={"x": [{"selector": {"metadata": "extension.Sales.PTP"}}]})
    visual = visual.replace('"queryRef": "Sales.Revenue"', '"queryRef": "extension.Sales.PTP"')
    extensions = json.dumps({"name": "extension", "entities": [{"name": "Sales", "measures": [
        {"name": "PTP", "dataType": "Double", "expression": "1"}]}]})
    model, report = project(tmp_path, visual, extensions)
    plan = change_plan.create_plan(model, [report], rename("Sales", "Fakty"))
    text = after(plan, "visual.json")
    assert "extension.Fakty.PTP" in text and "extension.Sales." not in text
    assert json.loads(after(plan, "reportExtensions.json"))["entities"][0]["name"] == "Fakty"


@pytest.mark.parametrize("newline", ["", "\n"])
def test_rewritten_json_keeps_its_original_final_newline(tmp_path, newline):
    model, report = project(tmp_path, visual_json() + newline)
    plan = change_plan.create_plan(model, [report], rename("Sales", "Fakty"))
    assert after(plan, "visual.json").endswith("\n") is bool(newline)
