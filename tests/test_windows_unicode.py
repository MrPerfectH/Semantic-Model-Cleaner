"""Exercise public entry points with Windows legacy encoding and redirected pipes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEXT = "Zażółć café 🚀"


def run_python(args, *, cwd, check=True):
    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252:strict",
               PYTHONCOERCECLOCALE="0", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, *args], cwd=cwd, env=env,
                            capture_output=True, timeout=45)
    if check:
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result


def run_cli(args, *, cwd, check=True):
    return run_python(["-m", "semantic_model_cleaner", *map(str, args)], cwd=cwd, check=check)


def project(tmp_path):
    root = tmp_path / TEXT
    model = root / "Modèle.SemanticModel"
    report = root / "Rapport.Report"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_bytes(b"table Sales\r\n\tmeasure Revenue = 1\r\n")
    (model / "definition" / "model.tmdl").write_text(
        "model Model\n\tref table Sales\n", encoding="utf-8")
    (report / "definition").mkdir(parents=True)
    (report / "definition" / "report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(json.dumps({
        "datasetReference": {"byPath": {"path": "../Modèle.SemanticModel"}}
    }), encoding="utf-8")
    return root, model, report


def snapshot(*roots):
    return {str(p): p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_unicode_reviewed_workflow_preserves_text_and_restores_bytes(tmp_path, encoding):
    root, model, report = project(tmp_path)
    before = snapshot(model, report)
    operations = root / "opérations.json"
    operation = {"kind": "actions", "actions": [{"action": "move_to_folder",
        "table": "Sales", "name": "Revenue", "item_type": "Measure", "folder": TEXT}]}
    operations.write_text(json.dumps([operation], ensure_ascii=False), encoding=encoding)
    plan = root / "révision.json"
    result = run_cli(["plan", root, "--operations", operations, "-o", plan], cwd=root)
    assert json.loads(result.stdout.decode("utf-8"))["ok"]
    saved = json.loads(plan.read_text(encoding="utf-8"))
    assert saved["operations"] == [operation]
    assert snapshot(model, report) == before
    diff = run_cli(["diff", plan], cwd=root).stdout.decode("utf-8")
    assert "displayFolder: " + TEXT in diff
    journal = root / "historique"
    for command in ("apply", "verify"):
        result = run_cli([command, plan, "--journal-dir", journal], cwd=root)
        assert json.loads(result.stdout.decode("utf-8"))["ok"]
    assert TEXT in (model / "definition/tables/Sales.tmdl").read_text(encoding="utf-8")
    result = run_cli(["history", "--journal-dir", journal], cwd=root)
    assert json.loads(result.stdout.decode("utf-8"))["receipts"]
    result = run_cli(["restore", plan, "--journal-dir", journal], cwd=root)
    assert json.loads(result.stdout.decode("utf-8"))["ok"]
    assert snapshot(model, report) == before


@pytest.mark.parametrize("content", [b'["\xff"]', '[]'.encode("utf-16")])
def test_malformed_encoding_is_actionable_and_writes_nothing(tmp_path, content):
    root, model, report = project(tmp_path)
    operations = root / "opérations.json"
    operations.write_bytes(content)
    before = snapshot(root)
    result = run_cli(["plan", root, "--operations", operations, "-o", root / "plan.json"],
                     cwd=root, check=False)
    assert result.returncode == 2
    error = json.loads(result.stderr.decode("utf-8"))["error"]
    assert "UTF-8" in error and "opérations.json" in error
    assert snapshot(root) == before


@pytest.mark.parametrize("module", ["webapp", "windows_launcher"])
def test_server_entrypoint_starts_with_redirected_legacy_streams(tmp_path, module):
    root, _, _ = project(tmp_path)
    # Replace only the long-running server/browser boundary; exercise main,
    # argument parsing, runtime configuration and the real startup banner.
    script = f"""
import sys
from unittest.mock import patch
from semantic_model_cleaner import {module} as entry
sys.argv = ['smc', {str(root)!r}]
with patch('flask.Flask.run'), patch('waitress.serve'), patch('threading.Thread.start'):
    entry.main()
print({TEXT!r}, file=sys.stderr)
"""
    result = run_python(["-c", script], cwd=root)
    assert str(root) in result.stdout.decode("utf-8")
    assert TEXT in result.stderr.decode("utf-8")


@pytest.mark.parametrize("entrypoint", [
    ["-m", "semantic_model_cleaner"],
    [str(ROOT / "scripts" / "analyze_model_usage.py")],
])
def test_cli_json_stdout_preserves_non_bmp_paths(tmp_path, entrypoint):
    root, _, _ = project(tmp_path)
    result = run_python([*entrypoint, str(root), "--format", "json"], cwd=root)
    output = result.stdout.decode("utf-8")
    assert TEXT in str(json.loads(output))


def test_subprocess_environment_disables_utf8_mode(tmp_path):
    result = run_python(["-c", "import locale, sys; "
                         "print(sys.flags.utf8_mode, sys.stdout.encoding, locale.getencoding())"],
                         cwd=tmp_path)
    mode, stdio, locale_encoding = result.stdout.decode("ascii").split()
    assert (mode, stdio) == ("0", "cp1252")
    if os.name == "nt" and locale_encoding.lower().replace("-", "") == "utf8":
        pytest.skip("Windows system locale is UTF-8; legacy locale verification needs a legacy locale host")
