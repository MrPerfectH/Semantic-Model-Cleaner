"""Narrowed Report scope never lets a plan break connected Reports it did not select."""
import json

import pytest

from semantic_model_cleaner import change_plan, webapp
from test_cli_insights import visual, write_json
from test_cli_path_selection import run


EXTENSION = {"name": "extension", "entities": [{"name": "Sales", "measures": [
    {"name": "Local", "expression": "[Helper] + 1"}]}]}


@pytest.fixture
def project(tmp_path):
    """Exec uses Sales[Helper]; Ops, bound to the same model, uses only Sales[OpsOnly]."""
    root = tmp_path / "Zażółć scope"
    model = root / "Models/Sales.SemanticModel"
    (model / "definition/tables").mkdir(parents=True)
    (model / "definition/tables/Sales.tmdl").write_text(
        "table Sales\n\tmeasure Helper = 1\n\tmeasure OpsOnly = 2\n\tmeasure Spare = 3\n", encoding="utf-8")
    reports = {}
    for name, used in (("Exec", "Helper"), ("Ops", "OpsOnly")):
        report = root / "Reports" / f"{name}.Report"
        write_json(report / "definition.pbir", {"datasetReference": {"byPath": {"path": "../../Models/Sales.SemanticModel"}}})
        write_json(report / "definition/report.json", {})
        visual(report, "P", name=used)
        reports[name] = report
    return root, model, reports


def snapshot(root):
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def plan(tmp_path, root, operation, *selectors, expected=0):
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps([operation]), encoding="utf-8")
    target = tmp_path / "out/plan.json"
    target.unlink(missing_ok=True)
    result = run(tmp_path, ["plan", root, *selectors, "--operations", operations, "-o", target,
                            "--format", "json"], expected=expected)
    return target, result


def exec_only(root, reports):
    return ["--model-path", "Models/Sales.SemanticModel",
            "--report-path", reports["Exec"].relative_to(root)]


def delete(name):
    return {"kind": "actions", "actions": [{"action": "delete", "table": "Sales", "name": name, "item_type": "Measure"}]}


def rename(name):
    return {"kind": "rename", "measure_renames": [{"table": "Sales", "name": name, "target_name": name + " 2"}]}


def promote(report):
    return {"kind": "promote", "report_path": str(report), "table": "Sales", "name": "Local"}


def add_twin_extensions(reports):
    for report in reports.values():
        write_json(report / "definition/reportExtensions.json", EXTENSION)
        visual(report, "Local", name="Local")


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("kind", ["delete", "rename", "promote"])
def test_narrowed_scope_refuses_plans_that_can_break_unselected_connected_reports(project, tmp_path, kind, legacy):
    root, model, reports = project
    if kind == "promote":
        add_twin_extensions(reports)
    operation = {"delete": delete("OpsOnly"), "rename": rename("OpsOnly"), "promote": promote(reports["Exec"])}[kind]
    selectors = (["--model", model, "--report", reports["Exec"]] if legacy else exec_only(root, reports))
    before = snapshot(root)
    target, result = plan(tmp_path, root, operation, *selectors, expected=2)
    assert not result["ok"] and not target.exists()
    assert "Ops" in result["error"] and "not selected" in result["error"]
    assert "--allow-partial-report-scope" in result["error"]
    assert snapshot(root) == before


@pytest.mark.parametrize("kind", ["delete", "rename", "promote"])
def test_opt_in_records_incomplete_selection_and_check_finds_the_break(project, tmp_path, kind):
    """The opt-in is explicit and the saved plan never claims complete coverage."""
    root, model, reports = project
    if kind == "promote":
        add_twin_extensions(reports)
    operation = {"delete": delete("OpsOnly"), "rename": rename("OpsOnly"), "promote": promote(reports["Exec"])}[kind]
    target, result = plan(tmp_path, root, operation, *exec_only(root, reports), "--allow-partial-report-scope")
    assert result["ok"]
    saved = json.loads(target.read_text(encoding="utf-8"))
    selection = saved["coverage"]["report_selection"]
    assert selection["complete"] is False and selection["partial_scope_allowed"] is True
    assert [row["name"] for row in selection["unselected_connected"]] == ["Ops"]
    assert [row["name"] for row in selection["selected"]] == ["Exec"]
    assert saved["coverage"]["final_state"]["complete"] is False
    assert any("Ops" in note for note in saved["validation"]["limitations"])
    run(tmp_path, ["apply", target, "--format", "json"])
    check = run(tmp_path, ["check", root], expected=1)
    assert any(row["severity"] == "error" and "Ops.Report" in row["path"] for row in check["findings"])


def test_display_only_and_report_only_operations_stay_allowed_on_a_subset(project, tmp_path):
    root, model, reports = project
    hide = {"kind": "actions", "actions": [{"action": "hide", "table": "Sales", "name": "OpsOnly", "item_type": "Measure"}]}
    target, result = plan(tmp_path, root, hide, *exec_only(root, reports))
    selection = json.loads(target.read_text(encoding="utf-8"))["coverage"]["report_selection"]
    assert result["ok"] and selection["complete"] is False and selection["partial_scope_allowed"] is False


def test_default_scope_selects_every_connected_report_and_records_completeness(project, tmp_path):
    root, model, reports = project
    target, result = plan(tmp_path, root, delete("OpsOnly"), expected=2)
    assert "OpsOnly" in result["error"]
    target, result = plan(tmp_path, root, delete("Spare"))
    saved = json.loads(target.read_text(encoding="utf-8"))
    selection = saved["coverage"]["report_selection"]
    assert selection["complete"] is True and selection["unselected_connected"] == [] and selection["unverified"] == []
    assert sorted(row["name"] for row in selection["selected"]) == ["Exec", "Ops"]
    assert saved["coverage"]["final_state"]["complete"] is True


def test_unverified_binding_under_project_blocks_deletion_until_opted_in(project, tmp_path):
    root, model, reports = project
    write_json(reports["Ops"] / "definition.pbir", {"datasetReference": {"byConnection": {"connectionString": "Data Source=x"}}})
    target, result = plan(tmp_path, root, delete("Spare"), expected=2)
    assert "Ops" in result["error"] and "could not be verified" in result["error"]
    target, result = plan(tmp_path, root, delete("Spare"), "--allow-partial-report-scope")
    selection = json.loads(target.read_text(encoding="utf-8"))["coverage"]["report_selection"]
    assert [(row["name"], row["status"]) for row in selection["unverified"]] == [("Ops", "remote")]


def test_web_plan_api_refuses_subset_unless_opted_in(project, tmp_path, monkeypatch):
    root, model, reports = project
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path / "state"))
    monkeypatch.setitem(webapp._state, "workspace", str(root))
    monkeypatch.setitem(webapp._state, "report_search_roots", [str(root)])
    client = webapp.app.test_client()
    body = {"model_path": str(model), "report_paths": [str(reports["Exec"])], "operations": [delete("OpsOnly")]}
    before = snapshot(root)
    response = client.post("/api/plans", json=body)
    assert response.status_code == 400 and "Ops" in response.get_json()["error"]
    response = client.post("/api/plans", json={**body, "allow_partial_report_scope": True})
    assert response.status_code == 200
    assert response.get_json()["plan"]["coverage"]["report_selection"]["complete"] is False
    assert snapshot(root) == before


def test_engine_guard_uses_known_reports(project):
    root, model, reports = project
    with pytest.raises(change_plan.PlanError, match="Ops"):
        change_plan.create_plan(model, [reports["Exec"]], [rename("OpsOnly")], known_reports=list(reports.values()))
