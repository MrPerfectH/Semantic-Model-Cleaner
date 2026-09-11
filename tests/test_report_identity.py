"""Stable report artifact identities across scans, payloads and cleanup entries."""
import json
from pathlib import Path
import shutil

import pytest

from semantic_model_cleaner import analyzer, webapp


def project(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n\tmeasure Spare = 1\n')
    reports = []
    for parent in ('A', 'B'):
        report = tmp_path / parent / 'Same.Report'
        visual = report / 'definition/pages/P/visuals/V/visual.json'
        visual.parent.mkdir(parents=True)
        visual.write_text(json.dumps({'visual': {'query': {'Measure': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Revenue'}, 'Missing': {'Measure': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Gone'}}}, 'objects': {'labels': [{'selector': {'metadata': 'Sales.Spare'}}]}}}))
        (report / 'definition/report.json').write_text('{}')
        reports.append(report)
    return model, reports


def test_same_named_reports_keep_distinct_issues_live_stale_and_cleanup_owners(tmp_path):
    model, reports = project(tmp_path)
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    expected = {str(p.resolve()) for p in reports}
    missing = [issue for issue in results['report_issues'] if issue['issueType'] == 'missing_measure']
    assert len(missing) == 2
    assert {issue['reportPath'] for issue in missing} == expected
    payload = webapp._serialize_results(results)
    revenue = next(item for item in payload['items'] if item['name'] == 'Revenue')
    spare = next(item for item in payload['items'] if item['name'] == 'Spare')
    assert revenue['reportCount'] == 2 and revenue['pageCount'] == 2
    assert {ref['reportPath'] for ref in revenue['usageDetails']} == expected
    assert {ref['reportPath'] for ref in spare['staleUsageDetails']} == expected
    assert {ref['reportPath'] for ref in payload['references'] if ref['report']} == expected
    assert {issue['reportPath'] for issue in payload['reportIssues']} == expected
    entries = analyzer.build_stale_cleanup_entries(results, reports)
    assert {entry['report_path'] for entry in entries} == expected
    foreign = {**results['report_issues'][0], 'reportPath': '/outside/Foreign.Report'}
    assert analyzer.stale_cleanup_entry(foreign, analyzer.report_path_index(reports)) is None


def test_invalid_json_issue_scanners_keep_exact_report_owner(tmp_path):
    model, reports = project(tmp_path)
    for report in reports:
        (report / 'definition/report.json').write_text('{invalid')
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    invalid = [issue for issue in results['report_issues'] if issue['issueType'] == 'invalid_report_json']
    assert len(invalid) == 2
    assert {issue['reportPath'] for issue in invalid} == {str(p.resolve()) for p in reports}


def test_synthetic_field_parameter_usages_inherit_report_identity(tmp_path):
    demo = Path(__file__).parents[1] / 'src/semantic_model_cleaner/demo_workspace'
    root = tmp_path / 'demo'
    shutil.copytree(demo, root)
    model = next(root.rglob('*.SemanticModel'))
    first = next(root.rglob('*.Report'))
    second = root / 'Other' / first.name
    shutil.copytree(first, second)
    results = analyzer.analyze(root, model_paths=[model], report_paths=[first, second])
    revenue = next(row for row in results['items'] if row['item'].name == 'Revenue')
    synthetic = [ref for ref in revenue['usages'] if ref.context == 'Field Parameter']
    assert synthetic
    assert {ref.report_path for ref in synthetic} == {str(first.resolve()), str(second.resolve())}
    assert all(ref.artifact_path and ref.source_path for ref in synthetic)


def extension(report, name, expression):
    path = report / 'definition/reportExtensions.json'
    path.write_text(json.dumps({'name': 'extension', 'entities': [{'name': 'Sales', 'measures': [{'name': name, 'expression': expression}]}]}))


