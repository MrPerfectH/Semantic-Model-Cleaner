"""DEFINE MEASURE ownership survives local shadowing and snapshot memoization."""
import pytest
from semantic_model_cleaner import analyzer, change_plan as plans
from semantic_model_cleaner.saved_dax import query_references
from test_report_measure_delete import project, extension, operation
from test_report_measure_coverage import query

QUERIES = [
    'DEFINE MEASURE Sales[Local] = 1 EVALUATE {[Local]}',
    'DEFINE MEASURE Sales[Local] = 1 EVALUATE {1}',
    "DEFINE MEASURE 'Sales'[Revenue] = 1 EVALUATE {[Revenue]}",
]


def fixture(tmp_path, item_type='Measure'):
    model, reports = project(tmp_path)
    declaration = 'measure Revenue = 1' if item_type == 'Measure' else 'column Revenue'
    (model / 'definition/tables/Sales.tmdl').write_text('table Sales\n\t' + declaration + '\n')
    (model / 'definition/tables/Keep.tmdl').write_text('table Keep\n\tmeasure Keeper = 2\n\tmeasure Spare = 3\n')
    for report in reports:
        (report / 'definition/reportExtensions.json').unlink()
    return model, reports


def deletion(table='Sales', name='Revenue', item_type='Measure'):
    return {'kind': 'actions', 'actions': [
        {'action': 'delete', 'table': table, 'name': name, 'item_type': item_type}]}


@pytest.mark.parametrize('text', QUERIES)
@pytest.mark.parametrize('item_type', ['Measure', 'Column'])
def test_define_owner_blocks_last_item_and_table_disappearance(tmp_path, text, item_type):
    model, reports = fixture(tmp_path, item_type)
    path = query(reports[0], text)
    assert query_references(text) == [('Sales', None)]
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    cache = analyzer.AnalysisCache()
    for selected in (reports, [reports[0]], reports):
        result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=selected, cache=cache)
        assert result['coverage']['complete']
        row = next(r for r in result['items'] if r['item'].table == 'Sales')
        assert row['removal_risk'] != 'Safe'
        assert row['usages']
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [deletion(item_type=item_type)])
    assert plans._inventory(roots) == before
    assert path.read_text() == text


@pytest.mark.parametrize('text', QUERIES)
def test_owner_preserving_cleanup_plan_apply_verify_restore(tmp_path, text):
    model, reports = fixture(tmp_path)
    path = query(reports[0], text)
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    plan = plans.create_plan(model, reports, [deletion('Keep', 'Spare')])
    assert 'report-1/DAXQueries/query.dax' in plan['inputs']
    assert plans.apply_plan(plan, tmp_path / 'journal')['ok']
    assert plans.verify_plan(plan)['ok']
    assert (model / 'definition/tables/Sales.tmdl').read_bytes() == before['model/definition/tables/Sales.tmdl']
    assert path.read_text() == text
    assert plans.restore_plan(plan, tmp_path / 'journal')['ok']
    assert plans._inventory(roots) == before


def test_unresolved_define_owner_fails_closed_in_own_report(tmp_path):
    model, reports = fixture(tmp_path)
    for report in reports:
        extension(report, [('Sales', 'Unused', '1')])
    query(reports[0], 'DEFINE MEASURE Missing[Local] = 1 EVALUATE {[Local]}')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    assert not result['coverage']['complete']
    limitation = next(v for v in result['coverage']['limitations'] if v['kind'] == 'unsupported_saved_dax_query')
    assert 'owner table cannot be resolved' in limitation['message']
    assert 'DAXQueries/query.dax' in limitation['location']
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    assert plans.create_plan(model, reports, [operation(reports[1], 'Unused')])['changes']


def test_define_owner_does_not_require_report_local_namesake(tmp_path):
    model, reports = fixture(tmp_path)
    extension(reports[0], [('Sales', 'Local', '1')])
    query(reports[0], 'DEFINE MEASURE Sales[Local] = 1 EVALUATE {[Local]}')
    plan = plans.create_plan(model, reports, [operation(reports[0], 'Local')])
    assert all(change['artifact'] != 'model' for change in plan['changes'])
    assert plans.apply_plan(plan, tmp_path / 'journal')['ok']
    assert plans.verify_plan(plan)['ok']
    assert plans.restore_plan(plan, tmp_path / 'journal')['ok']


def test_literal_and_comment_declarations_do_not_create_owner_dependencies():
    assert query_references('EVALUATE ROW("DEFINE MEASURE Sales[X] = 1", 1) // DEFINE MEASURE Ghost[Y] = 1') == []
    assert query_references("DEFINE MEASURE 'It''s'[X] = 1 EVALUATE {[X]}") == [("It's", None)]

@pytest.mark.parametrize('text', QUERIES)
def test_define_owner_blocks_explicit_whole_table_delete(tmp_path, text):
    model, reports = fixture(tmp_path)
    query(reports[0], text)
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [deletion(item_type='Table')])
    assert plans._inventory(roots) == before


@pytest.mark.parametrize('text', QUERIES)
def test_rename_cannot_strand_define_owner(tmp_path, text):
    model, reports = fixture(tmp_path)
    path = query(reports[0], text)
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    with pytest.raises(plans.PlanError, match='unresolved references'):
        plans.create_plan(model, reports, [{'kind': 'rename', 'table_renames': [
            {'table': 'Sales', 'target_table': 'Renamed'}]}])
    assert plans._inventory(roots) == before
    assert path.read_text() == text
