import threading
import time

import pytest

from semantic_model_cleaner.analysis_jobs import AnalysisJobs
from semantic_model_cleaner import webapp


def wait_done(jobs, identity):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = jobs.get(identity)
        if job['status'] not in {'running', 'cancelling'}:
            return job
        time.sleep(.005)
    pytest.fail('Job did not finish')


def test_cancel_discards_results_and_refuses_overlapping_work():
    jobs = AnalysisJobs()
    started, release = threading.Event(), threading.Event()
    published = []
    def run(progress):
        progress('Scanning', 1, 2)
        started.set()
        assert release.wait(3)
        return {'items': ['must not publish']}
    first = jobs.start(run, published.append)
    assert started.wait(3)
    with pytest.raises(ValueError, match='already running'):
        jobs.start(run)
    assert jobs.cancel(first['id'])['status'] == 'cancelling'
    release.set()
    assert wait_done(jobs, first['id'])['status'] == 'cancelled'
    assert published == []
    assert 'result' not in jobs.get(first['id'])


def test_jobs_publish_once_retain_bounded_results_and_report_failure():
    jobs = AnalysisJobs(retain=1)
    published = []
    first = jobs.start(lambda progress: {'items': [1]}, published.append)
    assert wait_done(jobs, first['id'])['result'] == {'items': [1]}
    assert jobs.cancel(first['id'])['status'] == 'completed'
    assert published == [{'items': [1]}]
    def fail(progress):
        raise ValueError('Invalid model')
    second = jobs.start(fail)
    assert wait_done(jobs, second['id'])['error'] == 'Invalid model'
    with pytest.raises(KeyError):
        jobs.get(first['id'])


def test_job_api_real_demo_and_invalid_scope(tmp_path, monkeypatch):
    from test_change_plans import project
    model, report = project(tmp_path)
    jobs = AnalysisJobs()
    monkeypatch.setattr(webapp, '_analysis_jobs', jobs)
    previous = dict(webapp._state)
    try:
        client = webapp.app.test_client()
        assert client.post('/api/analysis-jobs', json={'model_paths': [], 'report_paths': []}).status_code == 400
        response = client.post('/api/analysis-jobs', json={'model_paths': [str(model)], 'report_paths': [str(report)]})
        assert response.status_code == 202
        identity = response.json['job']['id']
        result = wait_done(jobs, identity)
        assert result['status'] == 'completed', result
        assert len(result['result']['items']) == 9
        assert client.get('/api/analysis-jobs/' + identity).json['job']['result']['items']
        assert webapp._state['model_paths'] == [str(model)]
        assert client.get('/api/analysis-jobs/missing').status_code == 404
    finally:
        webapp._state.clear()
        webapp._state.update(previous)


def test_compact_transport_reconstructs_references_and_shares_items(tmp_path):
    import json
    from pathlib import Path
    import shutil
    import subprocess
    from test_change_plans import project
    from semantic_model_cleaner import analyzer
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for browser transport roundtrip')
    model, report = project(tmp_path)
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    payload = webapp._serialize_results(result, model_paths=[model])
    expected = payload['references']
    packed = webapp._compact_browser_results(payload)
    input_file = tmp_path / 'compact.json'
    input_file.write_text(json.dumps(packed))
    js = Path(__file__).parents[1] / 'src/semantic_model_cleaner/static/analysis-jobs.js'
    program = r'''
const fs=require('fs'), vm=require('vm');
const context={window:{},apiPost:()=>{},document:{createElement:()=>({setAttribute(){},style:{},append(){}}),body:{appendChild(){}}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const result=context.window.smcHydrateAnalysis(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
if(!result.tables.every(t=>t.items.every(i=>result.items.includes(i)))) throw Error('Not canonical');
process.stdout.write(JSON.stringify(result.references));
'''
    run = subprocess.run([node, '-e', program, str(js), str(input_file)], capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == expected


def test_json_compression_respects_negotiation():
    import gzip
    import json
    client = webapp.app.test_client()
    with webapp.app.test_request_context(headers={'Accept-Encoding': 'gzip'}):
        response = webapp.compress_browser_json(webapp.jsonify({'data': 'a' * 9000}))
        assert response.headers['Content-Encoding'] == 'gzip'
        assert json.loads(gzip.decompress(response.data)) == {'data': 'a' * 9000}
    with webapp.app.test_request_context(headers={'Accept-Encoding': 'gzip;q=0'}):
        response = webapp.compress_browser_json(webapp.jsonify({'data': 'a' * 9000}))
        assert 'Content-Encoding' not in response.headers
    assert client.get('/api/analysis-jobs/missing').status_code == 404
