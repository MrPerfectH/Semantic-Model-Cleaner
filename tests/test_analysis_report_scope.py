"""The analysis command applies the same Safe -> Review rule as check, items and usage."""
import os
import subprocess
import sys

import pytest

from test_cli_insights import write_json
from test_cli_path_selection import ROOT, run
from test_partial_report_scope import project as scope_project

project = scope_project


def markdown(tmp_path, args):
    result = subprocess.run([sys.executable, "-m", "semantic_model_cleaner", *map(str, args)], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    return result.stdout.decode("utf-8")


def analysis_item(payload, name):
    return next(row for row in payload["items"] if row["table"] == "Sales" and row["name"] == name)


@pytest.mark.parametrize("selectors", [["--report-path", "Reports/Exec.Report"], ["--report", "Exec"]])
def test_analysis_downgrades_safe_to_review_when_connected_reports_are_not_selected(project, tmp_path, selectors):
    root, model, reports = project
    payload = run(tmp_path, [root, *selectors, "--format", "json"])
    ops = analysis_item(payload, "OpsOnly")
    assert ops["usageStatus"] == "NOT USED" and ops["removalRisk"] == "Review"
    assert any(row["id"] == "report_scan:not_selected" and "Ops" in row["unchecked"]
               for row in payload["analysisLimitations"])
    usage = run(tmp_path, ["usage", root, "--report-path", "Reports/Exec.Report", "--table", "Sales", "--item", "OpsOnly", "--format", "json"])
    assert usage["cleanup"] == "Review"


@pytest.mark.parametrize("output", ["unused", "full"])
def test_analysis_markdown_shows_review_for_narrowed_scope(project, tmp_path, output):
    root, model, reports = project
    text = markdown(tmp_path, [root, "--report-path", "Reports/Exec.Report", "--format", output])
    row = next(line for line in text.splitlines() if "| OpsOnly |" in line)
    assert row.rstrip().endswith("| Review |")
    assert "| Safe |" not in text
    assert "not selected" in text


def test_analysis_downgrades_safe_to_review_for_unverified_bindings(project, tmp_path):
    root, model, reports = project
    write_json(reports["Ops"] / "definition.pbir", {"datasetReference": {"byConnection": {"connectionString": "Data Source=x"}}})
    payload = run(tmp_path, [root, "--format", "json"])
    assert analysis_item(payload, "Spare")["removalRisk"] == "Review"
    assert any(row["id"] == "report_scan:unverified_binding" and "Ops" in row["unchecked"]
               for row in payload["analysisLimitations"])


def test_analysis_keeps_safe_when_every_connected_report_is_selected(project, tmp_path):
    root, model, reports = project
    payload = run(tmp_path, [root, "--format", "json"])
    assert analysis_item(payload, "Spare")["removalRisk"] == "Safe"
