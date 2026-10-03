"""Foreign browser requests must fail before local filesystem/state side effects."""
import json
import re
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from semantic_model_cleaner import change_plan, webapp, windows_launcher
from semantic_model_cleaner.local_http import install_local_http_boundary
from semantic_model_cleaner.analysis_jobs import AnalysisJobs


@pytest.fixture
def raw_client():
    # Deliberately bypass the authenticated client used by domain API tests.
    return FlaskClient(webapp.app)


def test_unrelated_host_cannot_browse_local_files(raw_client, tmp_path):
    response = raw_client.get('/api/browse', query_string={'path': str(tmp_path)},
                              headers={'Host': 'foreign.example', 'Origin': 'https://foreign.example'})
    assert response.status_code in {400, 403}
    assert b'entries' not in response.data


def test_cross_origin_form_cannot_apply_saved_plan(raw_client, tmp_path, monkeypatch):
    model = tmp_path / 'M.SemanticModel'
    report = tmp_path / 'R.Report'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tmeasure Revenue = 1\n', encoding='utf-8')
    (report / 'definition').mkdir(parents=True)
    (report / 'definition/report.json').write_text('{}', encoding='utf-8')
    (report / 'definition.pbir').write_text(json.dumps({
        'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}
    }), encoding='utf-8')
    plans = tmp_path / 'plans'
    monkeypatch.setattr(webapp, '_plan_directory', lambda: plans)
    plan = change_plan.create_plan(model, [report], [{
        'kind': 'actions', 'actions': [{'action': 'hide', 'table': 'Sales',
                                       'name': 'Revenue', 'item_type': 'Measure'}],
    }])
    change_plan.save_plan(plan, plans)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    response = raw_client.post(f"/api/plans/{plan['id']}/apply", data={'submit': 'yes'},
                               headers={'Origin': 'https://foreign.example'})
    assert response.status_code == 403
    assert {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


def mutation_routes():
    return [(re.sub(r'<[^>]+>', 'a' * 32, rule.rule), method)
            for rule in webapp.app.url_map.iter_rules()
            for method in sorted(rule.methods - {'GET', 'HEAD', 'OPTIONS'})]


@pytest.mark.parametrize('path,method', mutation_routes())
def test_every_mutation_route_requires_token_before_dispatch(raw_client, monkeypatch, path, method):
    def forbidden_view(**kwargs):
        pytest.fail('Rejected request reached a route and could have side effects')
    for endpoint in list(webapp.app.view_functions):
        monkeypatch.setitem(webapp.app.view_functions, endpoint, forbidden_view)
    assert raw_client.open(path, method=method, json={}).status_code == 403


@pytest.mark.parametrize('host', ['foreign.example', 'localhost.foreign.example', '127.0.0.1.foreign.example', '0.0.0.0'])
@pytest.mark.parametrize('path', ['/api/session', '/api/browse', '/api/plans', '/'])
def test_untrusted_hosts_cannot_bootstrap_or_read(raw_client, host, path):
    response = raw_client.get(path, headers={'Host': host})
    assert response.status_code in {400, 403}
    assert webapp.app.config['SMC_LOCAL_TOKEN'].encode() not in response.data


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://foreign.example'}, {'Origin': 'null'}, {'Origin': 'http://localhost:9999'},
    {'Origin': 'https://localhost'}, {'Origin': 'http://localhost/'}, {'Origin': 'http://user@localhost'},
    {'Origin': 'http://localhost:bad'}, {'Origin': 'http://localhost#fragment'}, {'Origin': 'http://localhost:0'},
    {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'},
    {'Sec-Fetch-Mode': 'no-cors'}, {'Sec-Fetch-Mode': 'navigate'},
    {'Sec-Fetch-Dest': 'iframe'}, {'Sec-Fetch-Dest': 'object'},
])
@pytest.mark.parametrize('path', ['/api/session', '/api/browse', '/api/discover', '/api/plans'])
def test_foreign_browser_headers_rejected_even_with_valid_token(raw_client, path, headers):
    response = raw_client.get(path, headers={**headers, 'X-SMC-Token': webapp.app.config['SMC_LOCAL_TOKEN']})
    assert response.status_code == 403
    assert webapp.app.config['SMC_LOCAL_TOKEN'].encode() not in response.data
    assert 'Access-Control-Allow-Origin' not in response.headers


@pytest.mark.parametrize('token', [None, '', 'invalid', 'é'])
@pytest.mark.parametrize('path', ['/api/browse', '/api/discover', '/api/plans', '/api/export'])
def test_missing_or_invalid_api_token(raw_client, path, token):
    response = raw_client.get(path, headers={} if token is None else {'X-SMC-Token': token})
    assert response.status_code == 403


@pytest.mark.parametrize('content_type', ['application/x-www-form-urlencoded', 'multipart/form-data', 'text/plain'])
def test_simple_form_content_type_rejected_with_valid_token(raw_client, content_type, monkeypatch):
    monkeypatch.setitem(webapp.app.view_functions, 'api_demo', lambda: pytest.fail('Form reached demo writer'))
    response = raw_client.post('/api/demo', data='{}', content_type=content_type,
                               headers={'X-SMC-Token': webapp.app.config['SMC_LOCAL_TOKEN']})
    assert response.status_code == 403


def test_cross_origin_preflight_never_grants_cors(raw_client):
    response = raw_client.options('/api/plans', headers={
        'Origin': 'http://foreign.example', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'X-SMC-Token,Content-Type',
    })
    assert response.status_code == 403
    assert 'Access-Control-Allow-Origin' not in response.headers


