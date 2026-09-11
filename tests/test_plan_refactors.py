"""Cross-artifact plan QA; may run against an integration tree via PYTHONPATH."""
import json

import pytest

from semantic_model_cleaner import change_plan as plans


def project(tmp_path):
    model = tmp_path / 'Model area' / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tcolumn Amount\n\t\tdataType: decimal\n\tmeasure Revenue = SUM(Sales[Amount])\n\tmeasure Derived = [Revenue] + 1\n')
    (tables / 'Measures.tmdl').write_text('table Measures\n\tmeasure Constant = 1\n')
    reports = []
    for folder in ('Reports Z', 'Reports A'):
        report = tmp_path / folder / 'Same name.Report'
        definition = report / 'definition'
        visual = definition / 'pages/P/visuals/V/visual.json'
        visual.parent.mkdir(parents=True)
        visual.write_text(json.dumps({'visual': {'query': {'Measure': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Revenue'}, 'Column': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Amount'}}}}))
        (definition / 'report.json').write_text('{}')
        (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../../Model area/M.SemanticModel'}}}))
        reports.append(report)
    return model, reports


def round_trip(tmp_path, model, reports, operations):
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    plan = plans.create_plan(model, reports, operations)
    assert plan['changes']
    assert plans._inventory(roots) == before
    assert plans.verify_plan(plan)['state'] == 'original'
    applied = plans.apply_plan(plan, tmp_path / 'journal')
    assert applied['ok'], applied
    assert plans.verify_plan(plan)['state'] == 'applied'
    after = plans._inventory(roots)
    restored = plans.restore_plan(plan, tmp_path / 'journal')
    assert restored['ok'], restored
    assert plans._inventory(roots) == before
    assert plans.verify_plan(plan)['state'] == 'original'
    return plan, after


@pytest.mark.parametrize('operation', [
    {'kind': 'rename', 'table_renames': [{'table': 'Sales', 'target_table': 'Fact Sales'}]},
    {'kind': 'rename', 'measure_renames': [{'table': 'Sales', 'name': 'Revenue', 'target_name': 'Net Revenue'}]},
    {'kind': 'rename', 'column_renames': [{'table': 'Sales', 'name': 'Amount', 'target_name': 'Net Amount'}]},
    {'kind': 'rename', 'table_renames': [{'table': 'Sales', 'target_table': 'Fact Sales'}],
     'measure_renames': [{'table': 'Sales', 'name': 'Revenue', 'target_name': 'Net Revenue'}],
     'column_renames': [{'table': 'Sales', 'name': 'Amount', 'target_name': 'Net Amount'}]},
    {'kind': 'move', 'moves': [{'table': 'Sales', 'name': 'Revenue', 'target_table': 'Measures'}]},
])
def test_plan_refactor_round_trip_across_same_named_reports(tmp_path, operation):
    model, reports = project(tmp_path)
    plan, _ = round_trip(tmp_path, model, reports, [operation])
    assert {change['artifact'] for change in plan['changes']} >= {'model', 'report-1', 'report-2'}


def test_promotion_explicit_report_path_maps_to_correct_same_named_report(tmp_path):
    model, reports = project(tmp_path)
    extension = reports[0] / 'definition/reportExtensions.json'
    extension.write_text(json.dumps({'name': 'extension', 'entities': [{'name': 'Sales', 'measures': [
        {'name': 'Local Base', 'expression': '[Revenue] + 1'},
        {'name': 'Local Derived', 'expression': '[Local Base] + 1'}]}]}))
    plan, after = round_trip(tmp_path, model, reports, [{'kind': 'promote', 'report_path': str(reports[0]),
        'table': 'Sales', 'name': 'Local Derived', 'include_dependencies': True}])
    target_key = next(key for key, path in plan['scope'].items() if path == str(reports[0].resolve()))
    assert {change['artifact'] for change in plan['changes']} == {'model', target_key}
    assert b"measure 'Local Base'" in after['model/definition/tables/Sales.tmdl']
    assert b"measure 'Local Derived'" in after['model/definition/tables/Sales.tmdl']


def test_report_repair_round_trip_and_existing_error_reduction(tmp_path):
    model, reports = project(tmp_path)
    visual = reports[0] / 'definition/pages/P/visuals/V/visual.json'
    visual.write_text(visual.read_text().replace('Sales', 'Legacy Sales'))
    plan, _ = round_trip(tmp_path, model, reports, [{'kind': 'report_repair', 'report_paths': [str(reports[0])],
        'table_renames': [{'table': 'Legacy Sales', 'target_table': 'Sales'}]}])
    assert plan['validation']['remaining_problem_count'] < plan['validation']['existing_problem_count']
    assert {change['artifact'] for change in plan['changes']} == {'report-2'}


def test_explicit_source_file_survives_staging_and_combined_table_rename(tmp_path):
    model, reports = project(tmp_path)
    round_trip(tmp_path, model, reports, [{'kind': 'rename',
        'table_renames': [{'table': 'Sales', 'target_table': 'Fact Sales'}],
        'measure_renames': [{'table': 'Sales', 'name': 'Revenue', 'target_name': 'Net Revenue',
                            'source_file': str(model / 'definition/tables/Sales.tmdl')}]}])


def test_rename_unrelated_existing_broken_measure_does_not_invent_new_error(tmp_path):
    model, reports = project(tmp_path)
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text() + '\tmeasure AlreadyBroken = [MissingMeasure]\n')
    round_trip(tmp_path, model, reports, [{'kind': 'rename',
        'measure_renames': [{'table': 'Sales', 'name': 'AlreadyBroken', 'target_name': 'StillBroken'}]}])


def test_same_named_reports_do_not_hide_new_broken_reference(tmp_path):
    model, reports = project(tmp_path)
    first = reports[0] / 'definition/pages/P/visuals/V/visual.json'
    first.write_text(first.read_text().replace('Revenue', 'MissingMeasure'))
    with pytest.raises(plans.PlanError, match='unresolved references'):
        plans.create_plan(model, reports, [{'kind': 'report_repair', 'report_paths': [str(reports[1])],
            'measure_renames': [{'table': 'Sales', 'name': 'Revenue', 'target_name': 'MissingMeasure'}]}])
