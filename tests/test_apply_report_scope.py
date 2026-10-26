"""A preview's selected file hashes do not cover newly connected Reports (#181)."""
import json

import pytest

from semantic_model_cleaner import change_plan, webapp
from test_cli_insights import visual, write_json
from test_cli_path_selection import run
from test_partial_report_scope import (EXTENSION, delete, plan, project as scope_project,
                                       promote, rename, snapshot)


@pytest.fixture
def project(tmp_path):
    return scope_project.__wrapped__(tmp_path)


def add_report(root, name="Added", binding=None):
    # A different parent makes recording the original PROJECT root essential.
    report = root / "New area" / (name + ".Report")
    write_json(report / "definition.pbir", {"datasetReference": binding or {
        "byPath": {"path": "../../Models/Sales.SemanticModel"}}})
    write_json(report / "definition/report.json", {})
    visual(report, "P", name="Spare")
    return report


@pytest.mark.parametrize("binding", [None, {"byConnection": {"connectionString": "Data Source=unverified"}}])
@pytest.mark.parametrize("operation", [delete("Spare"), rename("Helper")])
def test_cli_apply_refuses_new_connected_or_unverified_report_before_writes(project, tmp_path, operation, binding):
    root, _, _ = project
    target, _ = plan(tmp_path, root, operation)
    add_report(root, binding=binding)
    before = snapshot(root)
    journal = tmp_path / "journal"
    output = run(tmp_path, ["apply", target, "--journal-dir", journal, "--format", "json"], expected=2)
    assert "Report" in output["error"] and "new plan" in output["error"].lower()
    assert snapshot(root) == before
    assert not journal.exists()


def test_api_apply_refuses_new_report_without_receipt_or_project_changes(project, tmp_path, monkeypatch):
    root, model, reports = project
    state = tmp_path / "state"
    monkeypatch.setenv("SMC_USER_DIR", str(state))
    monkeypatch.setitem(webapp._state, "workspace", str(root))
    monkeypatch.setitem(webapp._state, "report_search_roots", [str(root)])
    client = webapp.app.test_client()
    prepared = client.post("/api/plans", json={"model_path": str(model),
        "report_paths": [str(path) for path in reports.values()], "operations": [delete("Spare")]})
    assert prepared.status_code == 200, prepared.json
    plan_id = prepared.json["plan"]["id"]
    add_report(root)
    before, stored = snapshot(root), snapshot(state)
    response = client.post(f"/api/plans/{plan_id}/apply")
    assert response.status_code == 409 and "new plan" in response.json["error"].lower()
    assert snapshot(root) == before and snapshot(state) == stored


@pytest.mark.parametrize("scenario", ["unchanged", "disconnected", "partial-opt-in", "display-only"])
def test_unchanged_irrelevant_or_explicitly_allowed_scope_can_apply_and_restore(project, tmp_path, scenario):
    root, _, _ = project
    operation = ({"kind": "actions", "actions": [{"action": "hide", "table": "Sales",
                  "name": "Spare", "item_type": "Measure"}]} if scenario == "display-only" else delete("Spare"))
    flags = ["--allow-partial-report-scope"] if scenario == "partial-opt-in" else []
    target, _ = plan(tmp_path, root, operation, *flags)
    if scenario == "disconnected":
        add_report(root, binding={"byPath": {"path": "../../Models/Other.SemanticModel"}})
    elif scenario in {"partial-opt-in", "display-only"}:
        add_report(root)
    before = snapshot(root)
    journal = tmp_path / "journal"
    run(tmp_path, ["apply", target, "--journal-dir", journal, "--format", "json"])
    run(tmp_path, ["verify", target, "--format", "json"])
    run(tmp_path, ["restore", target, "--journal-dir", journal, "--format", "json"])
    assert snapshot(root) == before


def test_plan_seals_the_original_project_discovery_roots(project, tmp_path):
    root, _, _ = project
    target, _ = plan(tmp_path, root, delete("Spare"))
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["coverage"]["report_selection"]["discovery_roots"] == [str(root.resolve())]


@pytest.mark.parametrize("legacy", ["no-selection", "no-roots"])
def test_older_checked_or_unidentified_scope_requires_new_preview(project, tmp_path, legacy):
    root, _, _ = project
    target, _ = plan(tmp_path, root, delete("Spare"))
    saved = json.loads(target.read_text(encoding="utf-8"))
    if legacy == "no-selection":
        saved["coverage"].pop("report_selection")
    else:
        saved["coverage"]["report_selection"].pop("discovery_roots")
    saved["digest"] = change_plan._seal(saved)  # Construct a valid historical schema, not an edited-plan failure.
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="new plan"):
        change_plan.apply_plan(saved, tmp_path / "journal")
    assert snapshot(root) == before and not (tmp_path / "journal").exists()


