"""Markdown is an escaped, bounded companion to the unchanged JSON/check result."""
import json

import pytest

from semantic_model_cleaner.ci_summary import render_summary
from test_ci_check import project as make_project
from test_cli_path_selection import run


@pytest.mark.parametrize("state,exit_code", [("findings", 1), ("pass", 0), ("missing", 2), ("bad-policy", 2)])
def test_summary_preserves_json_exit_and_input_bytes(tmp_path, state, exit_code):
    root = tmp_path / "project"
    model, _ = make_project(root)
    if state == "pass":
        (model / "definition/tables/Sales.tmdl").write_text("table Sales\n\tmeasure Revenue = 1\n", encoding="utf-8")
    if state == "bad-policy":
        (root / ".smc-policy.json").write_text("{bad", encoding="utf-8")
    selected = root / "absent" if state == "missing" else root
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plain = run(tmp_path, ["check", selected], expected=exit_code)
    target = tmp_path / "findings.md"
    result = run(tmp_path, ["check", selected, "--summary-output", target], expected=exit_code)
    assert plain == result
    markdown = target.read_text(encoding="utf-8")
    assert "exit " + str(exit_code) in markdown
    assert "External consumers were not verified" in markdown
    assert "## Report Health" in markdown and "## Analysis Limitations" in markdown
    if state == "findings":
        assert "SMC001" in markdown and "BLOCKING" in markdown
    if exit_code == 2:
        assert "Input or execution failure" in markdown
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("destination", ["model", "report", "excluded-report", "policy", "custom-policy", "baseline", "baseline-output", "symlink", "hardlink"])
def test_summary_cannot_overwrite_artifacts_or_policy_and_baselines(tmp_path, destination):
    root = tmp_path / "project"
    model, report = make_project(root)
    policy = root / ".smc-policy.json"
    policy.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"schema_version":"1.0","fingerprints":[]}', encoding="utf-8")
    options = []
    if destination == "model":
        target = model / "definition/tables/Sales.tmdl"
    elif destination == "report":
        target = report / "definition/report.json"
    elif destination == "excluded-report":
        target = root / "Other.Report/definition/report.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")
    elif destination == "policy":
        target = policy
    elif destination == "custom-policy":
        target = root / "custom.json"
        target.write_bytes(policy.read_bytes())
        options += ["--policy", target.name]
    elif destination in {"baseline", "baseline-output"}:
        target = baseline
        options += ["--baseline" if destination == "baseline" else "--write-baseline", baseline]
    else:
        target = tmp_path / "alias.md"
        source = report / "definition/report.json"
        try:
            if destination == "symlink":
                target.symlink_to(source)
            else:
                target.hardlink_to(source)
        except OSError as exc:
            pytest.skip(str(exc))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run(tmp_path, ["check", root, *options, "--summary-output", target], expected=2)
    assert result["errors"]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_summary_escapes_metadata_bounds_findings_and_retains_decisions():
    findings = [{"rule_id": "SMC004", "severity": "warning", "fingerprint": str(n),
        "table": "<script>alert(1)</script>", "name": "[click](https://evil)\n# heading",
        "message": "*bold* | cell " + "x" * 2000, "path": "a`b.tmdl", "location": "line:1",
        "suppressed": True, "gate": {"blocking": False, "reason": "Accepted"},
        "review_status": "accepted", "review_decision": {"owner": "Team", "reason": "Release", "expires_on": "2099-01-01"}}
        for n in range(205)]
    payload = {"findings": findings, "scope": {"reports": ["Report " + str(n) for n in range(105)],
        "bindings": [{"selected": False, "path": "External.Report", "status": "remote", "message": "Unverified"}]},
        "errors": [], "summary": {"finding_count": 205, "suppressed_count": 205}}
    markdown = render_summary(payload, 0)
    assert "<script>" not in markdown and "[click](https://evil)" not in markdown
    assert "&lt;script&gt;" in markdown and "\\[click\\]" in markdown
    assert "5 additional findings omitted" in markdown and "5 additional entries omitted" in markdown
    assert markdown.count("- SMC004") == 200
    assert "truncated" in markdown and "suppressed" in markdown
    assert "accepted; Team; Release; 2099" in markdown
    assert "External\\.Report" in markdown and "Unverified" in markdown


def test_policy_requirements_and_suppression_visible_in_markdown(tmp_path):
    root = tmp_path / "project"
    model, _ = make_project(root)
    (model / "definition/tables/Sales.tmdl").write_text("table Sales\n\tmeasure Spare = 1\n", encoding="utf-8")
    (root / ".smc-policy.json").write_text(json.dumps({"schema_version": "1.0", "ci_gate": {
        "require_complete_schema": True}}), encoding="utf-8")
    original = run(tmp_path, ["check", root], expected=1)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"schema_version": "1.0", "fingerprints": [
        row["fingerprint"] for row in original["findings"] if row["rule_id"] == "SMC004"]}), encoding="utf-8")
    target = tmp_path / "summary.md"
    output = run(tmp_path, ["check", root, "--baseline", baseline, "--summary-output", target], expected=1)
    assert output["summary"]["suppressed_count"] > 0
    markdown = target.read_text(encoding="utf-8")
    assert "require\\_complete\\_schema" in markdown and "BLOCKING" in markdown
    assert "SMC004 (warning; suppressed)" in markdown
