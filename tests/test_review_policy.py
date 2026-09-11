import json
from datetime import date
from pathlib import Path

import pytest

from semantic_model_cleaner import ci, cleanup_policy, review_policy as policy, policy_cli


@pytest.fixture
def project(tmp_path):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text("table Sales\n\tmeasure TotalRevenue = SUM(Sales[Amount])\n\tcolumn Amount\n\tcolumn Spare\n")
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text('{}')
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    return tmp_path, model, report


def finding(project, name="Spare"):
    root, model, report = project
    checked = policy.review_findings(root, model, [report])
    return checked, next(row for row in checked["findings"] if row["name"] == name)


def record(project, *, name="Spare", expires_on="2099-01-01", disposition="keep"):
    checked, row = finding(project, name)
    return policy.add_decision(project[0], row, checked["scope"], disposition=disposition,
                               reason="Required by a planned release", owner="Model team", expires_on=expires_on)


def test_decision_persists_with_accountability_and_suppresses_warning_only(project):
    saved = record(project)
    assert saved["decisions"][0]["owner"] == "Model team"
    assert policy.load_policy(project[0]) == saved
    _, row = finding(project)
    assert row["suppressed"] and row["review_status"] == "accepted"
    assert row["review_decision"]["reason"]
    removed = policy.remove_decision(project[0], saved["decisions"][0]["id"])
    assert removed["decisions"] == []
    assert not finding(project)[1]["suppressed"]


def test_expired_and_stale_decisions_do_not_suppress(project):
    record(project, expires_on="2000-01-01")
    assert finding(project)[1]["review_status"] == "expired"
    assert not finding(project)[1]["suppressed"]
    record(project)
    source = project[1] / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\n// subsequent edit\n")
    assert finding(project)[1]["review_status"] == "stale"
    assert not finding(project)[1]["suppressed"]


def test_scope_change_invalidates_decision(project):
    root, model, report = project
    record(project)
    second = root / "Second.Report"
    (second / "definition").mkdir(parents=True)
    (second / "definition/report.json").write_text('{}')
    (second / "definition.pbir").write_bytes((report / "definition.pbir").read_bytes())
    checked = policy.review_findings(root, model, [report, second])
    row = next(row for row in checked["findings"] if row["name"] == "Spare")
    assert row["review_status"] == "stale" and not row["suppressed"]


def test_decision_cannot_suppress_coverage_or_authorize_deletion(project):
    root, model, report = project
    (report / "definition/report.json").write_text('{invalid')
    checked = policy.review_findings(root, model, [report])
    row = next(row for row in checked["findings"] if row["rule_id"] == "SMC002")
    policy.add_decision(root, row, checked["scope"], disposition="accept", reason="Investigating", owner="Team", expires_on="2099-01-01")
    checked = policy.review_findings(root, model, [report])
    row = next(row for row in checked["findings"] if row["rule_id"] == "SMC002")
    assert not row["suppressed"] and row["review_status"] == "noted"
    assert not cleanup_policy.evaluate_deletion_policy(model, [report], [{"action": "delete", "table": "Sales", "name": "Spare", "item_type": "Column"}])["ok"]


def test_save_detects_concurrent_edit_and_rejects_artifact_paths(project):
    root, _, report = project
    first = policy.load_policy(root)
    saved = record(project)
    with pytest.raises(policy.PolicyError, match="changed"):
        policy.save_policy(root, first, expected_digest=first["digest"])
    assert policy.load_policy(root) == saved
    with pytest.raises(policy.PolicyError, match="expected_digest"):
        policy.save_policy(root, first)
    with pytest.raises(policy.PolicyError, match="outside"):
        policy.save_policy(root, first, report / "definition/report.json")
    assert (report / "definition/report.json").read_text() == '{}'


def test_canonical_finding_required_and_stale_client_rejected(project):
    checked, row = finding(project)
    row["fingerprint"] = "0" * 64
    with pytest.raises(policy.PolicyError, match="not present"):
        policy.add_decision(project[0], row, checked["scope"], disposition="keep", reason="x", owner="x", expires_on="2099-01-01")
    checked, row = finding(project)
    source = project[1] / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\n// changed\n")
    with pytest.raises(policy.PolicyError, match="changed"):
        policy.add_decision(project[0], row, checked["scope"], disposition="keep", reason="x", owner="x", expires_on="2099-01-01")


def test_schema_and_expiry_boundary(project):
    saved = record(project, expires_on="2030-01-01")
    checked, row = finding(project)
    row["suppressed"] = False
    assert policy.annotate_findings(project[0], [row], checked["scope"], saved, today=date(2030, 1, 1))[0]["suppressed"]
    assert not policy.annotate_findings(project[0], [row], checked["scope"], saved, today=date(2030, 1, 2))[0]["suppressed"]
    saved["decisions"][0]["owner"] = ""
    with pytest.raises(policy.PolicyError):
        policy.validate_policy(saved)


