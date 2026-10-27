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
        '\tmeasure Spare = 1\n\tmeasure MissingUrl = 1\n\tmeasure Leaf = 1\n\tmeasure Top = [Leaf]\n', encoding='utf-8')
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
    assert not any(row['name'] in {'Value', 'ParameterTarget', 'ExtensionTarget', 'Guarded', 'MissingUrl'} for row in safe)


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


def test_one_cascade_plan_deletes_closed_chains_and_unused_calculated_tables(tmp_path, capsys):
    import json
    from semantic_model_cleaner import plan_cli
    model, reports = project(tmp_path)
    (model / 'definition/tables/Derived.tmdl').write_text(
        'table Derived\n\tcolumn Description\n\t\tisNameInferred\n'
        '\tpartition Derived = calculated\n\t\tsource = DATATABLE("Description", STRING, {{"x"}})\n', encoding='utf-8')
    planfile = tmp_path / 'review/cleanup.json'
    assert plan_cli.main(['plan', str(tmp_path), '--cleanup', 'unused', '--cascade',
                          '-o', str(planfile), '--format', 'json']) == 0
    plan = json.loads(planfile.read_text(encoding='utf-8'))
    removed = {(a['table'], a['name'], a['item_type']) for op in plan['operations'] for a in op['actions']}
    assert {('Sales', 'Leaf', 'Measure'), ('Sales', 'Top', 'Measure'), ('Derived', 'Derived', 'Table')} <= removed
    assert not any(name in {'Guarded', 'Retained', 'ExtensionTarget', 'ParameterTarget', 'Value'} for _, name, _ in removed)
    assert plan['cleanup']['kept'] and all(r['kept_because'] for r in plan['cleanup']['kept'])
    assert plan['cleanup']['held_back_hidden'] == 1
    assert change_plan.apply_plan(plan, tmp_path / 'journal')['ok']
    assert change_plan.verify_plan(plan)['ok']
    assert not (model / 'definition/tables/Derived.tmdl').exists()
    assert change_plan.restore_plan(plan, tmp_path / 'journal')['ok']


def test_calculated_table_removal_is_blocked_by_retained_bare_table_consumer(tmp_path):
    from semantic_model_cleaner.cleanup_flow import cleanup_actions
    model, _ = project(tmp_path)
    (model / 'definition/tables/Derived.tmdl').write_text(
        'table Derived\n\tcolumn X\n\t\tisNameInferred\n'
        '\tpartition Derived = calculated\n\t\tsource = {1}\n', encoding='utf-8')
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text(encoding='utf-8') + '\tmeasure CountDerived = COUNTROWS(Derived)\n\t\tisHidden\n', encoding='utf-8')
    query = listing(model)
    result = cleanup_actions(query, cascade=True)
    assert not any(a['table'] == 'Derived' for a in result['actions'])
    assert any('CountDerived' in reason['message'] for reason in result['kept'][('derived', 'derived')])


def test_hidden_only_review_requires_explicit_opt_in(tmp_path):
    from semantic_model_cleaner.cleanup_flow import create_cleanup_plan
    model, reports = project(tmp_path)
    # Retained is hidden, but is otherwise unused; its column becomes removable together.
    regular = create_cleanup_plan(tmp_path, model, reports, cascade=True)
    assert not any(a['name'] == 'Retained' for op in regular['operations'] for a in op['actions'])
    opted = create_cleanup_plan(tmp_path, model, reports, cascade=True, include_review=True)
    assert any(a['name'] == 'Retained' and a['allow_hidden'] for op in opted['operations'] for a in op['actions'])
    assert opted['cleanup']['held_back_hidden'] == 0
    assert change_plan.apply_plan(opted, tmp_path / 'journal')['ok']
    assert change_plan.verify_plan(opted)['ok']


def test_unused_inferred_calculated_table_is_offered_as_one_table_action(tmp_path):
    model, _ = project(tmp_path)
    (model / 'definition/tables/Derived.tmdl').write_text(
        'table Derived\n\tcolumn X\n\t\tisNameInferred\n'
        '\tpartition Derived = calculated\n\t\tsource = {1}\n', encoding='utf-8')
    result = listing(model).items(unused=True, limit=None)
    table = next(row for row in result['table_removals'] if row['table'] == 'Derived')
    assert table['cleanup'] == 'Safe' and table['action']['item_type'] == 'Table'
    tables = listing(model).items(unused=True, item_type='table', limit=None)['items']['items']
    assert any(row['table'] == 'Derived' and row['cleanup'] == 'Safe' for row in tables)


def test_other_models_report_does_not_retain_unused_calculated_table(tmp_path):
    from semantic_model_cleaner.cleanup_flow import create_cleanup_plan
    model, reports = project(tmp_path)
    (model / 'definition/tables/Derived.tmdl').write_text(
        'table Derived\n\tcolumn X\n\t\tisNameInferred\n'
        '\tpartition Derived = calculated\n\t\tsource = {1}\n', encoding='utf-8')
    other = tmp_path / 'Legacy.Report'
    write_json(other / 'definition.pbir', {'datasetReference': {'byConnection': {
        'connectionString': 'Data Source=powerbi://example;Initial Catalog=Legacy;'}}})
    write_json(other / 'definition/report.json', {'Column': {
        'Expression': {'SourceRef': {'Entity': 'Derived'}}, 'Property': 'X'}})
    plan = create_cleanup_plan(tmp_path, model, reports, cascade=True,
                               known_reports=[*reports, other], report_search_roots=[tmp_path])
    assert any(a['table'] == 'Derived' and a['item_type'] == 'Table' for op in plan['operations'] for a in op['actions'])


def test_whole_table_writer_preserves_neighbour_bytes_and_line_endings(tmp_path):
    from semantic_model_cleaner import tmdl_writer
    model, _ = project(tmp_path)
    path = model / 'definition/tables/Mixed.tmdl'
    neighbor = b'table Neighbor\r\n\tcolumn Keep\r\n\t\tdescription: untouched\r\n'
    path.write_bytes(b'table Derived\r\n\tcolumn X\r\n\t\tisNameInferred\r\n' + neighbor)
    assert tmdl_writer.delete_table(model, 'Derived')['ok']
    assert path.read_bytes() == neighbor


def test_unrelated_broken_query_does_not_retain_same_named_model_measure(tmp_path):
    model, reports = project(tmp_path)
    source = model / 'definition/tables/Sales.tmdl'
    source.write_text(source.read_text(encoding='utf-8') + '\tmeasure Unrelated = 1\n', encoding='utf-8')
    write_json(reports[0] / 'definition/pages/P/visuals/Broken/visual.json', {'visual': {'query': {'Measure': {
        'Expression': {'SourceRef': {'Entity': 'MissingTable'}}, 'Property': 'Unrelated'}}}})
    rows = listing(model).items(unused=True, limit=None)['items']['items']
    assert next(r for r in rows if r['name'] == 'Unrelated')['cleanup'] == 'Safe'
    assert change_plan.create_plan(model, reports, [dict(kind='actions', actions=[
        dict(action='delete', table='Sales', name='Unrelated', item_type='Measure')])])['changes']
