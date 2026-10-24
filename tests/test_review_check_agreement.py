"""`smc review` and `smc check` reach the same verdict from the same policy and baseline."""
import json
import os
import subprocess
import sys

import pytest

from test_cli_insights import visual
from test_cli_path_selection import ROOT
from test_partial_report_scope import project  # noqa: F401  (fixture)


def code(tmp_path, args):
    result = subprocess.run([sys.executable, "-m", "semantic_model_cleaner", *map(str, args)], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), capture_output=True, timeout=40)
    payload = json.loads(result.stdout.decode("utf-8"))
    return result.returncode, payload


def both(tmp_path, root, *options):
    check, check_payload = code(tmp_path, ["check", root, *options])
    review, review_payload = code(tmp_path, ["review", root, *options, "--format", "json"])
    return (check, review), check_payload, review_payload


def test_review_uses_explicit_policy_like_check(project, tmp_path):
    root, model, reports = project
    (root / "custom-policy.json").write_text(json.dumps({"schema_version": "1.0", "decisions": [], "naming_rules": [],
        "ci_gate": {"rules": {"SMC004": "fail"}}}), encoding="utf-8")
    assert both(tmp_path, root)[0] == (0, 0)
    codes, check_payload, review_payload = both(tmp_path, root, "--policy", "custom-policy.json")
    assert codes == (1, 1)
    assert review_payload["policy"]["digest"] == check_payload["policy"]["digest"]


def test_review_uses_baseline_like_check(project, tmp_path):
    root, model, reports = project
    visual(reports["Ops"], "Broken", name="Missing")
    baseline = tmp_path / "b.json"
    assert both(tmp_path, root)[0] == (1, 1)
    assert code(tmp_path, ["check", root, "--write-baseline", baseline])[0] == 1
    codes, check_payload, review_payload = both(tmp_path, root, "--baseline", baseline)
    assert codes == (0, 0)
    assert review_payload["summary"] == check_payload["summary"]


@pytest.mark.parametrize("option, value", [("--policy", "missing.json"), ("--baseline", "missing.json"),
                                           ("--baseline", "bad.json")])
def test_review_rejects_invalid_policy_and_baseline_like_check(project, tmp_path, option, value):
    root, model, reports = project
    (tmp_path / "bad.json").write_text(json.dumps({"schema_version": "0"}), encoding="utf-8")
    codes, _, review_payload = both(tmp_path, root, option, tmp_path / value if option == "--baseline" else value)
    assert codes == (2, 2) and review_payload["ok"] is False


def test_capabilities_list_review_policy_and_baseline(tmp_path):
    _, payload = code(tmp_path, ["capabilities"])
    review = next(row for row in payload["commands"] if row["name"] == "review")
    assert {"--policy", "--baseline"} <= {option["flag"] for option in review["options"]}
