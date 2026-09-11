"""Independent regression probes for the in-flight async/policy implementation.

Run with the integration checkout on PYTHONPATH. Tests express the required
behavior for analysis lifecycle and policy attribute encoding.
"""
import threading
import time

import pytest

from semantic_model_cleaner import webapp
from semantic_model_cleaner.analysis_jobs import AnalysisJobs


def wait_terminal(jobs, identity):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = jobs.get(identity)
        if job['status'] not in {'running', 'cancelling'}:
            return job
        time.sleep(.005)
    pytest.fail('Analysis did not finish')


@pytest.fixture
def isolated_app(monkeypatch, tmp_path):
    state = dict(webapp._state)
    jobs = AnalysisJobs()
    monkeypatch.setattr(webapp, '_analysis_jobs', jobs)
    model, report = tmp_path / 'Demo.SemanticModel', tmp_path / 'Demo.Report'
    (model / "definition").mkdir(parents=True)
    (model / "definition/model.tmdl").write_text("model Model\n")
    report.mkdir()
    (report / "definition.pbir").write_text(
        '{"datasetReference":{"byPath":{"path":"../Demo.SemanticModel"}}}')
    webapp._state.update(workspace=str(tmp_path), model_paths=[str(model)],
                         report_paths=[str(report)], last_results={'snapshot': 'previous'})
    monkeypatch.setattr(webapp, '_serialize_results', lambda result, **kwargs:
                        {'items': [], 'tables': [], 'references': []})
    yield webapp.app.test_client(), jobs, model, report
    webapp._state.clear()
    webapp._state.update(state)


def test_analysis_cannot_republish_pre_change_results_after_successful_apply(isolated_app, monkeypatch):
    client, jobs, model, report = isolated_app
    read, release = threading.Event(), threading.Event()
    def analyze(**kwargs):
        read.set()
        assert release.wait(3)
        return {'snapshot': 'before_change'}
    monkeypatch.setattr(webapp.analyzer, 'analyze', analyze)
    monkeypatch.setattr(webapp, '_stored_plan', lambda identity: {'id': identity})
    monkeypatch.setattr(webapp.change_plan, 'apply_plan', lambda plan, directory:
                        {'ok': True, 'receipt': {'status': 'applied'}})
    response = client.post('/api/analysis-jobs', json={
        'model_paths': [str(model)], 'report_paths': [str(report)],
    })
    assert response.status_code == 202
    identity = response.json['job']['id']
    try:
        assert read.wait(3)
        applied = client.post('/api/plans/' + 'a' * 32 + '/apply', json={})
    finally:
        release.set()
    job = wait_terminal(jobs, identity)
    # Either serialize reads/writes by refusing apply during a scan, or discard
    # this scan. Never present the pre-write analysis as the latest result.
    assert applied.status_code == 409 or (
        job['status'] != 'completed' and webapp._state['last_results'] != {'snapshot': 'before_change'}
    )


def test_analysis_does_not_overwrite_a_newer_selected_scope(isolated_app, monkeypatch, tmp_path):
    client, jobs, model, report = isolated_app
    read, release = threading.Event(), threading.Event()
    def analyze(**kwargs):
        read.set()
        assert release.wait(3)
        return {'snapshot': 'old_scope'}
    monkeypatch.setattr(webapp.analyzer, 'analyze', analyze)
    response = client.post('/api/analysis-jobs', json={
        'model_paths': [str(model)], 'report_paths': [str(report)],
    })
    identity = response.json['job']['id']
    newer_model = str(tmp_path / 'New.SemanticModel')
    newer_report = str(tmp_path / 'New.Report')
    (tmp_path / 'New.SemanticModel/definition').mkdir(parents=True)
    (tmp_path / 'New.SemanticModel/definition/model.tmdl').write_text('model New\n')
    try:
        assert read.wait(3)
        monkeypatch.setattr(webapp.analyzer, 'discover_models', lambda roots: [tmp_path / 'New.SemanticModel'])
        monkeypatch.setattr(webapp.analyzer, 'discover_reports', lambda roots: [tmp_path / 'New.Report'])
        monkeypatch.setattr(webapp.analyzer, 'report_display_name', lambda report: 'New')
        discovered = client.post('/api/discover', json={'model_roots': [str(tmp_path)], 'report_roots': [str(tmp_path)]})
        assert discovered.status_code == 200
    finally:
        release.set()
    wait_terminal(jobs, identity)
    assert webapp._state['model_paths'] == [newer_model]
    assert webapp._state['report_paths'] == [newer_report]
    assert webapp._state['last_results'] != {'snapshot': 'old_scope'}


@pytest.mark.parametrize('layout', ['index.html', 'index_v2.html'])
def test_repository_owner_text_cannot_inject_input_attributes(layout):
    """Exercise the actual esc/formField helpers with DOM text serialization."""
    import json
    from pathlib import Path
    import shutil
    import subprocess
    from html.parser import HTMLParser
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required to execute UI helpers')
    source_root = Path(webapp.__file__).parent
    template = (source_root / 'templates' / layout).read_text()
    start = template.index('function esc(s) {')
    escape = template[start:template.index('\nfunction itemKey', start)]
    script = (source_root / 'static/policy-workspace.js').read_text()
    start = script.index('  function formField(')
    field = script[start:script.index('\n  async function call(', start)]
    # A div's innerHTML serializer escapes &, < and > in a text node, but not
    # quote characters. Attribute encoding needs an additional explicit step.
    harness = '''
const document = {createElement() { return {
  textContent: '',
  get innerHTML() { return this.textContent.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
}; }};
''' + escape + '\n' + field + '''
console.log(JSON.stringify(formField('owner','Owner','text','" autofocus onfocus="injected')));
'''
    output = subprocess.run([node, '-e', harness], capture_output=True, text=True, check=True)
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inputs = []
        def handle_starttag(self, tag, attrs):
            if tag == 'input':
                self.inputs.append(dict(attrs))
    parsed = Inputs()
    parsed.feed(json.loads(output.stdout))
    assert len(parsed.inputs) == 1
    assert parsed.inputs[0]['value'] == '" autofocus onfocus="injected'
    assert 'autofocus' not in parsed.inputs[0]
    assert 'onfocus' not in parsed.inputs[0]


def test_external_metadata_edit_discards_scan(isolated_app, monkeypatch):
    client, jobs, model, report = isolated_app
    metadata = model / 'model.tmdl'
    metadata.write_text('model Original')
    read, release = threading.Event(), threading.Event()

    def analyze(**kwargs):
        read.set()
        assert release.wait(3)
        return {'snapshot': 'before_external_change'}

    monkeypatch.setattr(webapp.analyzer, 'analyze', analyze)
    response = client.post('/api/analysis-jobs', json={
        'model_paths': [str(model)], 'report_paths': [str(report)],
    })
    try:
        assert read.wait(3)
        metadata.write_text('model Changed')
    finally:
        release.set()
    job = wait_terminal(jobs, response.json['job']['id'])
    assert job['status'] == 'failed'
    assert 'changed during analysis' in job['error']
    assert webapp._state['last_results'] != {'snapshot': 'before_external_change'}
