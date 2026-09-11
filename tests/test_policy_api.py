"""Browser policy contracts preserve editable policy and reject stale evidence."""
from semantic_model_cleaner import webapp
import pytest
import test_review_policy


@pytest.fixture
def project(tmp_path):
    return test_review_policy.project.__wrapped__(tmp_path)


def client_scope(project, monkeypatch):
    root, model, report = project
    monkeypatch.setitem(webapp._state, 'workspace', root)
    monkeypatch.setitem(webapp._state, 'model_paths', [model])
    monkeypatch.setitem(webapp._state, 'report_paths', [report])
    return webapp.app.test_client()


def test_browser_policy_lifecycle_and_stale_save(project, monkeypatch):
    client = client_scope(project, monkeypatch)
    result = client.post('/api/review-findings', json={}).get_json()
    assert result['policy']['naming_rules'] == []
    assert result['policy']['decisions'] == []
    policy = result['policy']
    saved = client.put('/api/review-policy', json={'policy': policy, 'expected_digest': policy['digest']})
    assert saved.status_code == 200
    assert client.put('/api/review-policy', json={'policy': policy, 'expected_digest': 'stale'}).status_code == 400
    finding = next(f for f in result['findings'] if f['name'] == 'Spare')
    body = {'finding': finding, 'scope': result['scope'], 'disposition': 'keep',
            'reason': 'Planned release', 'owner': 'Team "A"', 'expires_on': '2099-01-01'}
    decision = client.post('/api/review-policy/decisions', json=body)
    assert decision.status_code == 200
    assert decision.get_json()['policy']['decisions'][0]['owner'] == 'Team "A"'
    refreshed = client.post('/api/review-findings', json={}).get_json()
    assert next(f for f in refreshed['findings'] if f['name'] == 'Spare')['review_status'] == 'accepted'
    identity = decision.get_json()['policy']['decisions'][0]['id']
    removed = client.delete('/api/review-policy/decisions', json={'decision_id': identity})
    assert removed.status_code == 200 and removed.get_json()['policy']['decisions'] == []


def test_browser_rejects_decision_when_source_changed(project, monkeypatch):
    client = client_scope(project, monkeypatch)
    root, model, _ = project
    result = client.post('/api/review-findings', json={}).get_json()
    finding = next(f for f in result['findings'] if f['name'] == 'Spare')
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text() + '\n// external change\n')
    response = client.post('/api/review-policy/decisions', json={
        'finding': finding, 'scope': result['scope'], 'disposition': 'keep',
        'reason': 'Planned release', 'owner': 'Team', 'expires_on': '2099-01-01'})
    assert response.status_code == 400
    assert not (root / '.smc-policy.json').exists()
