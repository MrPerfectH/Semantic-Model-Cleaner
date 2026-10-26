"""VS Code sidebar scope: discovery per model and exact analysis of the chosen Reports."""
import json
import shutil
import time
from pathlib import Path

import pytest

from semantic_model_cleaner import webapp
from semantic_model_cleaner.analysis_jobs import AnalysisJobs
from semantic_model_cleaner.vscode_host import configure_host

DEMO = Path(__file__).parents[1] / 'src/semantic_model_cleaner/demo_workspace'


def bind(report, model_dir):
    (report / 'definition.pbir').write_text(json.dumps(
        {'version': '4.0', 'datasetReference': {'byPath': {'path': f'../../Models/{model_dir}'}}}))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Two models; Sales has two Reports, Second has one; one binding is unreadable."""
    root = tmp_path / 'Project'
    shutil.copytree(DEMO, root)
    models, reports = root / 'Models', root / 'Reports'
    shutil.copytree(models / 'TestModel.SemanticModel', models / 'Second.SemanticModel')
    for name, model in [('Report B', 'TestModel'), ('Report C', 'Second')]:
        shutil.copytree(reports / 'TestReport.Report', reports / f'{name}.Report')
        bind(reports / f'{name}.Report', f'{model}.SemanticModel')
    shutil.copytree(reports / 'TestReport.Report', reports / 'Broken.Report')
    (reports / 'Broken.Report/definition.pbir').write_text('{not json')
    previous = dict(webapp._state)
    monkeypatch.setitem(webapp.app.config, 'SMC_VSCODE_HOST_SCOPE', True)
    jobs = AnalysisJobs()
    monkeypatch.setattr(webapp, '_analysis_jobs', jobs)
    webapp.configure_runtime(workspace=str(root))
    try:
        yield root.resolve(), jobs
    finally:
        webapp._state.clear()
        webapp._state.update(previous)


def scope(body=None):
    return webapp.app.test_client().post('/api/vscode/scope', json=body or {})


def run(jobs, model, reports, **extra):
    response = webapp.app.test_client().post('/api/analysis-jobs', json={
        'model_paths': [str(model)], 'report_paths': [str(r) for r in reports], **extra})
    if response.status_code != 202:
        return response.status_code, response.json
    identity = response.json['job']['id']
    deadline = time.monotonic() + 20
    while jobs.get(identity)['status'] in {'running', 'cancelling'}:
        assert time.monotonic() < deadline
        time.sleep(.01)
    job = jobs.get(identity)
    assert job['status'] == 'completed', job
    return 202, job['result']


def limitation_ids(result):
    return {row['id'] for row in result['analysisLimitations']['limitations']}


def test_scope_endpoint_requires_host_scope_mode(workspace, monkeypatch):
    monkeypatch.setitem(webapp.app.config, 'SMC_VSCODE_HOST_SCOPE', False)
    assert scope().status_code == 404


def test_multiple_models_require_an_explicit_choice(workspace):
    root, _ = workspace
    data = scope().json
    assert sorted(m['name'] for m in data['models']) == ['Second', 'TestModel']
    assert data['model'] is None and data['reports'] == []
    chosen = scope({'model_path': str(root / 'Models/TestModel.SemanticModel')}).json
    assert chosen['model'] == str(root / 'Models/TestModel.SemanticModel')
    assert [r['name'] for r in chosen['reports']] == ['Report B', 'TestReport']
    assert [r['name'] for r in chosen['unverifiedReports']] == ['Broken']
    assert chosen['otherReportCount'] == 1
    other = scope({'model_path': str(root / 'Models/Second.SemanticModel')}).json
    assert [r['name'] for r in other['reports']] == ['Report C']


def test_sole_model_is_selected_by_default(workspace):
    root, _ = workspace
    shutil.rmtree(root / 'Models/Second.SemanticModel')
    data = scope().json
    assert data['model'] == str(root / 'Models/TestModel.SemanticModel')
    assert [r['name'] for r in data['reports']] == ['Report B', 'TestReport']


def test_unknown_model_is_a_stale_choice(workspace, tmp_path):
    assert scope({'model_path': str(tmp_path / 'Gone.SemanticModel')}).status_code == 409
    assert scope({'model_path': 7}).status_code == 409


def test_exact_subset_records_unselected_reports_and_withholds_safe(workspace):
    root, jobs = workspace
    model = root / 'Models/TestModel.SemanticModel'
    status, full = run(jobs, model, [root / 'Reports/TestReport.Report', root / 'Reports/Report B.Report'],
                       report_selection='exact')
    assert status == 202
    assert 'report_scan:not_selected' not in limitation_ids(full)
    # Broken.Report's binding cannot be verified, so Safe is withheld like in the CLI.
    assert 'report_scan:unverified_binding' in limitation_ids(full)
    assert not any(item['deleteSafety'] == 'Safe' for item in full['items'])
    status, subset = run(jobs, model, [root / 'Reports/TestReport.Report'], report_selection='exact')
    assert status == 202
    assert 'report_scan:not_selected' in limitation_ids(subset)
    assert not any(item['deleteSafety'] == 'Safe' for item in subset['items'])
    excluded = subset['reportBinding']['excluded']
    assert {(row['name'], row['status']) for row in excluded} == {('Report B', 'not_selected'),
                                                                  ('Broken', 'invalid_definition')}
    assert [row['name'] for row in subset['reportBinding']['selected']] == ['TestReport']
    assert webapp._state['report_paths'] == [str(root / 'Reports/TestReport.Report')]


@pytest.mark.parametrize('selection', ['exact', None])
def test_every_connected_report_with_verified_bindings_allows_safe(workspace, selection):
    root, jobs = workspace
    shutil.rmtree(root / 'Reports/Broken.Report')
    model = root / 'Models/TestModel.SemanticModel'
    extra = {'report_selection': selection} if selection else {}
    status, full = run(jobs, model, [root / 'Reports/TestReport.Report', root / 'Reports/Report B.Report'], **extra)
    assert status == 202
    assert not limitation_ids(full) & {'report_scan:not_selected', 'report_scan:unverified_binding'}
    assert any(item['deleteSafety'] == 'Safe' for item in full['items'])


@pytest.mark.parametrize('endpoint', ['job', 'sync'])
def test_standalone_analysis_withholds_safe_for_unverified_bindings_in_the_project(workspace, endpoint):
    root, jobs = workspace
    model = root / 'Models/TestModel.SemanticModel'
    reports = [root / 'Reports/TestReport.Report', root / 'Reports/Report B.Report']
    if endpoint == 'job':
        status, result = run(jobs, model, reports)
        assert status == 202
    else:
        response = webapp.app.test_client().post('/api/analyze', json={
            'model_paths': [str(model)], 'report_paths': [str(r) for r in reports]})
        assert response.status_code == 200, response.json
        result = response.json
    ids = limitation_ids(result) if endpoint == 'job' else {
        row['id'] for row in result['analysisLimitations']['limitations']}
    assert 'report_scan:unverified_binding' in ids
    assert not any(item['deleteSafety'] == 'Safe' for item in result['items'])


def test_exact_zero_reports_is_model_only(workspace):
    root, jobs = workspace
    model = root / 'Models/TestModel.SemanticModel'
    status, result = run(jobs, model, [], report_selection='exact')
    assert status == 202
    assert 'report_scan:not_requested' in limitation_ids(result)
    assert not any(item['deleteSafety'] == 'Safe' for item in result['items'])
    assert result['items']


def test_standalone_still_requires_reports_and_ignores_subset_limitation(workspace):
    root, jobs = workspace
    model = root / 'Models/TestModel.SemanticModel'
    assert run(jobs, model, [])[0] == 400
    status, result = run(jobs, model, [root / 'Reports/TestReport.Report'])
    assert status == 202
    assert 'report_scan:not_selected' not in limitation_ids(result)


def test_exact_selection_rejects_reports_of_another_model(workspace):
    root, jobs = workspace
    status, body = run(jobs, root / 'Models/TestModel.SemanticModel', [root / 'Reports/Report C.Report'],
                       report_selection='exact')
    assert status == 409 and 'connected' in body['error']
    response = webapp.app.test_client().post('/api/analyze', json={
        'model_paths': [str(root / 'Models/TestModel.SemanticModel')],
        'report_paths': [str(root / 'Reports/Report C.Report')], 'report_selection': 'exact'})
    assert response.status_code == 400


def test_sync_exact_zero_reports(workspace):
    root, _ = workspace
    response = webapp.app.test_client().post('/api/analyze', json={
        'model_paths': [str(root / 'Models/TestModel.SemanticModel')], 'report_paths': [],
        'report_selection': 'exact'})
    assert response.status_code == 200, response.json
    assert webapp.app.test_client().post('/api/analyze', json={
        'model_paths': [str(root / 'Models/TestModel.SemanticModel')], 'report_paths': []}).status_code == 400


@pytest.mark.parametrize('features, expected', [(None, False), ('', False), ('scope', True), ('other,scope', True)])
def test_host_features_are_opt_in(monkeypatch, features, expected):
    from flask import Flask
    app = Flask('features')
    monkeypatch.setenv('SMC_VSCODE_TOKEN', 'a' * 64)
    monkeypatch.setenv('SMC_VSCODE_ANCESTORS', json.dumps(['https://panel.vscode-cdn.net']))
    if features is None:
        monkeypatch.delenv('SMC_VSCODE_FEATURES', raising=False)
    else:
        monkeypatch.setenv('SMC_VSCODE_FEATURES', features)
    configure_host(app)
    assert app.config['SMC_VSCODE_HOST_SCOPE'] is expected


def test_invalid_host_features_fail(monkeypatch):
    from flask import Flask
    monkeypatch.setenv('SMC_VSCODE_TOKEN', 'a' * 64)
    monkeypatch.setenv('SMC_VSCODE_ANCESTORS', json.dumps(['https://panel.vscode-cdn.net']))
    monkeypatch.setenv('SMC_VSCODE_FEATURES', 'scope; x')
    with pytest.raises(ValueError):
        configure_host(Flask('bad'))


@pytest.mark.parametrize('ui', ['v2', 'classic'])
def test_templates_load_sidebar_scope_only_in_host_scope_mode(workspace, monkeypatch, ui):
    client = webapp.app.test_client()
    page = client.get(f'/?ui={ui}').get_data(as_text=True)
    assert 'host-scope.js' not in page and 'smc-embedded-host' not in page
    monkeypatch.setitem(webapp.app.config, 'SMC_WEBVIEW_ANCESTORS', ('vscode-webview://abc',))
    monkeypatch.setitem(webapp.app.config, 'SMC_VSCODE_HOST_SCOPE', False)
    page = client.get(f'/?ui={ui}').get_data(as_text=True)
    assert 'smc-embedded-host' in page and 'data-host-scope' not in page and 'host-scope.js' not in page
    monkeypatch.setitem(webapp.app.config, 'SMC_VSCODE_HOST_SCOPE', True)
    page = client.get(f'/?ui={ui}').get_data(as_text=True)
    assert 'data-host-scope="sidebar"' in page
    assert page.index('analysis-jobs.js') < page.index('host-scope.js')
