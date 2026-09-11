"""Invalid model folders fail setup instead of inventing broken report references."""
import json
import subprocess
import sys

import pytest

from semantic_model_cleaner import analyzer, webapp


def model_project(tmp_path, contents):
    model = tmp_path / 'Invalid.SemanticModel'
    model.mkdir()
    for relative, text in contents.items():
        path = model / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    report = tmp_path / 'Executive.Report'
    (report / 'definition').mkdir(parents=True)
    (report / 'definition.pbir').write_text(json.dumps({
        'datasetReference': {'byPath': {'path': '../Invalid.SemanticModel'}},
    }))
    (report / 'definition/report.json').write_text('{}')
    return model, report


@pytest.mark.parametrize('contents', [
    {}, {'definition/tables': 'not a directory'},
    {'definition/tables/Empty.tmdl': ''},
    {'definition/model.tmdl': '// model Model\n'},
    {'definition/tables/Bad.tmdl': 'annotation note = table Sales\n'},
    {'definition/model.tmdl': "model 'Broken\n"},
    {'definition/tables/Bad.tmdl': "table 'Broken\n"},
    {'definition/model.tmdl': '/*\nmodel Fake\n*/\n'},
])
def test_invalid_model_rejected_before_analysis_or_job(tmp_path, contents):
    model, report = model_project(tmp_path, contents)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(analyzer.UnsupportedSemanticModelError, match='TMDL'):
        analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    client = webapp.app.test_client()
    for route in ('/api/analyze', '/api/analysis-jobs'):
        response = client.post(route, json={'model_paths': [str(model)], 'report_paths': [str(report)]})
        assert response.status_code == 400, response.json
        assert 'TMDL' in response.json['error']
        assert 'job' not in response.json
        assert 'reportIssues' not in response.json
    assert {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('contents', [
    {'definition/model.tmdl': '\ufeffmodel Model\n\tculture: en-US\n'},
    {'definition/tables/Sales.tmdl': "table 'Empty Sales'\n"},
    {'definition/tables/Sales.tmdl': 'table Sales\n\tmeasure Revenue = 1\n'},
    {'definition/tables/Sales.tmdl': "\ufefftable 'Sales Team''s'\n\tmeasure Revenue = 1\n"},
])
def test_valid_empty_or_table_only_tmdl_is_not_rejected(tmp_path, contents):
    model, report = model_project(tmp_path, contents)
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert result['coverage']['complete']
    assert webapp.app.test_client().post('/api/analyze', json={
        'model_paths': [str(model)], 'report_paths': [str(report)],
    }).status_code == 200


def test_bom_table_keeps_real_items_and_report_references(tmp_path):
    model, report = model_project(tmp_path, {
        'definition/tables/Sales.tmdl': '\ufefftable Sales\n\tmeasure Revenue = 1\n',
    })
    visual = report / 'definition/pages/P/visuals/V/visual.json'
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({'visual': {'query': {'Measure': {
        'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Revenue',
    }}}}))
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert [(r['item'].name, r['status']) for r in result['items']] == [('Revenue', 'USED')]
    assert not result['report_issues']


@pytest.mark.parametrize('bad_path', ['definition/tables/Z.tmdl', 'definition/roles/Role.tmdl'])
def test_valid_first_header_does_not_hide_unreadable_later_metadata(tmp_path, bad_path):
    model, report = model_project(tmp_path, {
        'definition/model.tmdl': 'model Model\n',
        'definition/tables/A.tmdl': 'table Sales\n\tmeasure Revenue = 1\n',
    })
    bad = model / bad_path
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b'\xff\xfe')
    for route in ('/api/analyze', '/api/analysis-jobs'):
        response = webapp.app.test_client().post(route, json={
            'model_paths': [str(model)], 'report_paths': [str(report)],
        })
        assert response.status_code == 400
        assert 'Cannot read TMDL metadata' in response.json['error']
    for command in ([], ['check'], ['clean-stale']):
        result = subprocess.run([sys.executable, '-m', 'semantic_model_cleaner', *command,
                                 str(tmp_path), '--format', 'json'], capture_output=True, text=True)
        assert result.returncode == 2
        assert 'Traceback' not in result.stdout + result.stderr


@pytest.mark.parametrize('command', [[], ['check'], ['clean-stale']])
def test_invalid_model_cli_returns_input_error(tmp_path, command):
    model_project(tmp_path, {})
    result = subprocess.run([sys.executable, '-m', 'semantic_model_cleaner', *command,
                             str(tmp_path), '--format', 'json'], capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'TMDL' in result.stdout + result.stderr


@pytest.mark.parametrize('layout', ['classic', 'v2'])
def test_initial_and_discovery_scope_excludes_invalid_models_with_reasons(tmp_path, monkeypatch, layout):
    model, report = model_project(tmp_path, {})
    valid = tmp_path / 'Valid.SemanticModel'
    (valid / 'definition').mkdir(parents=True)
    (valid / 'definition/model.tmdl').write_text('model Model\n')
    monkeypatch.setattr(webapp, '_discover_initial_artifacts', lambda: ([model, valid], [report]))
    monkeypatch.setitem(webapp._state, 'model_search_roots', [str(tmp_path)])
    monkeypatch.setitem(webapp._state, 'report_search_roots', [str(tmp_path)])
    client = webapp.app.test_client()
    page = client.get('/?ui=' + layout).get_data(as_text=True)
    assert 'initialModelExclusions:' in page
    assert 'No readable TMDL model or table declaration' in page
    response = client.get('/api/discover').json
    assert [m['path'] for m in response['models']] == [str(valid)]
    assert response['modelExclusions'][0]['path'] == str(model)
    assert 'TMDL' in response['modelExclusions'][0]['message']