def test_same_named_report_extensions_keep_independent_formulas_and_usage(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], 'Local', '[Revenue]')
    extension(reports[1], 'Local', '[Spare]')
    visual = reports[0] / 'definition/pages/P/visuals/V/visual.json'
    visual.write_text(visual.read_text().replace('Revenue', 'Local'))
    other_visual = reports[1] / 'definition/pages/P/visuals/V/visual.json'
    other_visual.write_text('{}')
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    assert results['coverage']['complete']
    local = [row for row in results['items'] if row['item'].name == 'Local']
    assert len(local) == 2
    assert local[0]['status'] == 'USED'
    assert local[1]['status'] == 'NOT USED'
    model_rows = {row['item'].name: row for row in results['items'] if row['item'].source_kind == 'model'}
    assert model_rows['Revenue']['status'].startswith('INDIRECT')
    assert model_rows['Amount']['status'].startswith('INDIRECT')
    assert model_rows['Spare']['status'] == 'NOT USED'
    payload = webapp._serialize_results(results, model_paths=[model])
    owned = [row for row in payload['items'] if row['name'] == 'Local']
    assert [row['dependsOnMeasures'] for row in owned] == [['Sales[Revenue]'], ['Sales[Spare]']]
    assert [row['usageState'] for row in owned] == ['Used', 'Unused']
    nested = [row for row in payload['tables'][0]['items'] if row['name'] == 'Local']
    assert {row['sourceFile'] for row in nested} == {row['sourceFile'] for row in owned}
    assert [row['usageState'] for row in nested] == ['Used', 'Unused']
    revenue = next(row for row in payload['items'] if row['name'] == 'Revenue')
    assert revenue['dependentItems'] == [{'type': 'Measure', 'table': 'Sales', 'name': 'Local',
                                         'sourceKind': 'report', 'sourceFile': owned[0]['sourceFile']}]
    refs = [row for row in payload['references'] if row['name'] == 'Local']
    assert {row['sourceFile']: row['usageState'] for row in refs} == {row['sourceFile']: row['usageState'] for row in owned}


def test_model_report_collision_preserves_both_formulas_and_blocks_coverage(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], 'Revenue', '[Spare]')
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    assert not results['coverage']['complete']
    assert any(issue['issueType'] == 'ambiguous_extension_identity' for issue in results['report_issues'])
    rows = [row for row in results['items'] if row['item'].name == 'Revenue']
    assert len(rows) == 2
    graphs = results['dependency_graphs']
    by_kind = {row['item'].source_kind: analyzer.item_identity(row['item']) for row in rows}
    assert {key[-1] for key in graphs['columns'][by_kind['model']]} == {'Amount'}
    assert not graphs['measures'][by_kind['model']]
    assert {key[-1] for key in graphs['measures'][by_kind['report']]} == {'Spare'}
    assert not graphs['columns'][by_kind['report']]
    payload = webapp._serialize_results(results, model_paths=[model])
    owned = {row['sourceKind']: row for row in payload['items'] if row['name'] == 'Revenue'}
    assert owned['model']['dependsOnColumns'] == ['Sales[Amount]']
    assert owned['report']['dependsOnMeasures'] == ['Sales[Spare]']
    assert owned['model']['reportCount'] == 2
    assert owned['report']['reportCount'] == 1


def test_same_named_extensions_do_not_share_broken_dax_diagnostics(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], 'Local', '[Gone]')
    extension(reports[1], 'Local', '[Revenue]')
    rows = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)['items']
    local = [row for row in rows if row['item'].name == 'Local']
    assert local[0]['broken_dax_refs'] == ['[Gone]']
    assert not local[1]['broken_dax_refs']


def test_duplicate_declarations_within_one_report_remain_unsupported(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], 'Local', '1')
    path = reports[0] / 'definition/reportExtensions.json'
    data = json.loads(path.read_text())
    data['entities'][0]['measures'].append({'name': 'Local', 'expression': '2'})
    path.write_text(json.dumps(data))
    with pytest.raises(analyzer.UnsupportedSemanticModelError, match='within one report'):
        analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)


