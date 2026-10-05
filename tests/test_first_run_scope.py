"""First-run scope preview is read-only and shares analysis binding rules."""
import json
from pathlib import Path
import shutil

from semantic_model_cleaner import analyzer, webapp


def project(tmp_path):
    root = tmp_path / 'project'
    shutil.copytree(Path(webapp.__file__).parent / 'demo_workspace', root)
    model = next(root.rglob('*.SemanticModel'))
    report = next(root.rglob('*.Report'))
    return root, model, report


def test_scope_preview_excludes_unrelated_reports_without_changing_state(tmp_path):
    root, model, report = project(tmp_path)
    unrelated = root / 'Other.Report'
    shutil.copytree(report, unrelated)
    (unrelated / 'definition.pbir').write_text(json.dumps({
        'datasetReference': {'byPath': {'path': '../Other.SemanticModel'}}}), encoding='utf-8')
    before_state = webapp._state.copy()
    before_files = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = webapp.app.test_client().post('/api/scope', json={
        'model_paths': [str(model)], 'report_paths': [str(report), str(unrelated)]})
    assert result.status_code == 200
    assert result.json['reportBinding'] == analyzer.report_binding_scope(model, [report, unrelated])
    assert len(result.json['reportBinding']['selected']) == 1
    assert len(result.json['reportBinding']['excluded']) == 1
    assert webapp._state == before_state
    assert all(p.read_bytes() == data for p, data in before_files.items())


def test_ambiguous_startup_requires_explicit_model_choice(tmp_path, monkeypatch):
    root, model, report = project(tmp_path)
    other = model.with_name('Other.SemanticModel')
    shutil.copytree(model, other)
    monkeypatch.setattr(webapp, '_discover_initial_artifacts', lambda: ([model, other], [report]))
    assert webapp._default_model_selection([model, other]) == []
    for layout in ('v2', 'classic'):
        response = webapp.app.test_client().get('/?ui=' + layout)
        assert response.status_code == 200
        assert b'initialModels: []' in response.data
        assert b'Other.SemanticModel' in response.data
        assert b'first-run.js' in response.data


def test_scope_preview_rejects_unsupported_or_missing_model(tmp_path):
    client = webapp.app.test_client()
    for models in ([], [str(tmp_path / 'absent.SemanticModel')], ['one', 'two']):
        response = client.post('/api/scope', json={'model_paths': models, 'report_paths': []})
        assert response.status_code == 400
        assert response.json['error']


def test_discovery_pbix_only_has_no_proposed_model(tmp_path):
    (tmp_path / 'Report.pbix').write_bytes(b'disposable placeholder')
    response = webapp.app.test_client().post('/api/discover', json={
        'model_roots': [str(tmp_path)], 'report_roots': [str(tmp_path)]})
    assert response.status_code == 200
    assert response.json['models'] == []
    assert response.json['reports'] == []