def naming_config(**rule):
    return {**policy.empty_policy(), "naming_rules": [{"id": "display", "item_type": "Measure", "case": "title", **rule}]}


def test_naming_preview_is_reviewable_and_preserves_inputs(project):
    root, model, report = project
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    result = policy.naming_preview(root, model, [report], naming_config())
    assert result["ok"] and result["plan"]["changes"]
    assert result["operations"][0]["measure_renames"] == [{"table": "Sales", "name": "TotalRevenue", "target_name": "Total Revenue"}]
    assert all(content == Path(path).read_bytes() for path, content in before.items())
    assert not (root / policy.POLICY_FILENAME).exists()


def test_naming_collisions_and_unstable_rules_are_blocked(project):
    source = project[1] / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tmeasure 'Total Revenue' = 1\n")
    result = policy.naming_preview(project[0], project[1], [project[2]], naming_config())
    assert not result["ok"] and result["plan"] is None and result["conflicts"]
    result = policy.naming_proposals(project[1], naming_config(case="preserve", find="Total", replace="Total Total"))
    assert not result["ok"]


def test_prefix_is_idempotent_and_naming_findings_join_ci(project):
    root, model, _ = project
    config = naming_config(case="preserve", prefix="m_")
    policy.save_policy(root, config)
    code, checked = ci.run_check(root)
    assert code == 0 and any(row["rule_id"] == "SMC009" for row in checked["findings"])
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text().replace("TotalRevenue", "m_TotalRevenue"))
    assert policy.naming_proposals(model, config)["proposals"] == []


def test_policy_cli_init_validate_add_and_remove(project, capsys):
    root, _, _ = project
    assert policy_cli.main(["policy", "init", str(root)]) == 0
    capsys.readouterr()
    _, row = finding(project)
    assert policy_cli.main(["policy", "add", str(root), "--finding", row["fingerprint"], "--disposition", "keep", "--reason", "Release plan", "--owner", "Team", "--expires-on", "2099-01-01"]) == 0
    saved = json.loads(capsys.readouterr().out)["policy"]
    assert policy_cli.main(["policy", "remove", str(root), "--id", saved["decisions"][0]["id"]]) == 0


def test_table_column_and_measure_rules_apply_through_existing_plan(project):
    from semantic_model_cleaner import analyzer, change_plan
    root, model, report = project
    visual = report / "definition/pages/P/visuals/V/visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({"visual": {"query": {"Measure": {
        "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "TotalRevenue"}}}}))
    config = {**policy.empty_policy(), "naming_rules": [
        {"id": "tables", "item_type": "Table", "prefix": "f_"},
        {"id": "measures", "item_type": "Measure", "prefix": "m_"},
        {"id": "columns", "item_type": "Column", "prefix": "c_"},
    ]}
    preview = policy.naming_preview(root, model, [report], config)
    assert preview["ok"] and preview["plan"]
    assert change_plan.apply_plan(preview["plan"], root / "journals")["ok"]
    analyzed = analyzer.analyze(root, model_paths=[model], report_paths=[report])
    revenue = next(row for row in analyzed["items"] if row["item"].name == "m_TotalRevenue")
    assert revenue["status"] == "USED" and revenue["item"].table == "f_Sales"
    assert "c_Amount" in revenue["item"].dax_body
    assert not policy.naming_proposals(model, config)["proposals"]


def test_invalid_policy_fails_ci_and_cli_naming_output_is_contained(project, capsys):
    root, model, report = project
    (root / policy.POLICY_FILENAME).write_text('{invalid')
    assert ci.run_check(root)[0] == 2
    (root / policy.POLICY_FILENAME).unlink()
    policy.save_policy(root, naming_config())
    target = report / "definition/report.json"
    before = target.read_bytes()
    assert policy_cli.main(["naming", "preview", str(root), "-o", str(target)]) == 2
    assert target.read_bytes() == before
    assert "outside" in json.loads(capsys.readouterr().out)["error"]


def test_explicit_missing_policy_is_not_silently_ignored(project, capsys):
    root, _, _ = project
    assert ci.main([str(root), "--policy", "missing.json"]) == 2
    assert "does not exist" in json.loads(capsys.readouterr().out)["errors"][0]
    assert policy_cli.main(["policy", "validate", str(root)]) == 2
    assert "does not exist" in json.loads(capsys.readouterr().out)["error"]