def test_unchecked_low_level_scope_retains_its_explicit_scope_contract(project, tmp_path):
    root, model, reports = project
    saved = change_plan.create_plan(model, list(reports.values()), [delete("Spare")])
    assert saved["coverage"]["report_selection"]["checked"] is False
    assert change_plan.apply_plan(saved, tmp_path / "journal")["ok"]


def test_unavailable_search_root_is_not_silently_ignored(project, tmp_path):
    root, model, reports = project
    external = tmp_path / "External reports"
    external.mkdir()
    saved = change_plan.create_plan(model, list(reports.values()), [delete("Spare")],
        report_search_roots=[root, external])
    external.rmdir()
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="root is unavailable"):
        change_plan.apply_plan(saved, tmp_path / "journal")
    assert snapshot(root) == before and not (tmp_path / "journal").exists()


def test_external_selected_report_parent_is_monitored(project, tmp_path):
    root, model, reports = project
    external = tmp_path / "External"
    selected = external / "Outside.Report"
    write_json(selected / "definition.pbir", {"datasetReference": {"byPath": {"path": str(model)}}})
    write_json(selected / "definition/report.json", {})
    saved = change_plan.create_plan(model, [*reports.values(), selected], [delete("Spare")],
        report_search_roots=[root])
    assert saved["coverage"]["report_selection"]["discovery_roots"] == sorted(map(str, [root, external]))
    new = external / "New.Report"
    write_json(new / "definition.pbir", {"datasetReference": {"byPath": {"path": str(model)}}})
    write_json(new / "definition/report.json", {})
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="New"):
        change_plan.apply_plan(saved, tmp_path / "journal")
    assert snapshot(root) == before and not (tmp_path / "journal").exists()


def test_scope_is_checked_again_after_lock_and_fingerprint_check(project, tmp_path, monkeypatch):
    root, _, _ = project
    target, _ = plan(tmp_path, root, delete("Spare"))
    saved = change_plan.load_plan(target)
    original = change_plan._scope_hashes

    def concurrent_addition(*args):
        value = original(*args)
        add_report(root)
        return value

    monkeypatch.setattr(change_plan, "_scope_hashes", concurrent_addition)
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="new plan"):
        change_plan.apply_plan(saved, tmp_path / "journal")
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not list((tmp_path / "journal").iterdir())


def test_naming_preview_records_project_root_for_apply(project, tmp_path):
    from semantic_model_cleaner import review_policy
    root, model, reports = project
    policy = {"schema_version": "1.0", "naming_rules": [
        {"id": "prefix", "item_type": "Measure", "prefix": "m_"}]}
    saved = review_policy.naming_preview(root, model, list(reports.values()), policy=policy)["plan"]
    assert saved["coverage"]["report_selection"]["discovery_roots"] == [str(root)]
    add_report(root)
    with pytest.raises(change_plan.PlanError, match="new plan"):
        change_plan.apply_plan(saved, tmp_path / "journal")


@pytest.mark.parametrize("kind", ["move", "promote"])
def test_refactors_recheck_new_report_scope(project, tmp_path, kind):
    root, model, reports = project
    if kind == "promote":
        write_json(reports["Exec"] / "definition/reportExtensions.json", EXTENSION)
        visual(reports["Exec"], "Local", name="Local")
        operation = promote(reports["Exec"])
    else:
        (model / "definition/tables/Measures.tmdl").write_text("table Measures\n", encoding="utf-8")
        operation = {"kind": "move", "moves": [{"table": "Sales", "name": "Helper", "target_table": "Measures"}]}
    target, _ = plan(tmp_path, root, operation)
    add_report(root)
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="new plan"):
        change_plan.apply_plan(change_plan.load_plan(target), tmp_path / "journal")
    assert snapshot(root) == before and not (tmp_path / "journal").exists()


def test_previously_disconnected_report_becoming_connected_is_a_scope_change(project, tmp_path):
    root, _, _ = project
    added = add_report(root, binding={"byPath": {"path": "../../Models/Other.SemanticModel"}})
    target, _ = plan(tmp_path, root, delete("Spare"))
    write_json(added / "definition.pbir", {"datasetReference": {"byPath": {"path": "../../Models/Sales.SemanticModel"}}})
    before = snapshot(root)
    with pytest.raises(change_plan.PlanError, match="new plan"):
        change_plan.apply_plan(change_plan.load_plan(target), tmp_path / "journal")
    assert snapshot(root) == before and not (tmp_path / "journal").exists()


def test_legacy_metadata_only_plan_keeps_apply_compatibility(project, tmp_path):
    root, model, reports = project
    saved = change_plan.create_plan(model, list(reports.values()), [{"kind": "actions", "actions": [
        {"action": "hide", "table": "Sales", "name": "Spare", "item_type": "Measure"}]}], report_search_roots=[root])
    saved["coverage"].pop("report_selection")
    saved["digest"] = change_plan._seal(saved)
    before = snapshot(root)
    assert change_plan.apply_plan(saved, tmp_path / "journal")["ok"]
    assert change_plan.restore_plan(saved, tmp_path / "journal")["ok"]
    assert snapshot(root) == before
