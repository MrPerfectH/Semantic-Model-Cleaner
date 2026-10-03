"""Normal analysis and reviewed automation agree on connected Report scope."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from semantic_model_cleaner import analyzer, change_plan, ci, webapp


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scope_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(ROOT / "src/semantic_model_cleaner/demo_workspace", root)
    model = next(root.rglob("*.SemanticModel"))
    local = next(root.rglob("*.Report"))
    reports = {"local": local}
    bindings = {
        "live": {"byConnection": {"connectionString": f'Initial Catalog="{model.stem}"'}},
        "unrelated": {"byPath": {"path": "../Other.SemanticModel"}},
        "ambiguous": {"byPath": {"path": os.path.relpath(model, root / "ambiguous.Report")},
                      "byConnection": {"connectionString": f'Initial Catalog="{model.stem}"'}},
        "missing_reference": {},
        "remote": {"byConnection": {"connectionString": "Initial Catalog=Other"}},
    }
    for name in [*bindings, "missing", "malformed"]:
        report = root / (name + ".Report")
        shutil.copytree(local, report)
        definition = report / "definition.pbir"
        if name == "missing":
            definition.unlink()
        elif name == "malformed":
            definition.write_text("{broken", encoding="utf-8")
        else:
            definition.write_text(json.dumps({"datasetReference": bindings[name]}), encoding="utf-8")
        reports[name] = report
    previous = webapp._state.copy()
    monkeypatch.setitem(webapp._state, "workspace", str(root))
    yield root, model, reports
    webapp._state.clear()
    webapp._state.update(previous)


def cli(*args, cwd):
    return subprocess.run([sys.executable, "-m", "semantic_model_cleaner", *map(str, args)],
                          cwd=cwd, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                          capture_output=True, timeout=60)


def statuses(scope):
    return {Path(row["path"]).name: row["status"] for group in ("selected", "excluded")
            for row in scope[group]}


def test_default_scope_matches_cli_ui_check_plan_and_reference_counts(scope_project, tmp_path):
    root, model, reports = scope_project
    expected = {str(reports[key].resolve()) for key in ("local", "live")}
    result = analyzer.analyze(root)
    baseline = analyzer.analyze(root, model_paths=[model],
                                report_paths=[reports["local"], reports["live"]])
    assert result["summary"]["total_usage_refs"] == baseline["summary"]["total_usage_refs"]
    assert [(row["item"].name, row["status"], row["removal_risk"], len(row["usages"]))
            for row in result["items"]] == [
                (row["item"].name, row["status"], row["removal_risk"], len(row["usages"]))
                for row in baseline["items"]]
    assert {row["path"] for row in result["report_binding"]["selected"]} == expected
    run = cli(root, "--format", "json", cwd=root)
    assert run.returncode == 0, run.stderr.decode("utf-8")
    ordinary = json.loads(run.stdout)
    assert ordinary["summary"]["total_usage_refs"] == baseline["summary"]["total_usage_refs"]
    assert "unrelated.Report" in run.stderr.decode("utf-8")
    response = webapp.app.test_client().post("/api/analyze", json={
        "model_paths": [str(model)], "report_paths": list(map(str, reports.values()))})
    assert response.status_code == 200, response.json
    assert statuses(response.json["reportBinding"]) == statuses(ordinary["reportBinding"])
    assert statuses(ordinary["reportBinding"]) == statuses(result["report_binding"])
    _, checked = ci.run_check(root)
    assert {(root / row).resolve() for row in checked["scope"]["reports"]} == {Path(p) for p in expected}
    assert {Path(row["path"]).name: row["status"] for row in checked["scope"]["bindings"]} == statuses(result["report_binding"])
    assert all(row["message"] for row in checked["scope"]["bindings"])
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps([{"kind": "actions", "actions": [{
        "action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"
    }]}]), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    run = cli("plan", root, "--operations", operations, "-o", plan_path, cwd=root)
    assert run.returncode == 0, run.stderr.decode("utf-8")
    assert statuses(json.loads(run.stdout)["reportBinding"]) == statuses(result["report_binding"])
    plan = change_plan.load_plan(plan_path)
    assert {p for key, p in plan["scope"].items() if key != "model"} == expected
    assert statuses(result["report_binding"])["ambiguous.Report"] == "ambiguous_definition"


def test_unrelated_report_cannot_change_unused_recommendation(scope_project):
    root, model, reports = scope_project
    # The unrelated report alone references this otherwise unused measure.
    table = model / "definition/tables/Sales.tmdl"
    with table.open("a", encoding="utf-8") as handle:
        handle.write("\n\tmeasure UnrelatedOnly = 1\n")
    visual = next(reports["unrelated"].rglob("visual.json"))
    visual.write_text(json.dumps({"visual": {"visualType": "card", "query": {
        "queryState": {"Values": {"projections": [{"field": {"Measure": {
            "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "UnrelatedOnly"
        }}}]}}}}}), encoding="utf-8")
    normal = analyzer.analyze(root)
    row = next(row for row in normal["items"] if row["item"].name == "UnrelatedOnly")
    assert not row["usages"]
    assert row["status"] == "NOT USED"
    diagnostic = analyzer.analyze(root, model_paths=[model], report_paths=[reports["unrelated"]])
    assert next(row for row in diagnostic["items"] if row["item"].name == "UnrelatedOnly")["usages"]


def test_filters_and_interactive_selection_see_only_connected_reports(scope_project, monkeypatch, capsys):
    root, _, reports = scope_project
    run = cli(root, "--report", "unrelated", "--format", "json", cwd=root)
    assert run.returncode != 0
    assert not run.stdout
    assert "No matching connected" in run.stderr.decode("utf-8")
    seen = []
    def choose(kind, paths, _label):
        seen.append((kind, paths))
        return paths[:1]
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(analyzer, "select_paths_interactively", choose)
    analyzer.main([str(root), "--interactive", "--format", "json"])
    output = json.loads(capsys.readouterr().out)
    assert set(seen[1][1]) == {reports["local"], reports["live"]}
    assert len(output["reportBinding"]["selected"]) == 1
    assert any(row["status"] == "not_selected" for row in output["reportBinding"]["excluded"])


def test_explicit_unverified_refactor_scope_is_still_rejected(scope_project):
    _, model, reports = scope_project
    for kind in ("unrelated", "missing", "malformed", "ambiguous"):
        with pytest.raises(change_plan.PlanError, match="bound|invalid metadata"):
            change_plan.create_plan(model, [reports[kind]], [{"kind": "rename",
                "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Sales Total"}]}])


def test_empty_connected_scope_returns_exclusion_evidence(scope_project, tmp_path):
    root, _, reports = scope_project
    for key in ("local", "live"):
        (reports[key] / "definition.pbir").write_text("{}", encoding="utf-8")
    run = cli(root, "--format", "json", cwd=root)
    assert run.returncode != 0 and not run.stdout
    assert "No matching connected" in run.stderr.decode("utf-8")
    assert "ambiguous.Report" in run.stderr.decode("utf-8")
    code, checked = ci.run_check(root)
    assert code == 2
    assert checked["scope"]["selected_report_count"] == 0
    assert len(checked["scope"]["bindings"]) == len(reports)
    operations = tmp_path / "operations.json"
    operations.write_text("[]", encoding="utf-8")
    run = cli("plan", root, "--operations", operations, "-o", tmp_path / "plan.json", cwd=root)
    assert run.returncode == 2 and not run.stdout
    error = json.loads(run.stderr)
    assert "No connected" in error["error"]
    assert len(error["reportBinding"]["excluded"]) == len(reports)


def test_interactive_prompts_do_not_contaminate_json_stdout(scope_project, monkeypatch, capsys):
    root, _, _ = scope_project
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "all")
    analyzer.main([str(root), "--interactive", "--format", "json"])
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)["reportBinding"]["selected"]) == 2
    assert "reports selection" in captured.err


def test_excluded_report_remains_protected_from_exports(scope_project):
    root, _, reports = scope_project
    target = reports["unrelated"] / "definition.pbir"
    before = target.read_bytes()
    run = cli(root, "--format", "json", "-o", target, cwd=root)
    assert run.returncode == 2
    assert target.read_bytes() == before
