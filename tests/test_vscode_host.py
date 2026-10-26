"""VS Code opt-in cannot turn the normal loopback boundary into a CORS server."""
import hashlib
import json
import sys

import pytest
from flask import Flask
from flask.testing import FlaskClient

from semantic_model_cleaner.local_http import install_local_http_boundary
from semantic_model_cleaner.vscode_host import configure_host, validate_ancestors
from semantic_model_cleaner import webapp
from semantic_model_cleaner import __version__

ORIGINS = ['https://specific-panel.vscode-cdn.net', 'vscode-file://vscode-app']
TOKEN = 'a' * 64


@pytest.fixture
def embedded(monkeypatch):
    app = Flask('embedded')
    install_local_http_boundary(app)
    app.add_url_rule('/', view_func=lambda: 'UI')
    app.add_url_rule('/api/write', endpoint='write', view_func=lambda: 'written', methods=['POST'])
    monkeypatch.setenv('SMC_VSCODE_TOKEN', TOKEN)
    monkeypatch.setenv('SMC_VSCODE_ANCESTORS', json.dumps(ORIGINS))
    configure_host(app)
    app.config['SMC_WEBVIEW_PORT'] = 54321
    return FlaskClient(app)


def request(client, path='/', **kwargs):
    return client.open(path, base_url='http://127.0.0.1:54321', **kwargs)


def test_only_opted_in_document_can_be_framed(embedded):
    response = request(embedded, headers={'Sec-Fetch-Dest': 'iframe',
        'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 200
    assert response.headers['Content-Security-Policy'] == (
        'frame-ancestors ' + ' '.join(ORIGINS) + "; base-uri 'self'; object-src 'none'")
    assert 'X-Frame-Options' not in response.headers
    assert 'Access-Control-Allow-Origin' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'https://another.vscode-cdn.net'])
def test_foreign_explicit_origin_cannot_navigate_embedded_document(embedded, origin):
    assert request(embedded, headers={'Origin': origin, 'Sec-Fetch-Dest': 'iframe',
        'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site'}).status_code == 403


@pytest.mark.parametrize('path', ['/api/session', '/api/vscode/ready', '/api/write', '/static/file.js'])
@pytest.mark.parametrize('headers', [
    {'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site'},
    {'Sec-Fetch-Site': 'cross-site'}, {'Origin': ORIGINS[0]}, {'Origin': 'null'},
])
def test_api_and_resource_rules_remain_unchanged(embedded, path, headers):
    response = request(embedded, path, headers={**headers, 'X-SMC-Token': TOKEN})
    assert response.status_code == 403
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert TOKEN.encode() not in response.data


def test_ready_proves_this_instance_only(embedded):
    assert request(embedded, '/api/vscode/ready').status_code == 403
    assert request(embedded, '/api/vscode/ready', headers={'X-SMC-Token': 'b' * 64}).status_code == 403
    response = request(embedded, '/api/vscode/ready', headers={'X-SMC-Token': TOKEN})
    assert response.json == {'protocol': 1, 'engineVersion': __version__,
                            'instance': hashlib.sha256(TOKEN.encode()).hexdigest()}
    assert TOKEN.encode() not in response.data


def test_exact_authority_peer_and_json_still_required(embedded):
    assert embedded.get('/', base_url='http://127.0.0.1:54322').status_code == 403
    assert request(embedded, environ_overrides={'REMOTE_ADDR': '192.0.2.1'}).status_code == 403
    assert request(embedded, '/api/write', method='POST', data='x',
                   headers={'X-SMC-Token': TOKEN}).status_code == 403
    assert request(embedded, '/api/write', method='POST', json={},
                   headers={'X-SMC-Token': TOKEN, 'Origin': 'http://127.0.0.1:54321'}).status_code == 200


@pytest.mark.parametrize('value', [None, [], ['*'], ['https:'], ['https://*.vscode-cdn.net'],
    ['https://specific-panel.vscode-cdn.net/'], ['https://user@specific-panel.vscode-cdn.net'],
    ['https://specific-panel.vscode-cdn.net:443'], ['https://specific-panel.vscode-cdn.net; img-src *'],
    ['vscode-file://vscode-app'], ['http://localhost:9999'], ['null'], [123]])
def test_ancestor_configuration_rejects_broad_or_malformed_sources(value):
    with pytest.raises(ValueError):
        validate_ancestors(value)


def test_ordinary_app_ignores_environment_without_explicit_host_mode(monkeypatch):
    monkeypatch.setenv('SMC_VSCODE_TOKEN', TOKEN)
    monkeypatch.setenv('SMC_VSCODE_ANCESTORS', json.dumps(ORIGINS))
    app = Flask('ordinary')
    install_local_http_boundary(app)
    app.add_url_rule('/', view_func=lambda: 'UI')
    assert app.config['SMC_LOCAL_TOKEN'] != TOKEN
    assert FlaskClient(app).get('/', headers={'Sec-Fetch-Dest': 'iframe'}).status_code == 403


@pytest.mark.parametrize('extra', [[], ['--port', '0', '--debug'], ['--port', '0', '--host', 'localhost']])
def test_unsafe_vscode_flags_fail_before_runtime(monkeypatch, extra):
    monkeypatch.setattr(sys, 'argv', ['smc-web', '--vscode', *extra])
    monkeypatch.setattr(webapp, 'configure_runtime', lambda **_: pytest.fail('Reached runtime'))
    with pytest.raises(SystemExit) as error:
        webapp.main()
    assert error.value.code == 2


def test_real_host_exits_when_parent_pipe_closes(tmp_path):
    """The extension-host crash path must not leave the real Python server alive."""
    import os
    from pathlib import Path
    import subprocess
    import queue
    import threading
    from urllib.request import ProxyHandler, Request, build_opener

    source = str(Path(webapp.__file__).resolve().parents[1])
    env = {**os.environ, 'PYTHONPATH': source, 'PYTHONUNBUFFERED': '1',
           'SMC_VSCODE_TOKEN': TOKEN, 'SMC_VSCODE_ANCESTORS': json.dumps(ORIGINS),
           'SMC_USER_DIR': str(tmp_path / 'user')}
    process = subprocess.Popen([sys.executable, '-m', 'semantic_model_cleaner.web',
        '--vscode', '--host', '127.0.0.1', '--port', '0', str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        line = lines.get(timeout=10)
        assert line.startswith('SMC_VSCODE_READY '), line
        assert TOKEN not in line
        port = json.loads(line.split(' ', 1)[1])['port']
        http = build_opener(ProxyHandler({}))
        with http.open(Request(f'http://127.0.0.1:{port}/api/vscode/ready',
                              headers={'X-SMC-Token': TOKEN}), timeout=3) as response:
            assert json.load(response)['instance'] == hashlib.sha256(TOKEN.encode()).hexdigest()
        # The page spawns git for its build stamp while the parent watcher reads.
        # On Windows that once deadlocked on the shared stdin pipe.
        with http.open(Request(f'http://127.0.0.1:{port}/', headers={
                'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'cross-site'}), timeout=20) as response:
            assert response.status == 200
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        assert not list(tmp_path.iterdir())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
