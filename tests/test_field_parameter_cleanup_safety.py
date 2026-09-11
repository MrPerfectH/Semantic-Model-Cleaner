"""Unused field parameters still retain structural NAMEOF dependencies."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


def project(tmp_path, item_type="Measure", reference="'Sales'[Target]"):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    target = "measure Target = 2" if item_type == "Measure" else "column Target"
    (tables / "Sales.tmdl").write_text("table Sales\n\tmeasure Existing = 1\n\t" + target + "\n")
    (tables / "Parameter.tmdl").write_text(
        "table Parameter\n\tcolumn Label\n\tcolumn Fields\n\tpartition Parameter = calculated\n"
        "\t\tsource =\n\t\t\t{ (\"Target\", NAMEOF(" + reference + "), 0) }\n")
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text("{}")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    return model, report


def delete(table, name, item_type="Measure"):
    return {"action": "delete", "table": table, "name": name, "item_type": item_type}


@pytest.mark.parametrize("item_type,reference", [("Measure", "'Sales'[Target]"),
                                                  ("Measure", "[Target]"), ("Column", "Sales[Target]")])
def test_unused_field_parameter_protects_retained_nameof_target(tmp_path, item_type, reference):
    model, report = project(tmp_path, item_type, reference)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    target = next(row for row in analysis["items"] if row["item"].name == "Target")
    assert target["status"] == "NOT USED"
    assert target["removal_risk"] == "Caution"
    actions = [delete("Sales", "Target", item_type)]
    policy = evaluate_deletion_policy(model, [report], actions)
    assert not policy["ok"], policy
    assert any(v["rule_id"] == "SMC-D006" and "NAMEOF" in v["message"] for v in policy["violations"])
    with pytest.raises(change_plan.PlanError, match="NAMEOF"):
        change_plan.create_plan(model, [report], [{"kind": "actions", "actions": actions}])
    assert change_plan._inventory(roots) == before


def test_combined_field_parameter_deletion_does_not_assume_definition_removed(tmp_path):
    model, report = project(tmp_path)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    actions = [delete("Parameter", "Label", "Column"), delete("Parameter", "Fields", "Column"),
               delete("Sales", "Target")]
    assert not evaluate_deletion_policy(model, [report], actions)["ok"]
    with pytest.raises(change_plan.PlanError, match="NAMEOF"):
        change_plan.create_plan(model, [report], [{"kind": "actions", "actions": actions}])
    assert change_plan._inventory(roots) == before


def test_target_deletion_requires_proven_parameter_removal_and_restores_exactly(tmp_path):
    model, report = project(tmp_path)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    parameter_plan = change_plan.create_plan(model, [report], [{"kind": "actions", "actions": [
        delete("Parameter", "Label", "Column"), delete("Parameter", "Fields", "Column")]}])
    assert change_plan._inventory(roots) == before
    journal = tmp_path / "journal"
    assert change_plan.apply_plan(parameter_plan, journal)["ok"]
    assert change_plan.verify_plan(parameter_plan)["ok"]
    assert analyzer.parse_field_parameters(model) == []
    target_plan = change_plan.create_plan(model, [report], [{"kind": "actions", "actions": [delete("Sales", "Target")]}])
    assert change_plan.apply_plan(target_plan, journal)["ok"]
    assert change_plan.verify_plan(target_plan)["ok"]
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert not any(w["code"] in {"UNRESOLVED_NAMEOF_TARGET", "AMBIGUOUS_NAMEOF_TARGET"} for w in analysis["warnings"])
    assert change_plan.restore_plan(target_plan, journal)["ok"]
    assert change_plan.restore_plan(parameter_plan, journal)["ok"]
    assert change_plan._inventory(roots) == before
