"""Behavioral regressions from the independent workspace review; no Apply calls."""
import shutil
import subprocess
from pathlib import Path

import pytest

from semantic_model_cleaner.metadata_validation import validate_report_paths

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_workspace_controllers_and_scoped_reader():
    result = subprocess.run([shutil.which("node"), str(ROOT / "tests/js/workspace-review.cjs"), str(ROOT)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_coverage_retains_report_identity_and_empty_reports(tmp_path):
    reports = [tmp_path / folder / "Same.Report" for folder in ("A", "B", "Empty")]
    for report in reports:
        (report / "definition").mkdir(parents=True)
    valid = (ROOT / "tests/fixtures/schema-validation/page-valid.json").read_bytes()
    (reports[0] / "definition/page.json").write_bytes(valid)
    (reports[1] / "definition/page.json").write_text('{invalid', encoding="utf-8")
    (reports[1] / "definition/report.json").write_text('{}', encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    evidence = validate_report_paths(reports, workspace=tmp_path, include_report_identity=True)
    by_report = {row["reportPath"]: row for row in evidence["reports"]}
    assert len(by_report) == 3
    assert by_report[str(reports[0].resolve())]["counts"] == {"valid": 1, "invalid": 0, "not_validated": 0}
    assert by_report[str(reports[0].resolve())]["complete"]
    assert by_report[str(reports[1].resolve())]["counts"] == {"valid": 0, "invalid": 1, "not_validated": 1}
    assert not by_report[str(reports[1].resolve())]["complete"]
    assert by_report[str(reports[2].resolve())]["fileCount"] == 0
    assert not by_report[str(reports[2].resolve())]["complete"]
    assert {row["reportPath"] for row in evidence["files"]} == {str(p.resolve()) for p in reports[:2]}
    assert all(p.read_bytes() == data for p, data in before.items())
