"""Public CLI contracts tested as captured subprocess bytes, including aliases."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from semantic_model_cleaner import __version__, change_plan


ROOT = Path(__file__).resolve().parents[1]


def run(args, tmp_path, entrypoint=None):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="0",
               PYTHONIOENCODING="cp1252:strict", SMC_USER_DIR=str(tmp_path / "state"))
    return subprocess.run([*(entrypoint or [sys.executable, "-m", "semantic_model_cleaner"]),
                           *map(str, args)], cwd=tmp_path, env=env,
                          capture_output=True, timeout=60)


def envelope(result, command, code=0):
    assert result.returncode == code, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == command
    if code == 2:
        assert payload["ok"] is False and payload["errors"]
        assert b"Traceback" not in result.stderr
    return payload


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Zażółć project"
    shutil.copytree(ROOT / "src/semantic_model_cleaner/demo_workspace", root)
    model = next(root.rglob("*.SemanticModel"))
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps([{"kind": "actions", "actions": [{
        "action": "move_to_folder", "table": "Sales", "name": "Revenue",
        "item_type": "Measure", "folder": "Zażółć 🚀"
    }]}], ensure_ascii=False), encoding="utf-8")
    return root, model, operations


@pytest.mark.parametrize("alias", ["module", "smc", "semantic-model-cleaner"])
def test_help_and_version_for_public_entrypoints(tmp_path, alias):
    entrypoint = None
    if alias != "module":
        launcher = Path(sys.executable).parent / (alias + (".exe" if os.name == "nt" else ""))
        if not launcher.is_file():
            pytest.skip("Installed console alias unavailable; install package to exercise aliases")
        entrypoint = [str(launcher)]
    result = run(["--version"], tmp_path, entrypoint)
    assert result.returncode == 0 and not result.stderr
    assert result.stdout.decode("utf-8").strip() == f"Semantic Model Cleaner {__version__}"
    result = run(["--help"], tmp_path, entrypoint)
    assert result.returncode == 0
    help_text = result.stdout.decode("utf-8")
    for command in ("check", "clean-stale", "plan", "diff", "apply", "verify", "history",
                    "restore", "recover-lock", "policy", "naming"):
        assert f"smc {command}" in help_text
    assert "FILTERS" in help_text and "relative to PROJECT" in help_text and "CWD" in help_text


@pytest.mark.parametrize("args,command", [
    (["missing", "--format", "json"], "analyze"),
    (["--format=json", "--unknown"], "analyze"),
    (["check", "missing"], "check"),
    (["check", "--model"], "check"),
    (["check", "--format", "invalid"], "check"),
    (["plan", "--format", "json"], "plan"),
    (["diff", "missing.json", "--format", "json"], "diff"),
    (["apply", "missing.json", "--format", "json"], "apply"),
    (["restore", "--format", "json"], "restore"),
])
def test_machine_input_and_argument_errors_are_stdout_envelopes(tmp_path, args, command):
    envelope(run(args, tmp_path), command, code=2)


def test_analysis_success_file_receipt_and_protected_output(project, tmp_path):
    root, model, _ = project
    payload = envelope(run([root, "--format", "json"], tmp_path), "analyze")
    assert payload["items"] and payload["reportBinding"]["selected"]
    output = tmp_path / "analysis.json"
    receipt = envelope(run([root, "--format", "json", "-o", output], tmp_path), "analyze")
    assert receipt["output_file"] == str(output)
    assert json.loads(output.read_text(encoding="utf-8"))["summary"] == payload["summary"]
    source = next(model.rglob("*.tmdl"))
    before = source.read_bytes()
    error = envelope(run([root, "--format", "json", "-o", source], tmp_path), "analyze", code=2)
    assert "outside" in error["errors"][0]
    assert source.read_bytes() == before


def test_no_eligible_reports_reports_scope_error(project, tmp_path):
    root, _, operations = project
    for binding in root.rglob("definition.pbir"):
        binding.write_text("{}", encoding="utf-8")
    analysis = envelope(run([root, "--format", "json"], tmp_path), "analyze", code=2)
    assert "No matching connected" in analysis["errors"][0]
    check = envelope(run(["check", root], tmp_path), "check", code=2)
    assert check["scope"]["bindings"] and check["scope"]["selected_report_count"] == 0
    plan = envelope(run(["plan", root, "--operations", operations, "-o", "plan.json",
                         "--format", "json"], tmp_path), "plan", code=2)
    assert plan["reportBinding"]["excluded"]


def test_synthetic_reviewed_machine_workflow_and_legacy_diff(project, tmp_path):
    root, model, operations = project
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    checked = run(["check", root], tmp_path)
    check = envelope(checked, "check", code=checked.returncode)
    assert checked.returncode in (0, 1) and check["scope"]["reports"]
    plan_path = tmp_path / "review/plan.json"
    prepared = envelope(run(["plan", root, "--operations", operations, "-o", plan_path,
                             "--format", "json"], tmp_path), "plan")
    saved = change_plan.load_plan(plan_path)
    assert saved["id"] == prepared["id"] and "command" not in saved
    preview = envelope(run(["diff", plan_path, "--format", "json"], tmp_path), "diff")
    assert "Zażółć 🚀" in preview["diff"] and preview["changes"]
    legacy = run(["diff", plan_path], tmp_path)
    assert legacy.returncode == 0
    # Legacy text stdout still follows the platform newline translation.
    assert legacy.stdout.decode("utf-8").replace("\r", "").strip() == preview["diff"].replace("\r", "").strip()
    drift = envelope(run(["verify", plan_path, "--format", "json"], tmp_path), "verify", code=1)
    assert drift["ok"] is False and drift["state"] == "original" and drift["changed_since_plan"]
    for command in ("apply", "verify", "history", "restore"):
        args = [command, "--format", "json"] if command == "history" else [command, plan_path, "--format", "json"]
        envelope(run(args, tmp_path), command)
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    # Stale-plan refusal preserves subsequent edits and returns structured input failure.
    envelope(run(["plan", root, "--operations", operations, "-o", plan_path,
                  "--format", "json"], tmp_path), "plan")
    source = next(model.rglob("*.tmdl"))
    source.write_bytes(source.read_bytes() + b"\n// later edit\n")
    after = source.read_bytes()
    stale = envelope(run(["apply", plan_path, "--format", "json"], tmp_path), "apply", code=2)
    assert "Stale" in stale["errors"][0] and source.read_bytes() == after


def test_legacy_plan_error_stays_on_stderr(tmp_path):
    result = run(["diff", "missing.json"], tmp_path)
    assert result.returncode == 2 and not result.stdout
    assert json.loads(result.stderr.decode("utf-8"))["ok"] is False


def test_analysis_runtime_failure_remains_parseable(project, tmp_path):
    root, _, _ = project
    script = """
import sys
from semantic_model_cleaner import analyzer, cli
def fail(*args, **kwargs):
    raise RuntimeError('Cannot read café 🚀')
analyzer.analyze = fail
cli.main(sys.argv[1:])
"""
    result = run([root, "--format", "json"], tmp_path,
                 entrypoint=[sys.executable, "-c", script])
    assert envelope(result, "analyze", code=2)["errors"] == ["Cannot read café 🚀"]
