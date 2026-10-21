"""Exact artifact selection through the public CLI, independent of terminal CWD."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Zażółć project"
    model = root / "Models/Sales.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text("table Sales\n\tmeasure Revenue = 1\n\tcolumn Spare\n", encoding="utf-8")
    reports = []
    for name in ("Executive", "Executive Archive"):
        report = root / "Reports" / (name + ".Report")
        (report / "definition").mkdir(parents=True)
        (report / "definition/report.json").write_text("{}", encoding="utf-8")
        (report / "definition.pbir").write_text(json.dumps({"datasetReference": {
            "byPath": {"path": "../../Models/Sales.SemanticModel"}}}), encoding="utf-8")
        reports.append(report)
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps([{"kind": "actions", "actions": [{
        "action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"}]}]), encoding="utf-8")
    return root, model, reports, operations


def run(tmp_path, args, expected=0):
    result = subprocess.run([sys.executable, "-m", "semantic_model_cleaner", *map(str, args)],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                              SMC_USER_DIR=str(tmp_path / "state")),
        capture_output=True, timeout=30)
    assert result.returncode == expected, result.stderr.decode("utf-8") + result.stdout.decode("utf-8")
    return json.loads(result.stdout.decode("utf-8"))


def invocation(command, root, operations, tmp_path):
    args = ([command] if command else []) + (["preview"] if command == "naming" else []) + [root]
    if command == "plan":
        args += ["--operations", operations, "-o", tmp_path / "review/plan.json"]
    if command != "naming":
        args += ["--format", "json"]
    return args


@pytest.mark.parametrize("command", ["", "check", "items", "usage", "summary", "review", "cleanup-groups", "plan", "clean-stale", "naming"])
@pytest.mark.parametrize("absolute", [False, True])
def test_canonical_paths_select_one_exact_report_outside_project(project, tmp_path, command, absolute):
    root, model, reports, operations = project
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    args = invocation(command, root, operations, tmp_path)
    args += ["--model-path", model if absolute else model.relative_to(root),
             "--report-path", reports[0] if absolute else reports[0].relative_to(root)]
    if command == "usage":
        args += ["--table", "Sales", "--item", "Revenue"]
    payload = run(tmp_path, args)
    assert payload.get("ok", True)
    if command in {"check", "items", "usage", "summary", "review", "cleanup-groups"}:
        assert payload["scope"]["reports"] == [reports[0].relative_to(root).as_posix()]
    elif command == "":
        assert len(payload["reportBinding"]["selected"]) == 1
    elif command == "plan":
        saved = json.loads((tmp_path / "review/plan.json").read_text(encoding="utf-8"))
        assert list(saved["scope"].values()) == [str(model), str(reports[0])]
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("command", ["", "check", "items", "plan", "clean-stale", "naming"])
@pytest.mark.parametrize("failure", ["missing", "empty-model", "unbound", "mixed-model", "mixed-report"])
def test_canonical_selection_never_falls_back_or_bypasses_binding(project, tmp_path, command, failure):
    root, model, reports, operations = project
    args = invocation(command, root, operations, tmp_path)
    args += ["--model-path", model.relative_to(root), "--report-path", reports[0].relative_to(root)]
    if failure == "missing":
        args[-1] = "Reports/Missing.Report"
    elif failure == "empty-model":
        args[args.index("--model-path") + 1] = ""
    elif failure == "unbound":
        (reports[0] / "definition.pbir").write_text(json.dumps({"datasetReference": {
            "byPath": {"path": "../../Models/Other.SemanticModel"}}}), encoding="utf-8")
    elif failure == "mixed-model":
        args += ["--model", "Sales"]
    else:
        args += ["--report", "Executive"]
    payload = run(tmp_path, args, expected=2)
    assert payload.get("ok", False) is False
    assert not (tmp_path / "review/plan.json").exists()


def test_repeated_paths_and_legacy_filters_have_distinct_selection(project, tmp_path):
    root, model, reports, _ = project
    legacy = run(tmp_path, ["check", root, "--report", "Executive"])
    exact = run(tmp_path, ["check", root, "--model-path", model.relative_to(root),
                           "--report-path", reports[0].relative_to(root)])
    both = run(tmp_path, ["check", root, "--report-path", reports[0], "--report-path", reports[1],
                          "--report-path", reports[0]])
    assert len(legacy["scope"]["reports"]) == 2
    assert len(exact["scope"]["reports"]) == 1
    assert both["scope"]["reports"] == legacy["scope"]["reports"]
    assert not exact["scope"]["selection_complete"]


def test_policy_add_and_naming_use_canonical_selection(project, tmp_path):
    root, model, reports, _ = project
    selectors = ["--model-path", model.relative_to(root), "--report-path", reports[0].relative_to(root)]
    findings = run(tmp_path, ["check", root, *selectors])
    finding = next(row for row in findings["findings"] if row["rule_id"] == "SMC004")
    result = run(tmp_path, ["policy", "add", root, *selectors, "--finding", finding["fingerprint"],
        "--disposition", "keep", "--reason", "Planned release", "--owner", "Model team", "--expires-on", "2099-01-01"])
    assert result["ok"]
    checked = run(tmp_path, ["check", root, *selectors])
    assert any(row.get("review_status") == "accepted" for row in checked["findings"])


def test_model_only_conflict_and_capability_discovery(project, tmp_path):
    root, model, reports, _ = project
    args = ["items", root, "--model-path", model, "--model-only", "--format", "json"]
    assert run(tmp_path, args)["scope"]["report_usage_checked"] is False
    assert not run(tmp_path, [*args, "--report-path", reports[0]], expected=2)["ok"]
    capabilities = run(tmp_path, ["capabilities"])
    assert capabilities["artifact_selection"]["path_base"] == "PROJECT"
    for command in capabilities["commands"]:
        if command["name"] != "capabilities":
            assert {"--model-path", "--report-path"} <= {option["flag"] for option in command["options"]}
