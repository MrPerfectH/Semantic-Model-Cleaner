"""Plan and CI baseline exports share the ordinary export alias boundary."""
import json

import pytest

from semantic_model_cleaner import ci, plan_cli
import test_analysis_exports as fixtures
from test_analysis_exports import make_directory_alias, snapshot


project = fixtures.project


@pytest.fixture
def operations(tmp_path):
    path = tmp_path / "operations.json"
    path.write_text(json.dumps([{"kind": "actions", "actions": [{
        "action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"
    }]}]), encoding="utf-8")
    return path


def export(command, project, operations, target):
    root, model, report, *_ = project
    if command == "plan":
        return plan_cli.main(["plan", str(root), "--model", str(model), "--report", str(report),
                              "--operations", str(operations), "-o", str(target)])
    return ci.main([str(root), "--model", str(model), "--report", "Overview",
                    "--write-baseline", str(target)])


@pytest.mark.parametrize("command", ["plan", "baseline"])
@pytest.mark.parametrize("source_index", [1, 2, 3, 4])
def test_hard_link_to_selected_or_excluded_metadata_rejected(
    project, operations, tmp_path, capsys, command, source_index,
):
    artifact = project[source_index]
    source = artifact / ("definition/tables/Sales.tmdl" if source_index in (1, 3)
                         else "definition/report.json")
    target = tmp_path / "external.json"
    try:
        target.hardlink_to(source)
    except OSError as exc:
        pytest.skip(f"Hard links unavailable: {exc}")
    before = snapshot(tmp_path)
    assert export(command, project, operations, target) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err if command == "plan" else captured.out)
    assert "hard link" in str(payload)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("command", ["plan", "baseline"])
@pytest.mark.parametrize("destination", ["selected", "excluded", "named", "junction"])
def test_nested_artifact_destinations_rejected_before_mkdir(
    project, operations, tmp_path, command, destination,
):
    if destination == "selected":
        target = project[1] / "new/nested/plan.json"
    elif destination == "excluded":
        target = project[4] / "new/nested/plan.json"
    elif destination == "named":
        target = tmp_path / "Outside.Report/new/nested/plan.json"
    else:
        alias = tmp_path / "alias"
        make_directory_alias(alias, project[1])
        target = alias / "new/nested/plan.json"
    before = snapshot(tmp_path)
    assert export(command, project, operations, target) == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("command", ["plan", "baseline"])
def test_discovered_excluded_alias_protects_unnamed_target(project, operations, tmp_path, command):
    storage = tmp_path / "metadata storage"
    storage.mkdir()
    target = storage / "metadata.json"
    target.write_text("original", encoding="utf-8")
    make_directory_alias(project[0] / "Another.Report", storage)
    before = snapshot(tmp_path)
    assert export(command, project, operations, target) == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("alias", [False, True])
def test_plan_cannot_replace_operations_input(project, operations, tmp_path, alias):
    target = operations
    if alias:
        target = tmp_path / "operations-alias.json"
        try:
            target.hardlink_to(operations)
        except OSError as exc:
            pytest.skip(f"Hard links unavailable: {exc}")
    before = snapshot(tmp_path)
    assert export("plan", project, operations, target) == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("command", ["plan", "baseline"])
def test_external_existing_output_remains_supported(project, operations, tmp_path, command):
    target = tmp_path / "révision.json"
    target.write_text("previous export", encoding="utf-8")
    before = snapshot(project[0])
    assert export(command, project, operations, target) in (0, 1)
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"]
    assert snapshot(project[0]) == before


def test_plan_creates_external_missing_parent_directories(project, operations, tmp_path):
    target = tmp_path / "new external/nested/plan.json"
    before = snapshot(project[0])
    assert export("plan", project, operations, target) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["digest"]
    assert snapshot(project[0]) == before
