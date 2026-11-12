"""Persistent reuse is data-only, content-verified and independent of file stats."""
import os

import pytest

from semantic_model_cleaner import analyzer, change_plan, insights
from test_bulk_cleanup_flow import project
from test_cli_insights import write_json


@pytest.fixture
def cached_project(tmp_path, monkeypatch):
    monkeypatch.delenv('SMC_DISABLE_ANALYSIS_CACHE', raising=False)
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'state'))
    return project(tmp_path)


def analyze(model, reports):
    return analyzer.analyze(model.parent, model_paths=[model], report_paths=reports, suggestions=False)


def test_repeated_read_commands_and_plan_reuse_content_verified_analysis(cached_project, monkeypatch, tmp_path):
    model, reports = cached_project
    cold = insights.Insights(*insights.select_scope(model.parent))
    expected = cold.items(unused=True, limit=None)
    calls = []
    original = analyzer._analyze_uncached

    def observed(*args, **kwargs):
        calls.append(kwargs['model_paths'][0])
        return original(*args, **kwargs)

    monkeypatch.setattr(analyzer, '_analyze_uncached', observed)
    warm = insights.Insights(*insights.select_scope(model.parent))
    assert warm.items(unused=True, limit=None) == expected
    assert warm.usage(table='Sales', item='Guarded') == cold.usage(table='Sales', item='Guarded')
    plan = change_plan.create_plan(model, reports, [dict(kind='actions', actions=[
        dict(action='delete', table='Sales', name='Spare', item_type='Measure')])])
    assert plan['changes']
    assert calls and all(path != model for path in calls), 'Only the changed staged scope needs fresh analysis'
    assert list((tmp_path / 'state/analysis-cache').glob('*.json.gz'))


