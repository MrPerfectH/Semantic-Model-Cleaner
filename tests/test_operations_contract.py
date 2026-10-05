import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from semantic_model_cleaner import __version__, change_plan
from semantic_model_cleaner.operations_contract import parse_operations, schema
from test_cli_contract import envelope, project as demo_project, run

project = demo_project


EXAMPLE = Path(__file__).parents[1] / "docs/cli/examples/agent-folder.json"


def test_discovery_and_standalone_schema(tmp_path):
    capabilities = envelope(run(["capabilities"], tmp_path), "capabilities")
    assert capabilities["tool_version"] == __version__
    assert set(capabilities["operations"]) == {
        "actions", "rename", "move", "promote", "dax", "clean_stale", "report_issues", "report_repair"}
    result = run(["operations-schema"], tmp_path)
    assert result.returncode == 0
    contract = json.loads(result.stdout)
    Draft202012Validator.check_schema(contract)
    assert contract == schema()
    envelope(run(["capabilities", "--unknown"], tmp_path), "capabilities", code=2)


def test_published_example_roundtrip_and_stale_refusal(project, tmp_path):
    root, model, operations = project
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    Draft202012Validator(schema()).validate(raw)
    operations.write_text(json.dumps(raw), encoding="utf-8")
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = tmp_path / "reviewed.json"
    envelope(run(["plan", root, "--operations", operations, "-o", plan, "--format", "json"], tmp_path), "plan")
    assert all(p.read_bytes() == value for p, value in original.items())
    assert "Reviewed metrics" in envelope(run(["diff", plan, "--format", "json"], tmp_path), "diff")["diff"]
    for command in ("apply", "verify", "restore"):
        assert envelope(run([command, plan, "--format", "json"], tmp_path), command)["ok"]
    assert all(p.read_bytes() == value for p, value in original.items())
    envelope(run(["plan", root, "--operations", operations, "-o", plan, "--format", "json"], tmp_path), "plan")
    source = next(model.rglob("*.tmdl"))
    source.write_bytes(source.read_bytes() + b"\n// later edit\n")
    changed = {p: p.read_bytes() for p in original}
    error = envelope(run(["apply", plan, "--format", "json"], tmp_path), "apply", code=2)
    assert "Stale" in error["error"]
    assert all(p.read_bytes() == value for p, value in changed.items())


@pytest.mark.parametrize("operation", [
    {"kind": "rename", "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Reviewed Revenue"}]},
    {"kind": "move", "moves": [{"table": "Sales", "name": "Revenue", "target_table": "Orders"}]},
    {"kind": "dax", "table": "Sales", "name": "Revenue", "item_type": "Measure", "dax_expression": "42"},
])
def test_versioned_model_operations_stage_without_writes(project, operation):
    root, model, _ = project
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    raw = {"schema_version": "1.0", "operations": [operation]}
    Draft202012Validator(schema()).validate(raw)
    plan = change_plan.create_plan(model, list(root.rglob("*.Report")), parse_operations(raw))
    assert plan["changes"]
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.update(schema_version="2.0"),
    lambda raw: raw.update(auto_apply=True),
    lambda raw: raw.update(operations=[]),
    lambda raw: raw["operations"][0].update(kind="shell"),
    lambda raw: raw["operations"][0].update(kind=[]),
    lambda raw: raw["operations"][0]["actions"][0].update(floder="typo"),
])
def test_invalid_requests_fail_before_any_plan_or_source_write(project, tmp_path, mutation):
    root, _, operations = project
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    mutation(raw)
    assert not Draft202012Validator(schema()).is_valid(raw)
    operations.write_text(json.dumps(raw), encoding="utf-8")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    output = tmp_path / "rejected.json"
    envelope(run(["plan", root, "--operations", operations, "-o", output, "--format", "json"], tmp_path), "plan", code=2)
    assert not output.exists()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_legacy_input_compatibility():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    operations = copy.deepcopy(raw["operations"])
    assert parse_operations(operations) == operations
    assert parse_operations({"operations": operations}) == operations


@pytest.mark.parametrize("kind", ["promote", "report_repair", "clean_stale", "report_issues"])
def test_versioned_report_operations_roundtrip(tmp_path, kind):
    from test_plan_write_boundaries import project as report_project, snapshot
    model, report, operations = report_project(tmp_path)
    before = snapshot(tmp_path)
    raw = {"schema_version": "1.0", "operations": [{"kind": kind, **operations[kind]}]}
    Draft202012Validator(schema()).validate(raw)
    plan = change_plan.create_plan(model, [report], parse_operations(raw))
    assert plan["changes"] and snapshot(tmp_path) == before
    journal = tmp_path.parent / (tmp_path.name + "-journal")
    assert change_plan.apply_plan(plan, journal)["ok"]
    assert change_plan.verify_plan(plan)["state"] == "applied"
    assert change_plan.restore_plan(plan, journal)["ok"]
    assert snapshot(tmp_path) == before
