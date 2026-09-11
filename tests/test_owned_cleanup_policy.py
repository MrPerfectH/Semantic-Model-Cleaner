"""Retained report-local formulas stay distinct when authorizing model deletion."""
import json
import os

import pytest

from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


@pytest.mark.parametrize('expression,target_type,target_name', [
    ('[First]', 'Measure', 'First'),
    ('SUM(Sales[Amount])', 'Column', 'Amount'),
    ('COUNTROWS(Sales)', 'Table', 'Sales'),
    ("COUNTROWS('Sales')", 'Table', 'Sales'),
])
def test_retained_same_named_report_measure_blocks_model_dependency_deletion(tmp_path, expression, target_type, target_name):
    model = tmp_path / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tmeasure First = 1\n\tmeasure Second = 2\n\tcolumn Amount\n\t\tdataType: int64\n')
    reports = []
    for owner, dax in [('a', expression), ('b', '[Second]')]:
        report = tmp_path / owner / 'Same.Report'
        definition = report / 'definition'
        definition.mkdir(parents=True)
        (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': os.path.relpath(model, report)}}}))
        (definition / 'report.json').write_text('{}')
        (definition / 'reportExtensions.json').write_text(json.dumps({'entities': [{'name': 'Sales', 'measures': [{'name': 'Local', 'expression': dax}]}]}))
        reports.append(report)
    result = evaluate_deletion_policy(model, reports, [
        {'action': 'delete', 'item_type': target_type, 'table': 'Sales', 'name': target_name}])
    assert not result['ok']
    retained = [v for v in result['violations'] if v['rule_id'] == 'SMC-D006']
    assert any('Local' in v['message'] and str(reports[0]) in v['message'] for v in retained), result
