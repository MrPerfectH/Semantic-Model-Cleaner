"""Repository gates keep finding evidence, review decisions and safety separate."""
import json

import pytest

from semantic_model_cleaner import ci, review_policy
from test_ci_check import project as make_project
from test_cli_path_selection import run


@pytest.fixture
def project(tmp_path):
    model, report = make_project(tmp_path / "project")
    source = model / "definition/tables/Sales.tmdl"
    source.write_text("table Sales\n\tmeasure totalRevenue = 1\n\tcolumn Spare\n", encoding="utf-8")
    return model.parent, model, report


def policy(gate):
    return {"schema_version": "1.0", "ci_gate": gate, "naming_rules": [
        {"id": "measure-case", "item_type": "Measure", "case": "title"}]}


def test_naming_can_block_while_unused_is_advisory_and_cli_agrees(project, tmp_path):
    root, model, report = project
    settings = policy({"rules": {"SMC009": "fail", "SMC004": "advisory"}})
    (root / ".smc-policy.json").write_text(json.dumps(settings), encoding="utf-8")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    args = [root, "--model-path", model.name, "--report-path", report.name, "--format", "json"]
    checked = run(tmp_path, ["check", *args], expected=1)
    reviewed = run(tmp_path, ["review", *args, "--all"], expected=1)
    assert checked["gate"] == reviewed["gate"]
    assert checked["findings"] == sorted(reviewed["findings"]["items"], key=lambda f: (f["rule_id"], f["path"], f["table"], f["name"], f["location"]))
    assert checked["summary"]["failure_count"] > 0
    for row in checked["findings"]:
        assert row["severity"] == "warning"
        assert row["gate"]["blocking"] == (row["rule_id"] == "SMC009")
        assert not row["suppressed"]
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_baselines_decisions_and_expiry_still_take_precedence(project):
    root, _, _ = project
    settings = policy({"rules": {"SMC009": "fail"}})
    saved = review_policy.save_policy(root, settings)
    _, initial = ci.run_check(root)
    naming = next(row for row in initial["findings"] if row["rule_id"] == "SMC009")
    baseline = {"schema_version": "1.0", "fingerprints": [naming["fingerprint"]]}
    assert ci.run_check(root, baseline=baseline)[0] == 0
    review_policy.add_decision(root, naming, initial["scope"], disposition="accept", reason="Release", owner="Team", expires_on="2099-01-01")
    assert ci.run_check(root)[0] == 0
    current = review_policy.load_policy(root)
    current["decisions"][0]["expires_on"] = "2000-01-01"
    review_policy.save_policy(root, current, expected_digest=current["digest"])
    code, expired = ci.run_check(root)
    assert code == 1
    assert any(row["review_status"] == "expired" and row["gate"]["blocking"] for row in expired["findings"])
    current = review_policy.load_policy(root)
    current["decisions"][0]["expires_on"] = "2099-01-01"
    review_policy.save_policy(root, current, expected_digest=current["digest"])
    source = root / "M.SemanticModel/definition/tables/Sales.tmdl"
    source.write_text(source.read_text(encoding="utf-8") + "\n// subsequent edit\n", encoding="utf-8")
    code, stale = ci.run_check(root)
    assert code == 1
    assert any(row["review_status"] == "stale" and row["gate"]["blocking"] for row in stale["findings"])
    assert saved["ci_gate"]["rules"] == settings["ci_gate"]["rules"]


@pytest.mark.parametrize("gate", [None, [], {"rules": []}, {"rules": {"SMC999": "fail"}},
    {"rules": {"SMC009": []}}, {"rules": {"SMC001": "advisory"}},
    {"rules": {"SMC002": "advisory"}}, {"rules": {"SMC012": "advisory"}},
    {"rules": {"SMC010": "advisory"}}, {"require_complete_scan": 1},
    {"unused_recommendations": []}, {"unused_recommendations": ["Safe", "Safe"]},
    {"unused_recommendations": ["safe"]}, {"unknown": True}])
def test_invalid_configuration_fails_closed(project, gate):
    root, _, _ = project
    code, output = ci.run_check(root, policy=policy(gate))
    assert code == 2 and not output["ok"] and output["errors"]
    with pytest.raises(review_policy.PolicyError):
        review_policy.validate_policy(policy(gate))


