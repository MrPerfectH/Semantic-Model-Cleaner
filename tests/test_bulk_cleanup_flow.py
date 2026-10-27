"""One model and connected Reports: listing, bulk plan and exact verification."""
from semantic_model_cleaner import change_plan, insights
from test_cli_insights import write_json


def project(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text(
        'table Sales\n\tcolumn Amount\n\tcolumn Guarded\n'
        '\tmeasure Retained = SUM(Sales[Guarded])\n\t\tisHidden\n'
        '\tmeasure ExtensionTarget = 1\n\tmeasure ParameterTarget = 1\n'
        '\tmeasure Spare = 1\n\tmeasure Leaf = 1\n\tmeasure Top = [Leaf]\n', encoding='utf-8')
    (tables / 'Links.tmdl').write_text('table Links\n\tcolumn Value\n', encoding='utf-8')
    (tables / 'FP.tmdl').write_text(
        'table FP\n\tcolumn Label\n\tcolumn Fields\n\tcolumn Order\n'
        '\tpartition FP = calculated\n\t\tmode: import\n\t\tsource = {("Target", NAMEOF(Sales[ParameterTarget]), 0)}\n', encoding='utf-8')
    report = tmp_path / 'R.Report'
    write_json(report / 'definition.pbir', {'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}})
    write_json(report / 'definition/report.json', {})
    write_json(report / 'definition/reportExtensions.json', {'name': 'extension', 'entities': [
        {'name': 'Sales', 'measures': [{'name': 'Local', 'expression': '[ExtensionTarget]'}]}]})
    write_json(report / 'definition/pages/P/page.json', {'name': 'P', 'displayName': 'Weekly'})
    write_json(report / 'definition/pages/P/visuals/V/visual.json', {'visual': {
        'visualContainerObjects': {'visualLink': [{'properties': {'webUrl': {'expr': {'Measure': {
            'Expression': {'SourceRef': {'Entity': 'Links'}}, 'Property': 'MissingUrl'}}}}}]}}})
    return model, [report]


def listing(model):
    return insights.Insights(*insights.select_scope(model.parent))


def actions(items):
    return [dict(action='delete', table=row['table'], name=row['name'], item_type=row['type']) for row in items]


def test_every_safe_unused_item_can_be_planned_in_one_batch(tmp_path):
    model, reports = project(tmp_path)
    rows = listing(model).items(unused=True, limit=None)['items']['items']
    safe = [row for row in rows if row['cleanup'] == 'Safe']
    assert any(row['name'] == 'Spare' for row in safe)
    plan = change_plan.create_plan(model, reports, [{'kind': 'actions', 'actions': actions(safe)}])
    assert plan['changes']
    assert not any(row['name'] in {'Value', 'ParameterTarget', 'ExtensionTarget', 'Guarded'} for row in safe)


def test_report_reference_matching_is_case_insensitive(tmp_path):
    model, reports = project(tmp_path)
    path = model / 'definition/tables/ReportView.tmdl'
    path.write_text("table 'Report View'\n\tcolumn value\n", encoding='utf-8')
    write_json(reports[0] / 'definition/pages/P/visuals/C/visual.json', {'visual': {'query': {'Column': {
        'Expression': {'SourceRef': {'Entity': 'REPORT VIEW'}}, 'Property': 'Value'}}}})
    query = listing(model)
    result = query.usage(table='Report View', item='value')
    row = query.items(table='Report View', limit=None)['items']['items'][0]
    assert row['status'].startswith('USED')
    assert result['report_used'] and result['locations']['total'] == 1
    assert not query.items(table='Report View', unused=True)['items']['items']



def test_unused_non_safe_items_explain_inferred_columns_and_retained_review_consumers(tmp_path):
    model, reports = project(tmp_path)
    (model / 'definition/tables/Derived.tmdl').write_text(
        'table Derived\n\tcolumn Description\n\t\tisNameInferred\n'
        '\tpartition Derived = calculated\n\t\tsource = DATATABLE("Description", STRING, {{"x"}})\n', encoding='utf-8')
    query = listing(model)
    rows = query.items(unused=True, limit=None)['items']['items']
    assert all(row.get('kept_because') for row in rows if row['cleanup'] != 'Safe')
    inferred = next(r for r in rows if r['name'] == 'Description')
    assert any('calculated table' in r['reason'] and 'expression' in r['reason'] for r in inferred['kept_because'])
    column = next(r for r in rows if r['name'] == 'Guarded')
    assert any(r.get('dependency', {}).get('name') == 'Retained' and 'Review' in r['reason']
               for r in column['kept_because'])
    usage = query.usage(table='Derived', item='Description')
    assert usage['review_reasons']['total'] and usage['kept_because']