def test_report_extension_is_not_available_to_another_report_or_model(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], 'OnlyInA', '[Revenue]')
    extension(reports[1], 'OnlyInB', '[OnlyInA]')
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text() + '\tmeasure InvalidModelReference = [OnlyInA]\n')
    visual = reports[1] / 'definition/pages/P/visuals/V/visual.json'
    visual.write_text(visual.read_text().replace('Revenue', 'OnlyInA'))
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    local_a = next(row for row in results['items'] if row['item'].name == 'OnlyInA')
    assert not local_a['usages']
    for name in ('OnlyInB', 'InvalidModelReference'):
        row = next(row for row in results['items'] if row['item'].name == name)
        assert row['broken_dax_refs'], name
    assert any(issue['name'] == 'OnlyInA' and issue['reportPath'] == str(reports[1].resolve())
               for issue in results['report_issues'])

def test_model_broken_formula_does_not_leak_into_valid_same_named_local(tmp_path):
    model, reports = project(tmp_path)
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text().replace('SUM(Sales[Amount])', '[MissingModelMeasure]'))
    extension(reports[0], 'Revenue', '[Spare]')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    same_named = {row['item'].source_kind: row for row in result['items'] if row['item'].name == 'Revenue'}
    assert same_named['model']['broken_dax_refs'] == ['[MissingModelMeasure]']
    assert not same_named['report']['broken_dax_refs']


def test_model_local_ambiguity_is_nonsuppressible_ci_coverage_finding(tmp_path):
    from semantic_model_cleaner.ci import run_check
    model, reports = project(tmp_path)
    extension(reports[0], 'Revenue', '[Spare]')
    for report in reports:
        (report / 'definition.pbir').write_text(json.dumps({
            'version': '4.0', 'datasetReference': {'byPath': {'path': '../../M.SemanticModel'}}}))
    _, first = run_check(tmp_path, model_path=model, report_paths=reports)
    ambiguity = [finding for finding in first['findings'] if finding['rule_id'] == 'SMC002']
    assert ambiguity
    code, checked = run_check(tmp_path, model_path=model, report_paths=reports,
                              baseline={'schema_version': '1.0', 'fingerprints': [finding['fingerprint'] for finding in first['findings']]})
    assert code == 1
    assert not checked['scope']['scan_complete']
    assert all(not finding['suppressed'] for finding in checked['findings'] if finding['rule_id'] == 'SMC002')

def test_bare_unquoted_table_dependencies_ignore_literals_comments_and_qualified_columns():
    column = analyzer.ModelItem(item_type='Column', table='Sales', name='Amount')
    measure = analyzer.ModelItem(item_type='Measure', table='Metrics', name='Count', dax_body='COUNTROWS(Sales)')
    assert analyzer.build_dax_table_deps([column, measure])[measure.key] == {'Sales'}
    for formula in ('SUM(Sales[Amount])', '"Sales"', '1 // Sales', '1 /* Sales */', 'Sales(1)', '[Sales]'):
        measure.dax_body = formula
        assert not analyzer.build_dax_table_deps([column, measure])[measure.key], formula

def test_local_empty_formula_does_not_inherit_same_named_model_edges():
    items = [analyzer.ModelItem(item_type='Column', table='Sales', name='Amount'),
             analyzer.ModelItem(item_type='Measure', table='Sales', name='Revenue', dax_body='SUM(Sales[Amount])'),
             analyzer.ModelItem(item_type='Measure', table='Sales', name='Revenue', dax_body='',
                                source_kind='report', source_file='/tmp/Owned.Report/definition/reportExtensions.json')]
    graph = analyzer.scoped_dependency_graphs(items)
    assert graph['columns'][analyzer.item_identity(items[1])]
    assert not graph['columns'][analyzer.item_identity(items[2])]
