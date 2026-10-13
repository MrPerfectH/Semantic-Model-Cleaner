from semantic_model_cleaner import analyzer, webapp


def test_relationship_cards_receive_local_cardinality_and_actual_direction(tmp_path):
    model = tmp_path / 'Graph.SemanticModel'
    tables = model / 'definition' / 'tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tcolumn Key\n', encoding='utf-8')
    (tables / 'Customers.tmdl').write_text('table Customers\n\tcolumn Key\n', encoding='utf-8')
    relationships = model / 'definition' / 'relationships.tmdl'
    relationships.write_text('relationship 11111111-2222-3333-4444-555555555555\n'
                             '\tfromColumn: Sales.Key\n\ttoColumn: Customers.Key\n'
                             '\tfromCardinality: many\n\ttoCardinality: one\n'
                             '\tcrossFilteringBehavior: bothDirections\n\tisActive: false\n', encoding='utf-8')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[], allow_model_only=True)
    payload = webapp._serialize_results(result)
    by_name = {table['name']: table for table in payload['tables']}
    sales = by_name['Sales']['relationships'][0]
    customers = by_name['Customers']['relationships'][0]
    assert sales['cardinality'] == '*:1'
    assert customers['cardinality'] == '1:*'
    assert customers['otherTable'] == 'Sales'
    assert sales['filterDirection'] == 'Both directions'
    assert sales['isActive'] is False
    relationships.write_text(relationships.read_text().replace('bothDirections', 'oneDirection'), encoding='utf-8')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[], allow_model_only=True)
    payload = webapp._serialize_results(result)
    assert all(rel['filterDirection'] == 'Customers → Sales' for table in payload['tables'] for rel in table['relationships'])
