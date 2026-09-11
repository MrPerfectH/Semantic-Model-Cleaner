import importlib.util
import json
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer


def script(name):
    path = Path(__file__).parents[1] / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('count', [2000, 10000])
def test_generator_creates_exact_item_counts_and_bound_reports(tmp_path, count):
    generator = script('generate_scale_fixture')
    target = tmp_path / 'generated'
    result = generator.generate_fixture(target, items=count, reports=1, pages_per_report=1, visuals_per_page=1)
    model = analyzer.discover_models([target])[0]
    report = analyzer.discover_reports([target])[0]
    assert len(analyzer.parse_model_items(model)) == count
    assert analyzer.report_binding_status(report, model)['status'] == 'connected'
    assert len(analyzer.parse_relationship_details(model)) == count // 100 - 1
    assert analyzer.parse_rls_roles(model)
    analyzed = analyzer.analyze(target, model_paths=[model], report_paths=[report])
    assert analyzed['coverage']['complete']
    assert analyzed['summary']['total_usage_refs'] == 2
    assert result['calculated_columns'] == count // 20


def test_generator_refuses_existing_directory_and_symlink(tmp_path):
    generator = script('generate_scale_fixture')
    target = tmp_path / 'existing'
    target.mkdir()
    sentinel = target / 'untouched.txt'
    sentinel.write_text('untouched')
    with pytest.raises(ValueError, match='already exists'):
        generator.generate_fixture(target)
    assert sentinel.read_text() == 'untouched'
    linked = tmp_path / 'linked'
    linked.symlink_to(tmp_path / 'missing')
    with pytest.raises(ValueError, match='symlinks'):
        generator.generate_fixture(linked)
    assert not (tmp_path / 'missing').exists()


def test_benchmark_outputs_counts_without_customer_content(tmp_path, monkeypatch, capsys):
    benchmark = script('benchmark_repository')
    model, report = tmp_path / 'private-model', tmp_path / 'private-report'
    monkeypatch.setattr(benchmark.analyzer, 'discover_models', lambda roots: [model])
    monkeypatch.setattr(benchmark.analyzer, 'discover_reports', lambda roots: [report])
    monkeypatch.setattr(benchmark.analyzer, 'filter_reports_bound_to_model', lambda reports, model: reports)
    def analyze(*args, **kwargs):
        print('DO-NOT-LOG-CUSTOMER-VALUES')
        return {'items': [{}, {}], 'table_summaries': [{}], 'summary': {'total_usage_refs': 1},
                'report_issues': [], 'warnings': [], 'coverage': {'complete': True}}
    monkeypatch.setattr(benchmark.analyzer, 'analyze', analyze)
    monkeypatch.setattr(benchmark.webapp, '_serialize_results', lambda result, model_paths=None: {'private': 'DO-NOT-LOG-CUSTOMER-VALUES', 'references': [1, 2]})
    def compact(payload):
        payload.pop('references')
        return payload
    monkeypatch.setattr(benchmark.webapp, '_compact_browser_results', compact, raising=False)
    monkeypatch.setattr(benchmark, '_peak_rss_bytes', lambda: 100)
    assert benchmark.main([str(tmp_path), '--repeats', '2']) == 0
    text = capsys.readouterr().out
    assert 'DO-NOT-LOG-CUSTOMER-VALUES' not in text and str(tmp_path) not in text
    result = json.loads(text)
    assert result['counts']['model_items'] == 2 and result['repeats'] == 2
    assert result['medians']['full_json_bytes'] > result['medians']['compact_json_bytes']
    assert result['peak_rss_bytes'] == 100


def test_benchmark_exception_does_not_print_private_error_message(tmp_path, monkeypatch, capsys):
    benchmark = script('benchmark_repository')
    def failure(*args, **kwargs):
        raise ValueError('private names must stay local')
    monkeypatch.setattr(benchmark, 'benchmark_repository', failure)
    assert benchmark.main([str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out) == {'schema_version': '1.0', 'ok': False, 'error_type': 'ValueError'}
