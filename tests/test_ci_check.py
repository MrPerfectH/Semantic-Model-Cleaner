"""CLI contract, deterministic findings, coverage and baseline behavior."""
import json
import shutil

import pytest

from semantic_model_cleaner import cli
from semantic_model_cleaner.ci import main, run_check


def project(root):
    model = root / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text('table Sales\n\tmeasure Broken = [Missing]\n\tcolumn Spare\n', encoding="utf-8")
    report = root / "R.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text('{}', encoding="utf-8")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}), encoding="utf-8")
    return model, report


def test_check_stable_relative_paths_and_fingerprints_across_checkouts(tmp_path):
    first = tmp_path / "first"
    project(first)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    code, output = run_check(first)
    code2, output2 = run_check(second)
    assert code == code2 == 1
    assert output == output2
    assert output["schema_version"] == "1.0"
    assert {f["rule_id"] for f in output["findings"]} == {"SMC001", "SMC004", "SMC012"}
    assert all(not f["path"].startswith('/') for f in output["findings"])


def test_baseline_keeps_findings_visible_and_cannot_hide_coverage(tmp_path):
    _, report = project(tmp_path)
    _, initial = run_check(tmp_path)
    baseline = {"schema_version": "1.0", "fingerprints": [f["fingerprint"] for f in initial["findings"]]}
    code, output = run_check(tmp_path, baseline=baseline)
    assert code == 0
    assert all(f["suppressed"] for f in output["findings"] if f["rule_id"] != "SMC012")
    assert all(not f["suppressed"] for f in output["findings"] if f["rule_id"] == "SMC012")
    (report / "definition/report.json").write_text('{invalid', encoding="utf-8")
    _, invalid = run_check(tmp_path)
    baseline["fingerprints"] += [f["fingerprint"] for f in invalid["findings"]]
    code, output = run_check(tmp_path, baseline=baseline)
    assert code == 1
    assert any(f["rule_id"] == "SMC002" and not f["suppressed"] for f in output["findings"])


def test_check_bound_report_scope_excludes_other_model(tmp_path):
    project(tmp_path)
    other = tmp_path / "Other.Report"
    other.mkdir()
    (other / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../Other.SemanticModel"}}}), encoding="utf-8")
    code, output = run_check(tmp_path)
    assert code == 1
    assert output["scope"]["reports"] == ["R.Report"]
    assert output["scope"]["bindings"][0] == {"path": "Other.Report", "status": "not_connected", "selected": False}


def test_unverified_discovered_binding_is_a_nonsuppressible_failure(tmp_path):
    project(tmp_path)
    (tmp_path / "Mystery.Report").mkdir()
    _, output = run_check(tmp_path)
    assert any(f["rule_id"] == "SMC008" for f in output["findings"])


def test_bad_inputs_are_exit_two(tmp_path):
    assert run_check(tmp_path)[0] == 2
    project(tmp_path)
    assert run_check(tmp_path, baseline=[])[0] == 2
    assert run_check(tmp_path, report_filters=["nonexistent"])[0] == 2


def test_cli_dispatch_json_and_baseline_write(tmp_path, capsys):
    project(tmp_path)
    baseline = tmp_path / "baseline.json"
    assert main([str(tmp_path), "--write-baseline", str(baseline)]) == 1
    assert json.loads(capsys.readouterr().out)["schema_version"] == "1.0"
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", str(tmp_path), "--baseline", str(baseline)])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_unsupported_metadata_is_visible_even_with_resolved_targets(tmp_path):
    model, _ = project(tmp_path)
    (model / "definition/tables/Time.tmdl").write_text(
        "table Time\n\tcalculationGroup\n\t\tcalculationItem Current = [Broken]\n", encoding="utf-8")
    _, output = run_check(tmp_path)
    metadata = [f for f in output["findings"] if f["rule_id"] == "SMC003"]
    assert len(metadata) == 1 and metadata[0]["severity"] == "warning"


def test_cli_plan_dispatch_propagates_exit_code(monkeypatch):
    import sys
    import types
    module = types.ModuleType("semantic_model_cleaner.plan_cli")
    module.main = lambda argv: 2
    monkeypatch.setitem(sys.modules, "semantic_model_cleaner.plan_cli", module)
    with pytest.raises(SystemExit) as exc:
        cli.main(["apply", "plan.json"])
    assert exc.value.code == 2


@pytest.mark.parametrize("destination", ["model", "report", "excluded_report", "symlink"])
def test_baseline_output_cannot_overwrite_artifact_metadata(tmp_path, capsys, destination):
    model, report = project(tmp_path)
    if destination == "model":
        target = model / "definition/tables/Sales.tmdl"
    elif destination == "excluded_report":
        excluded = tmp_path / "Unrelated.Report"
        excluded.mkdir()
        target = excluded / "definition.pbir"
        target.write_text(json.dumps({"datasetReference": {"byPath": {"path": "../Unrelated.SemanticModel"}}}))
    else:
        target = report / "definition/report.json"
    original = target.read_bytes()
    output = target
    if destination == "symlink":
        output = tmp_path / "baseline-link.json"
        output.symlink_to(target)
    assert main([str(tmp_path), "--write-baseline", str(output)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "outside" in payload["errors"][0]
    assert target.read_bytes() == original