def test_unused_risk_filter_does_not_change_other_findings_or_fingerprints(project):
    root, model, _ = project
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tcolumn Hidden\n\t\tisHidden\n", encoding="utf-8")
    _, original = ci.run_check(root)
    code, filtered = ci.run_check(root, policy={"schema_version": "1.0", "ci_gate": {
        "rules": {"SMC004": "fail"}, "unused_recommendations": ["Safe"]}})
    assert code == 1
    assert {row["fingerprint"] for row in filtered["findings"]} == {row["fingerprint"] for row in original["findings"]}
    unused = [row for row in filtered["findings"] if row["rule_id"] == "SMC004"]
    assert {row["cleanup_recommendation"] for row in unused} >= {"Safe", "Review"}
    assert all(row["gate"]["blocking"] == (row["cleanup_recommendation"] == "Safe") for row in unused)
    assert all(not row["gate"]["blocking"] for row in filtered["findings"] if row["rule_id"] != "SMC004")


def test_coverage_requirements_are_independent_and_cannot_be_baselined(project):
    root, _, _ = project
    settings = {"schema_version": "1.0", "ci_gate": {"require_complete_schema": True}}
    code, output = ci.run_check(root, policy=settings)
    assert code == 1 and output["gate"]["failed_requirement_count"] == 1
    assert output["gate"]["blocking_finding_count"] == 0
    baseline = {"schema_version": "1.0", "fingerprints": [row["fingerprint"] for row in output["findings"]]}
    assert ci.run_check(root, policy=settings, baseline=baseline)[0] == 1
    code, output = ci.run_check(root, policy={"schema_version": "1.0", "ci_gate": {
        "require_all_reports": True, "require_complete_scan": True}})
    assert code == 0 and all(row["passed"] for row in output["gate"]["requirements"])
    _, missing = ci.run_check(root, report_paths=[], allow_model_only=True, policy={"schema_version": "1.0", "ci_gate": {
        "require_all_reports": True, "require_complete_scan": True}})
    assert missing["gate"]["failed_requirement_count"] == 2


def test_error_findings_stay_blocking_and_defaults_are_compatible(project):
    root, model, report = project
    _, initial = ci.run_check(root)
    assert initial["ok"] and all(not row["gate"]["blocking"] for row in initial["findings"])
    assert ci.run_check(root, fail_on="warning")[0] == 1
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tmeasure Broken = [Gone]\n", encoding="utf-8")
    (report / "definition/report.json").write_text("{bad", encoding="utf-8")
    _, output = ci.run_check(root, policy=policy({"rules": {"SMC004": "advisory", "SMC006": "advisory"}}))
    assert all(row["gate"]["blocking"] for row in output["findings"] if row["severity"] == "error")
    assert not output["ok"]


def test_partial_scope_does_not_create_safe_only_failures(project):
    root, _, report = project
    other = root / "Second.Report"
    (other / "definition").mkdir(parents=True)
    (other / "definition/report.json").write_text("{}", encoding="utf-8")
    (other / "definition.pbir").write_bytes((report / "definition.pbir").read_bytes())
    code, output = ci.run_check(root, report_paths=[report], policy={"schema_version": "1.0", "ci_gate": {
        "rules": {"SMC004": "fail"}, "unused_recommendations": ["Safe"]}})
    assert code == 0 and not output["scope"]["selection_complete"]
    assert all(row["cleanup_recommendation"] == "Review" and not row["gate"]["blocking"]
               for row in output["findings"] if row["rule_id"] == "SMC004")


def test_policy_api_roundtrip_and_decision_changes_preserve_gate(project, monkeypatch):
    from test_policy_api import client_scope
    root, _, _ = project
    review_policy.save_policy(root, policy({"rules": {"SMC009": "fail"}}))
    client = client_scope(project, monkeypatch)
    read = client.post('/api/review-findings', json={}).get_json()
    current = read['policy']
    current['naming_rules'] = []
    saved = client.put('/api/review-policy', json={'policy': current, 'expected_digest': current['digest']})
    assert saved.status_code == 200
    assert saved.get_json()['policy']['ci_gate'] == current['ci_gate']
    finding = next(row for row in read['findings'] if row['rule_id'] == 'SMC004')
    checked = ci.run_check(root)[1]
    finding = next(row for row in checked['findings'] if row['fingerprint'] == finding['fingerprint'])
    response = client.post('/api/review-policy/decisions', json={'finding': finding, 'scope': checked['scope'],
        'disposition': 'keep', 'reason': 'Planned release', 'owner': 'Team', 'expires_on': '2099-01-01'})
    assert response.status_code == 200
    assert response.get_json()['policy']['ci_gate'] == current['ci_gate']