@pytest.mark.parametrize('remote', ['192.168.1.20', '203.0.113.1', '::', 'invalid'])
def test_remote_peer_cannot_access_bootstrap_even_with_local_host(raw_client, remote):
    response = raw_client.get('/api/session', environ_overrides={'REMOTE_ADDR': remote}, headers={
        'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Host': 'localhost',
    })
    assert response.status_code == 403


@pytest.mark.parametrize('host', ['http://localhost', 'http://127.0.0.1:5001', 'http://[::1]:5001'])
def test_same_origin_bootstrap_and_authenticated_discovery_work(raw_client, tmp_path, host):
    headers = {'Origin': host, 'Sec-Fetch-Site': 'same-origin',
               'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'}
    bootstrap = raw_client.get('/api/session', base_url=host, headers=headers)
    assert bootstrap.status_code == 200
    assert bootstrap.headers['Cache-Control'] == 'no-store'
    headers['X-SMC-Token'] = bootstrap.json['token']
    browse = raw_client.get('/api/browse', base_url=host, headers=headers, query_string={'path': str(tmp_path)})
    assert browse.status_code == 200 and browse.json['entries'] == []


def test_tokens_are_distinct_per_application_launch():
    first, second = Flask('first'), Flask('second')
    install_local_http_boundary(first)
    install_local_http_boundary(second)
    assert first.config['SMC_LOCAL_TOKEN'] != second.config['SMC_LOCAL_TOKEN']
    response = FlaskClient(second).get('/api/missing', headers={'X-SMC-Token': first.config['SMC_LOCAL_TOKEN']})
    assert response.status_code == 403


@pytest.mark.parametrize('launcher', [webapp, windows_launcher])
@pytest.mark.parametrize('host', ['0.0.0.0', '192.168.1.20', '::', 'foreign.example'])
def test_launchers_refuse_remote_binding_before_runtime_setup(monkeypatch, launcher, host):
    monkeypatch.setattr(sys, 'argv', ['smc-web', '--host', host])
    monkeypatch.setattr(webapp, 'configure_runtime', lambda **kwargs: pytest.fail('Unsafe host reached startup'))
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 2


@pytest.mark.parametrize('layout', ['v2', 'classic'])
def test_layout_bootstrap_and_reviewed_roundtrip(raw_client, tmp_path, monkeypatch, layout):
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'user state'))
    monkeypatch.setattr(webapp, '_state', {**webapp._state, 'workspace': str(tmp_path),
        'model_search_roots': [str(tmp_path)], 'report_search_roots': [str(tmp_path)],
        'model_paths': [], 'report_paths': [], 'last_results': None})
    response = raw_client.get('/?ui=' + layout)
    assert response.status_code == 200
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['Cache-Control'] == 'no-store'
    html = response.get_data(as_text=True)
    token = re.search(r'<meta name="smc-local-token" content="([^"]+)">', html).group(1)
    assert 'local-http.js' in html
    headers = {'X-SMC-Token': token, 'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin'}
    demo = raw_client.post('/api/demo', json={}, headers=headers)
    assert demo.status_code == 200, demo.json
    models, reports = demo.json['models'], demo.json['reports']
    model_paths, report_paths = [row['path'] for row in models], [row['path'] for row in reports]
    def source_snapshot():
        return {str(path): path.read_bytes() for root in [*model_paths, *report_paths]
                for path in Path(root).rglob('*') if path.is_file()}
    original = source_snapshot()
    analyzed = raw_client.post('/api/analyze', json={'model_paths': model_paths, 'report_paths': report_paths}, headers=headers)
    assert analyzed.status_code == 200, analyzed.json
    exported = raw_client.get('/api/export?format=json', headers=headers)
    assert exported.status_code == 200 and exported.json['items']
    planned = raw_client.post('/api/plans', headers=headers, json={
        'model_path': model_paths[0], 'report_paths': report_paths,
        'operations': [{'kind': 'actions', 'actions': [{'action': 'hide', 'table': 'Sales',
                                                       'name': 'Revenue', 'item_type': 'Measure'}]}],
    })
    assert planned.status_code == 200, planned.json
    identity = planned.json['plan']['id']
    for operation in ('apply', 'verify', 'restore'):
        before = source_snapshot()
        rejected = raw_client.post(f'/api/plans/{identity}/{operation}', data={'submit': 'yes'},
                                   headers={'Origin': 'null'})
        assert rejected.status_code == 403
        assert source_snapshot() == before
        result = raw_client.post(f'/api/plans/{identity}/{operation}', json={}, headers=headers)
        assert result.status_code == 200 and result.json['ok'], result.json
    assert source_snapshot() == original


def test_embedding_is_denied_before_ui_discovery(raw_client, monkeypatch):
    monkeypatch.setitem(webapp.app.view_functions, 'index', lambda: pytest.fail('Embedded UI reached discovery'))
    assert raw_client.get('/', headers={'Sec-Fetch-Dest': 'iframe'}).status_code == 403


def test_analysis_cancellation_requires_authenticated_json_request(raw_client, monkeypatch):
    jobs = AnalysisJobs()
    monkeypatch.setattr(webapp, '_analysis_jobs', jobs)
    release, finished = threading.Event(), threading.Event()
    def run(progress):
        try:
            assert release.wait(5)
            progress('After release')
        finally:
            finished.set()
    identity = jobs.start(run)['id']
    try:
        assert raw_client.delete('/api/analysis-jobs/' + identity).status_code == 403
        assert jobs.get(identity)['status'] == 'running'
        response = raw_client.delete('/api/analysis-jobs/' + identity, json={},
                                      headers={'X-SMC-Token': webapp.app.config['SMC_LOCAL_TOKEN']})
        assert response.status_code == 200
        assert jobs.get(identity)['status'] == 'cancelling'
    finally:
        release.set()
        assert finished.wait(5)
