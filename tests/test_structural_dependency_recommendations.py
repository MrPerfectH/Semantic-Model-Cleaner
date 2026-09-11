"""Retained sort/hierarchy consumers must agree with deletion recommendations."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan, cleanup_policy, webapp


def project(tmp_path, dependency='sort'):
    model = tmp_path / 'M.SemanticModel'
    report = tmp_path / 'R.Report'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    source = tables / 'Sales.tmdl'
    source.write_text('table Sales\n\tcolumn Spare\n\t\tdataType: int64\n\tcolumn Label\n'
                      + ('\t\tsortByColumn: Spare\n' if dependency == 'sort' else
                         '\thierarchy Geo\n\t\tlevel Label\n\t\t\tcolumn: Spare\n'))
    (report / 'definition').mkdir(parents=True)
    (report / 'definition/report.json').write_text('{}')
    (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}}))
    (model / '.platform').write_text('{"metadata":{"displayName":"M"}}')
    return model, report, source


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def delete(name):
    return {'action': 'delete', 'table': 'Sales', 'name': name, 'item_type': 'Column'}


@pytest.mark.parametrize('dependency', ['sort', 'hierarchy'])
def test_unused_structural_target_is_blocked_consistently_without_changing_cli_usage(tmp_path, dependency):
    model, report, _ = project(tmp_path, dependency)
    original = snapshot(tmp_path)
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    target = next(row for row in result['items'] if row['item'].name == 'Spare')
    assert target['status'] == 'NOT USED'
    assert target['removal_risk'] == 'Caution'
    assert any(dependency in reason.lower() for reason in target['review_triggers'])
    assert result['summary']['not_used'] == 2
    payload = webapp._serialize_results(result, model_paths=[str(model)])
    views = [payload['items'], payload['references'], payload['tables'][0]['items']]
    for rows in views:
        item = next(item for item in rows if item['name'] == 'Spare')
        assert item['usageState'] == 'Indirect'
        assert item['removalRisk'] == 'Caution'
        assert item['deleteSafety'] == 'Blocked'
    assert payload['tables'][0]['cleanupCounts'] == {'Safe': 1, 'Review': 0, 'Blocked': 1, 'Keep': 0}
    assert payload['summary']['not_used'] == sum(item['usageState'] == 'Unused' for item in payload['items']) == 1
    assert payload['summary']['indirect'] == 1
    assert payload['tables'][0]['unusedItemCount'] == 1
    assert payload['tables'][0]['usedItemCount'] == 1
    assert payload['tables'][0]['usageState'] == 'Indirect'
    assert result['summary']['not_used'] == 2
    assert result['summary']['indirect'] == 0
    assert result['table_summaries'][0]['unused_item_count'] == 2
    assert json.loads(analyzer.format_json_output(result))['summary']['not_used'] == 2
    rejected = cleanup_policy.evaluate_deletion_policy(model, [report], [delete('Spare')])
    assert not rejected['ok']
    assert any(v['rule_id'] == 'SMC-D006' for v in rejected['violations'])
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, [report], [{'kind': 'actions', 'actions': [delete('Spare')]}])
    assert snapshot(tmp_path) == original


@pytest.mark.parametrize('used_source', ['First', 'Last'])
def test_every_sort_source_contributes_usage_regardless_of_declaration_order(tmp_path, used_source):
    model, report, source = project(tmp_path)
    source.write_text('table Sales\n\tcolumn Spare\n\t\tdataType: int64\n'
                      '\tcolumn First\n\t\tsortByColumn: Spare\n'
                      '\tcolumn Last\n\t\tsortByColumn: Spare\n')
    visual = report / 'definition/pages/P/visuals/V/visual.json'
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({'visual': {'query': {'Column': {
        'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': used_source}}}}))
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    target = next(row for row in result['items'] if row['item'].name == 'Spare')
    assert target['status'] == f'USED (Sort Column for: {used_source})'
    payload = webapp._serialize_results(result, model_paths=[str(model)])
    assert next(item for item in payload['items'] if item['name'] == 'Spare')['deleteSafety'] == 'Blocked'


def test_sort_deletion_requires_every_source_but_allows_reviewed_complete_group(tmp_path):
    model, report, source = project(tmp_path / 'project')
    source.write_text(source.read_text() + '\tcolumn Second\n\t\tsortByColumn: Spare\n\tcolumn Keep\n')
    original = snapshot(tmp_path / 'project')
    partial = [delete('Spare'), delete('Label')]
    assert not cleanup_policy.evaluate_deletion_policy(model, [report], partial)['ok']
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, [report], [{'kind': 'actions', 'actions': partial}])
    complete = partial + [delete('Second')]
    assert cleanup_policy.evaluate_deletion_policy(model, [report], complete)['ok']
    plan = change_plan.create_plan(model, [report], [{'kind': 'actions', 'actions': complete}])
    assert plan['changes']
    assert snapshot(tmp_path / 'project') == original
    assert change_plan.apply_plan(plan, tmp_path / 'journal')['ok']
    assert change_plan.verify_plan(plan)['state'] == 'applied'
    assert source.read_text() == 'table Sales\n\tcolumn Keep\n'
    assert (model / '.platform').read_bytes() == original['M.SemanticModel/.platform']
    assert change_plan.restore_plan(plan, tmp_path / 'journal')['ok']
    assert snapshot(tmp_path / 'project') == original
