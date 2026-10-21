"""Public CLI journeys for one Semantic Model and its connected Reports."""
import json

import pytest

from test_cli_insights import visual as add_visual
from test_cli_path_selection import run
from test_plan_write_boundaries import project as make_project, snapshot


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Zażółć core project"
    model, report, operations = make_project(root)
    path = report / "definition/pages/P/visuals/V/visual.json"
    visual = json.loads(path.read_text(encoding="utf-8"))
    # The shared fixture includes a broken reference for repair tests; these
    # journeys introduce that failure explicitly when needed.
    visual["visual"]["query"]["queryState"]["Values"]["projections"].pop()
    path.write_text(json.dumps(visual), encoding="utf-8")
    return root, model, report, operations


def select(project):
    root, model, report, _ = project
    return [root, "--model-path", model.relative_to(root), "--report-path", report.relative_to(root)]


def create_plan(project, tmp_path, operation, expected=0):
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps([operation]), encoding="utf-8")
    target = tmp_path / "changes.plan.json"
    result = run(tmp_path, ["plan", *select(project), "--operations", operations, "-o", target,
                            "--format", "json"], expected=expected)
    return target, result


@pytest.mark.parametrize("kind", ["rename", "move", "promote", "clean_stale"])
def test_reviewed_cli_roundtrips_preserve_report_consumers(project, tmp_path, kind):
    root, model, report, operations = project
    if kind == "promote":
        add_visual(report, "LocalPage", name="Local")
    before = snapshot(root)
    operation = {"kind": kind, **operations[kind]}
    if kind == "clean_stale":
        discovery = run(tmp_path, ["clean-stale", *select(project), "--format", "json"], expected=1)
        fields = {"reportPath": "report_path", "artifactPath": "artifact_path", "sourcePath": "source_path",
                  "selectorValue": "selector_value", "staleKind": "stale_kind"}
        operation["entries"] = [{target: row[key] for key, target in fields.items()}
                                for row in discovery["candidates"]]
        assert operation["entries"]
    plan, _ = create_plan(project, tmp_path, operation)
    assert snapshot(root) == before
    diff = run(tmp_path, ["diff", plan, "--format", "json"])
    assert diff["changes"] and diff["diff"]
    assert run(tmp_path, ["verify", plan, "--format", "json"], expected=1)["state"] == "original"
    applied = run(tmp_path, ["apply", plan, "--format", "json"])
    assert applied["receipt"]["status"] == "applied"
    assert run(tmp_path, ["verify", plan, "--format", "json"])["state"] == "applied"
    if kind == "rename":
        usage = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Net Revenue", "--format", "json"])
        assert usage["report_used"] and usage["cleanup"] == "Blocked"
        visual = json.loads((report / "definition/pages/P/visuals/V/visual.json").read_text(encoding="utf-8"))
        assert visual["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Measure"]["Property"] == "Net Revenue"
    elif kind == "move":
        usage = run(tmp_path, ["usage", *select(project), "--table", "Measures", "--item", "Revenue", "--format", "json"])
        assert usage["report_used"]
    elif kind == "promote":
        source = model / "definition/tables/Sales.tmdl"
        assert "measure Local" in source.read_text(encoding="utf-8")
        extensions = json.loads((report / "definition/reportExtensions.json").read_text(encoding="utf-8"))
        assert not any(measure["name"] == "Local" for entity in extensions.get("entities", []) for measure in entity.get("measures", []))
        usage = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Local", "--source", "model", "--format", "json"])
        assert usage["report_used"] and usage["item"]["source"] == "model"
    else:
        run(tmp_path, ["clean-stale", *select(project), "--format", "json"])
        visual = json.loads((report / "definition/pages/P/visuals/V/visual.json").read_text(encoding="utf-8"))
        original_visual = json.loads(before["R.Report/definition/pages/P/visuals/V/visual.json"])
        assert visual["visual"]["query"] == original_visual["visual"]["query"]
        usage = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Revenue", "--format", "json"])
        assert usage["report_used"]
    checked = run(tmp_path, ["check", *select(project)])
    assert not any(row["severity"] == "error" for row in checked["findings"])
    run(tmp_path, ["restore", plan, "--format", "json"])
    assert snapshot(root) == before


def test_usage_cleanup_candidates_and_broken_report_reference_have_distinct_evidence(project, tmp_path):
    root, model, report, _ = project
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text(encoding="utf-8") + "\tmeasure Helper = [Revenue] + 1\n\tmeasure Spare = 1\n", encoding="utf-8")
    add_visual(report, "IndirectPage", name="Helper")
    before = snapshot(root)
    usage = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Revenue", "--format", "json"])
    assert {row["kind"] for row in usage["locations"]["items"]} == {"direct", "indirect"}
    assert any(item["name"] == "Helper" for row in usage["locations"]["items"] for item in row["via"])
    spare = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Spare", "--format", "json"])
    assert not spare["report_used"] and spare["cleanup"] == "Safe"
    assert not spare["scope"]["external_consumers_verified"]
    assert snapshot(root) == before
    add_visual(report, "BrokenPage", name="Missing")
    output = run(tmp_path, ["check", *select(project)], expected=1)
    broken = [row for row in output["findings"] if row["rule_id"] == "SMC006" and row["severity"] == "error"]
    assert broken and any("BrokenPage" in row["path"] for row in broken)


def test_incomplete_report_scan_downgrades_candidate_and_refuses_delete_plan(project, tmp_path):
    root, model, report, _ = project
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text(encoding="utf-8") + "\tmeasure Spare = 1\n", encoding="utf-8")
    (report / "definition/report.json").write_text("{broken", encoding="utf-8")
    before = snapshot(root)
    usage = run(tmp_path, ["usage", *select(project), "--table", "Sales", "--item", "Spare", "--format", "json"])
    assert not usage["report_used"] and usage["cleanup"] == "Review"
    assert not usage["scope"]["scan_complete"]
    plan, result = create_plan(project, tmp_path, {"kind": "actions", "actions": [{
        "action": "delete", "table": "Sales", "name": "Spare", "item_type": "Measure"}]}, expected=2)
    assert not result["ok"] and not plan.exists()
    assert snapshot(root) == before
