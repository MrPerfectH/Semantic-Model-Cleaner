import json
import time

import pytest

from semantic_model_cleaner import analyzer, webapp
from semantic_model_cleaner.analysis_jobs import AnalysisJobs
from test_change_plans import project


@pytest.fixture
def scope(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    unrelated = tmp_path / 'Reports' / 'Nested' / 'Other.Report'
    unrelated.mkdir(parents=True)
    (unrelated / 'definition.pbir').write_text(json.dumps({
        'datasetReference': {'byPath': {'path': '../../../Other.SemanticModel'}}
    }))
    missing = tmp_path / 'Reports' / 'Missing.Report'
    missing.mkdir()
    previous = webapp._state.copy()
    monkeypatch.setattr(webapp, '_analysis_jobs', AnalysisJobs())
    webapp._state.update(workspace=str(tmp_path), model_paths=[str(model)], report_paths=[])
    yield model, report, unrelated, missing
    webapp._state.clear()
    webapp._state.update(previous)


@pytest.mark.parametrize('endpoint', ['/api/analyze', '/api/analysis-jobs'])
def test_analysis_filters_unbound_reports_and_returns_reasons(scope, endpoint):
    model, report, unrelated, missing = scope
    client = webapp.app.test_client()
    response = client.post(endpoint, json={
        'model_paths': [str(model)], 'report_paths': list(map(str, [report, unrelated, missing]))
    })
    assert response.status_code in (200, 202), response.json
    payload = response.json
    if endpoint.endswith('jobs'):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = client.get('/api/analysis-jobs/' + payload['job']['id']).json['job']
            if job['status'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert job['status'] == 'completed', job
        payload = job['result']
    assert [row['path'] for row in payload['reportBinding']['selected']] == [str(report)]
    assert {row['status'] for row in payload['reportBinding']['excluded']} == {'not_connected', 'missing_definition'}
    assert all(row['message'] for row in payload['reportBinding']['excluded'])
    assert any(w['code'] == 'REPORT_SCOPE_EXCLUDED' for w in payload['warnings'])
    assert webapp._state['report_paths'] == [str(report)]


@pytest.mark.parametrize('endpoint', ['/api/analyze', '/api/analysis-jobs'])
def test_analysis_without_connected_reports_refuses_misleading_empty_scope(scope, endpoint):
    model, _, unrelated, missing = scope
    response = webapp.app.test_client().post(endpoint, json={
        'model_paths': [str(model)], 'report_paths': [str(unrelated), str(missing)]
    })
    assert response.status_code == 400
    assert 'connected' in response.json['error'].lower()
    assert len(response.json['reportBinding']['excluded']) == 2
    assert webapp._state['report_paths'] == []


def test_initial_selection_only_contains_connected_reports(scope, monkeypatch):
    model, report, unrelated, missing = scope
    monkeypatch.setattr(webapp, '_discover_initial_artifacts', lambda: ([model], [report, unrelated, missing]))
    captured = {}
    def render(_template, **context):
        captured.update(context)
        return 'index'
    monkeypatch.setattr(webapp, 'render_template', render)
    assert webapp.app.test_client().get('/').status_code == 200
    assert [r['path'] for r in captured['initial_reports']] == [str(report)]
    assert len(captured['initial_report_binding']['excluded']) == 2


def test_invalid_utf8_report_binding_is_reported_instead_of_crashing(scope):
    model, _, unrelated, _ = scope
    (unrelated / 'definition.pbir').write_bytes(b'\xff\xfe invalid')
    status = analyzer.report_binding_status(unrelated, model)
    assert status['status'] == 'invalid_definition'


def test_hidden_usage_survives_serialization_and_compaction(scope):
    model, report, _, _ = scope
    results = analyzer.analyze(model.parent, model_paths=[model], report_paths=[report])
    row = next(row for row in results['items'] if row['usages'])
    usage = row['usages'][0]
    usage.page_hidden = True
    usage.visual_hidden = True
    payload = webapp._serialize_results(results, model_paths=[str(model)])
    item = next(i for i in payload['items'] if i['name'] == row['item'].name and i['table'] == row['item'].table)
    assert item['usageDetails'][0]['pageHidden'] is True
    assert item['usageDetails'][0]['visualHidden'] is True
    assert item['usageState'] != 'Unused'
    packed = webapp._compact_browser_results(payload)
    assert next(i for i in packed['items'] if i['name'] == item['name'])['usageDetails'][0]['pageHidden'] is True


@pytest.mark.parametrize('declarations,expected', [
    ('', ('many', 'one')),
    ('\tfromCardinality: one\n', ('one', 'one')),
    ('\ttoCardinality: many\n', ('many', 'many')),
    ('\tfromCardinality: one\n\ttoCardinality: many\n', ('one', 'many')),
])
def test_relationship_omission_defaults_match_tom(scope, declarations, expected):
    model, _, _, _ = scope
    (model / 'definition' / 'relationships.tmdl').write_text(
        'relationship R\n\tfromColumn: Sales.Amount\n\ttoColumn: Date.Id\n' + declarations
    )
    relationship, = analyzer.parse_relationship_details(model)
    assert (relationship.from_cardinality, relationship.to_cardinality) == expected


def test_report_health_total_does_not_double_count_stale_or_model_signals():
    issues = [{'issueType': 'missing_column'}, {'issueType': 'stale_visual_selector'}]
    items = [{'staleUsageCount': 5, 'brokenDaxRefs': ['A[B]', 'C[D]']}]
    health = webapp._build_report_health(issues, items)
    assert health['totalIssueCount'] == len(issues)
    assert health['signalCounts'] == {'staleReferences': 5, 'brokenModelReferences': 2, 'unsupportedMetadata': 0}


def test_async_analysis_rejects_platform_binding_changed_during_scan(scope, monkeypatch):
    model, report, _, _ = scope
    platform = model / '.platform'
    platform.write_text(json.dumps({'metadata': {'displayName': 'Published Sales'}}))
    (report / 'definition.pbir').write_text(json.dumps({
        'datasetReference': {'byConnection': {'connectionString': 'Initial Catalog=Published Sales'}}
    }))
    previous_results = object()
    webapp._state['last_results'] = previous_results
    analyze = analyzer.analyze

    def change_binding(**kwargs):
        result = analyze(**kwargs)
        platform.write_text(json.dumps({'metadata': {'displayName': 'Unrelated'}}))
        return result

    monkeypatch.setattr(analyzer, 'analyze', change_binding)
    client = webapp.app.test_client()
    response = client.post('/api/analysis-jobs', json={
        'model_paths': [str(model)], 'report_paths': [str(report)]
    })
    assert response.status_code == 202, response.json
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get('/api/analysis-jobs/' + response.json['job']['id']).json['job']
        if job['status'] not in ('queued', 'running'):
            break
        time.sleep(.01)
    assert job['status'] == 'failed', job
    assert 'changed' in job['error'].lower()
    assert webapp._state['last_results'] is previous_results