def test_cache_invalidates_same_size_same_time_edits(cached_project, monkeypatch):
    model, reports = cached_project
    before = analyze(model, reports)
    file = model / 'definition/tables/Sales.tmdl'
    info = file.stat()
    file.write_bytes(file.read_bytes().replace(b'measure Spare = 1', b'measure Fresh = 1'))
    os.utime(file, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert file.stat().st_size == info.st_size
    after = analyze(model, reports)
    assert any(r['item'].name == 'Fresh' for r in after['items'])
    assert not any(r['item'].name == 'Fresh' for r in before['items'])
    monkeypatch.setenv('SMC_DISABLE_ANALYSIS_CACHE', '1')
    assert after == analyze(model, reports)


@pytest.mark.parametrize('mutation', ['report-edit', 'add-file', 'delete-file', 'new-report', 'binding', 'selection', 'engine'])
def test_inputs_discovery_bindings_and_options_invalidate(cached_project, tmp_path, monkeypatch, mutation):
    from semantic_model_cleaner import analysis_store
    model, reports = cached_project
    other = tmp_path / 'Other.Report'
    write_json(other / 'definition.pbir', {'datasetReference': {'byPath': {'path': '../Other.SemanticModel'}}})
    write_json(other / 'definition/report.json', {})
    analyze(model, reports)
    calls = []
    original = analyzer._analyze_uncached
    monkeypatch.setattr(analyzer, '_analyze_uncached', lambda *a, **kw: calls.append(1) or original(*a, **kw))
    if mutation == 'report-edit':
        write_json(reports[0] / 'definition/report.json', {'Column': {
            'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Amount'}})
    elif mutation == 'add-file':
        write_json(reports[0] / 'definition/extra.json', {})
    elif mutation == 'delete-file':
        (reports[0] / 'definition/reportExtensions.json').unlink()
    elif mutation == 'new-report':
        write_json(tmp_path / 'New.Report/definition.pbir', {'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}})
        write_json(tmp_path / 'New.Report/definition/report.json', {})
    elif mutation == 'binding':
        write_json(other / 'definition.pbir', {'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}})
    elif mutation == 'selection':
        reports = [*reports, other]
    else:
        monkeypatch.setattr(analysis_store, '_engine', lambda: 'different-code-or-bundled-schemas')
    actual = analyze(model, reports)
    assert calls == [1]
    monkeypatch.setenv('SMC_DISABLE_ANALYSIS_CACHE', '1')
    assert actual == analyze(model, reports)


def test_corrupt_cache_is_a_miss_and_caller_mutation_does_not_leak(cached_project, tmp_path, monkeypatch):
    model, reports = cached_project
    original = analyze(model, reports)
    original['items'].clear()
    assert analyze(model, reports)['items']
    entry = next((tmp_path / 'state/analysis-cache').glob('*.json.gz'))
    entry.write_bytes(b'corrupt compressed JSON')
    actual = analyze(model, reports)
    monkeypatch.setenv('SMC_DISABLE_ANALYSIS_CACHE', '1')
    assert actual == analyze(model, reports)


def test_change_while_loading_cache_refuses_stale_evidence(cached_project, monkeypatch):
    from semantic_model_cleaner import analysis_store
    model, reports = cached_project
    analyze(model, reports)
    original = analysis_store._load

    def changed(*args):
        result = original(*args)
        (reports[0] / 'definition/report.json').write_text('{"changed":true}', encoding='utf-8')
        return result

    monkeypatch.setattr(analysis_store, '_load', changed)
    with pytest.raises(ValueError, match='Input changed'):
        analyze(model, reports)


def test_persistent_payload_preserves_graph_and_dataclass_types(cached_project):
    model, reports = cached_project
    cold = analyze(model, reports)
    warm = analyze(model, reports)
    assert cold == warm
    assert isinstance(warm['items'][0]['item'], analyzer.ModelItem)
    assert all(isinstance(key, tuple) and isinstance(value, set)
               for key, value in warm['dependency_graphs']['measures'].items())
    assert all(isinstance(ref, analyzer.UsageRef) for ref in warm['report_references'])


def test_parse_cache_cannot_seed_a_new_content_snapshot_with_old_items(cached_project):
    model, reports = cached_project
    cache = analyzer.AnalysisCache()
    analyzer.analyze(model.parent, model_paths=[model], report_paths=reports, cache=cache, suggestions=False)
    path = model / 'definition/tables/Sales.tmdl'
    path.write_bytes(path.read_bytes().replace(b'measure Spare = 1', b'measure Fresh = 1'))
    result = analyzer.analyze(model.parent, model_paths=[model], report_paths=reports, cache=cache, suggestions=False)
    names = {row['item'].name for row in result['items']}
    assert 'Fresh' in names and 'Spare' not in names


def test_baselines_are_reapplied_after_cached_analysis(cached_project, monkeypatch):
    from semantic_model_cleaner.ci import run_check
    model, reports = cached_project
    _, first = run_check(model.parent, model_path=model, report_paths=reports)
    baseline = {'schema_version': '1.0', 'fingerprints': [f['fingerprint'] for f in first['findings']]}
    calls = []
    original = analyzer._analyze_uncached
    monkeypatch.setattr(analyzer, '_analyze_uncached', lambda *a, **kw: calls.append(1) or original(*a, **kw))
    _, second = run_check(model.parent, model_path=model, report_paths=reports, baseline=baseline)
    assert any(f['suppressed'] for f in second['findings'])
    assert not calls


def test_repeated_reference_records_preserve_types_and_independent_mutability():
    from semantic_model_cleaner import analysis_store
    # Equal locations appear in several projections; compressing them must not
    # couple those projections, or merge booleans/integers/floats in metadata.
    records = [dict((str(k), value) for k in range(10)) for value in (False, 0, 0.0)]
    original = [*records, dict(records[0])]
    restored = analysis_store._unpack(analysis_store._pack(original))
    assert restored == original
    assert [type(row['0']) for row in restored] == [bool, int, float, bool]
    restored[0]['0'] = 'caller mutation'
    assert restored[-1]['0'] is False


def test_nested_project_query_and_plan_share_discovery_boundary(cached_project, tmp_path, monkeypatch):
    model, reports = cached_project
    (tmp_path / 'Models').mkdir()
    (tmp_path / 'Reports').mkdir()
    model = model.rename(tmp_path / 'Models/M.SemanticModel')
    reports = [reports[0].rename(tmp_path / 'Reports/R.Report')]
    write_json(reports[0] / 'definition.pbir', {'datasetReference': {'byPath': {'path': '../../Models/M.SemanticModel'}}})
    extra = tmp_path / 'Archive/Other.SemanticModel/definition/tables/Other.tmdl'
    extra.parent.mkdir(parents=True)
    extra.write_text('table Other\n\tcolumn X\n', encoding='utf-8')
    insights.Insights(*insights.select_scope(tmp_path, model=model))
    calls = []
    original = analyzer._analyze_uncached
    monkeypatch.setattr(analyzer, '_analyze_uncached', lambda *a, **kw: calls.append(kw['model_paths'][0]) or original(*a, **kw))
    plan = change_plan.create_plan(model, reports, [dict(kind='actions', actions=[
        dict(action='delete', table='Sales', name='Spare', item_type='Measure')])], project_path=tmp_path)
    assert plan['changes']
    assert model not in calls, 'Planning must reuse the same PROJECT discovery boundary as the query'
