"""Artifact roles preserve resources and exclude scratch editor state."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan as plans, metadata_validation
from test_cleanup_scope import fixture

REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.0.0/schema.json"


def declare(report, path="theme.dax"):
    document = {"$schema": REPORT_SCHEMA, "layoutOptimization": "None",
                "themeCollection": {}, "resourcePackages": [
                    {"name": "RegisteredResources", "type": "RegisteredResources",
                     "items": [{"name": "Theme", "path": path, "type": "CustomTheme"}]}]}
    assert metadata_validation.validate_document(document)["status"] == "valid"
    (report / "definition/report.json").write_text(json.dumps(document), encoding="utf-8")
    resource = report / "StaticResources/RegisteredResources" / path
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_bytes(b'{"name":"Blue","dataColors":["#0000FF"]}')
    return resource


@pytest.mark.parametrize("kind", ["model", "report"])
def test_declared_dax_resource_staged_and_drift_guarded(tmp_path, monkeypatch, kind):
    model, reports, op = fixture(tmp_path, kind)
    resource = declare(reports[0])
    original = plans._analyze
    staged = []
    def inspect(roots, cache=None):
        if roots["model"] != model:
            copy = roots["report-1"] / resource.relative_to(reports[0])
            assert copy.read_bytes() == resource.read_bytes()
            staged.append(True)
        return original(roots, cache)
    monkeypatch.setattr(plans, "_analyze", inspect)
    plan = plans.create_plan(model, reports, [op])
    assert staged
    assert any(k.endswith("theme.dax") for k in plan["inputs"])
    resource.write_bytes(b'{"name":"Red","dataColors":["#FF0000"]}')
    with pytest.raises(plans.PlanError, match="Stale plan"):
        plans.apply_plan(plan, tmp_path / "journal")


@pytest.mark.parametrize("kind", ["model", "report"])
@pytest.mark.parametrize("owner", ["model", "report"])
@pytest.mark.parametrize("content", [
    b'{"version":"1.0.0","tabOrder":["Unused"],"defaultTab":"Unused"}',
    b"", b"{malformed", b'{"$schema":"https://unknown.invalid/schema.json"}',
])
def test_editor_state_does_not_affect_analysis_or_staging(tmp_path, monkeypatch, kind, owner, content):
    model, reports, op = fixture(tmp_path, kind)
    def analyze():
        a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
        return a["coverage"], a["report_issues"], [
            (r["item"].table, r["item"].name, r["usage_status"], r["removal_risk"],
             r.get("report_measure_delete")) for r in a["items"]]
    before = analyze()
    root = model if owner == "model" else reports[0]
    path = root / "DAXQueries/.pbi/daxQueries.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    assert analyze() == before
    original = plans._analyze
    def inspect(roots, cache=None):
        if roots["model"] != model:
            assert not any((r / "DAXQueries/.pbi/daxQueries.json").exists() for r in roots.values())
        return original(roots, cache)
    monkeypatch.setattr(plans, "_analyze", inspect)
    plan = plans.create_plan(model, reports, [op])
    assert not any(k.endswith("daxQueries.json") for k in plan["inputs"])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert path.read_bytes() == content


@pytest.mark.parametrize("kind", ["model", "report"])
@pytest.mark.parametrize("owner", ["model", "report"])
@pytest.mark.parametrize("drift", ["edit", "add", "delete"])
@pytest.mark.parametrize("when", ["preview", "before_apply", "after_apply"])
def test_editor_concurrent_changes_preserved(tmp_path, monkeypatch, kind, owner, drift, when):
    model, reports, op = fixture(tmp_path, kind)
    root = model if owner == "model" else reports[0]
    path = root / "DAXQueries/.pbi/daxQueries.json"
    path.parent.mkdir(parents=True)
    if drift != "add":
        path.write_bytes(b'{"version":"1.0.0","tabOrder":["Query 1"],"defaultTab":"Query 1"}')
    def mutate():
        if drift == "delete":
            path.unlink()
        else:
            path.write_bytes(b'{"version":"1.0.0","tabOrder":["Unused"],"defaultTab":"Unused"}')
    original = plans._analyze
    changed = False
    def inspect(roots, cache=None):
        nonlocal changed
        result = original(roots, cache)
        if when == "preview" and not changed:
            mutate()
            changed = True
        return result
    monkeypatch.setattr(plans, "_analyze", inspect)
    plan = plans.create_plan(model, reports, [op])
    if when == "before_apply":
        mutate()
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    if when == "after_apply":
        mutate()
    expected = path.read_bytes() if path.exists() else None
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert (path.read_bytes() if path.exists() else None) == expected
    assert plans.verify_plan(plan)["state"] == "original"


@pytest.mark.parametrize("kind", ["model", "report"])
@pytest.mark.parametrize("relative", [".pbi/actual.json", "DAXQueries/.pbi/actual.json",
                                      "definition/folder.dax/actual.json"])
def test_other_json_metadata_remains_guarded(tmp_path, kind, relative):
    model, reports, op = fixture(tmp_path, kind)
    path = reports[0] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}")
    plan = plans.create_plan(model, reports, [op])
    path.write_bytes(b'{"changed":true}')
    with pytest.raises(plans.PlanError, match="Stale plan"):
        plans.apply_plan(plan, tmp_path / "journal")


def test_declared_editor_path_collision_remains_guarded(tmp_path):
    model, reports, op = fixture(tmp_path, "report")
    path = declare(reports[0], "../../DAXQueries/.pbi/daxQueries.json")
    plan = plans.create_plan(model, reports, [op])
    assert any(k.endswith("DAXQueries/.pbi/daxQueries.json") for k in plan["inputs"])
    path.write_bytes(b'{"name":"Changed"}')
    with pytest.raises(plans.PlanError, match="Stale plan"):
        plans.apply_plan(plan, tmp_path / "journal")


@pytest.mark.parametrize("owner", ["model", "report"])
@pytest.mark.parametrize("content", [b"{malformed", b'{"tabOrder":["LocalDateTable_x"]}'])
def test_auto_date_scope_ignores_editor_state(tmp_path, owner, content):
    from semantic_model_cleaner import auto_date_tables
    from test_auto_date_tables import project as date_project, ALL
    model, report = date_project(tmp_path)
    path = (model if owner == "model" else report) / "DAXQueries/.pbi/daxQueries.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    files, problems = auto_date_tables._read_scope(model, [report])
    assert not problems
    assert all(f.path != path for f in files)
    plan = plans.create_plan(model, [report], [ALL])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert path.read_bytes() == content
