"""Behavior-preservation regressions for the shared refactoring writers."""
import json

import pytest

from semantic_model_cleaner import report_writer, tmdl_writer
from semantic_model_cleaner.reference_tokens import rewrite_dax


def project(tmp_path, text='table Sales\n\tcolumn Amount\n\tmeasure Revenue = 1\n'):
    model = tmp_path / 'Demo.SemanticModel'
    tables = model / 'definition' / 'tables'
    tables.mkdir(parents=True)
    source = tables / 'Sales.tmdl'
    source.write_text(text)
    report = tmp_path / 'Demo.Report'
    (report / 'definition').mkdir(parents=True)
    return model, source, report


def extensions(report, measures):
    path = report / 'definition' / 'reportExtensions.json'
    path.write_text(json.dumps({'name': 'extension', 'entities': [{'name': 'Sales', 'measures': measures}]}))
    return path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_measure_rename_preserves_literals_comments_metadata_and_m(tmp_path):
    text = ('table Sales\n\tmeasure Revenue = 1\n'
            '\tmeasure Label = "[Revenue]" & [Revenue] // [Revenue]\n'
            '\tmeasure Multi =\n\t\t\t/* [Revenue] */\n\t\t\t[Revenue]\n'
            '\t\tdescription: [Revenue]\n'
            '\tpartition Sales = m\n\t\tsource =\n\t\t\tlet Revenue = "[Revenue]", x = [Revenue] in x\n')
    model, source, _ = project(tmp_path, text)
    result = tmdl_writer.rename_measure(model, 'Sales', 'Revenue', 'Net Revenue')
    assert result['ok']
    actual = source.read_text()
    assert '"[Revenue]" & [Net Revenue] // [Revenue]' in actual
    assert '/* [Revenue] */\n\t\t\t[Net Revenue]' in actual
    assert 'description: [Revenue]' in actual
    assert 'let Revenue = "[Revenue]", x = [Revenue] in x' in actual


def test_table_rename_preserves_m_and_strings_but_changes_bare_dax(tmp_path):
    model, _, _ = project(tmp_path, 'table Sales\n\tmeasure N = COUNTROWS(Sales) + SUM(Sales[Amount])\n'
                        '\tmeasure Label = "Sales[Amount]" // Sales[Amount]\n'
                        '\tpartition Sales = m\n\t\tsource =\n\t\t\tlet Sales = [Amount = 1] in Sales\n')
    assert tmdl_writer.rename_table(model, 'Sales', 'Fact Sales')['ok']
    text = (model / 'definition/tables/Fact Sales.tmdl').read_text()
    assert "COUNTROWS('Fact Sales') + SUM('Fact Sales'[Amount])" in text
    assert '"Sales[Amount]" // Sales[Amount]' in text
    assert 'let Sales = [Amount = 1] in Sales' in text


def test_ambiguous_measure_rename_blocks_before_any_write(tmp_path):
    model, _, _ = project(tmp_path, 'table Sales\n\tmeasure Revenue = 1\n\tmeasure Total = [Revenue]\n')
    (model / 'definition/tables/Other.tmdl').write_text('table Other\n\tcolumn Revenue\n')
    before = snapshot(tmp_path)
    result = tmdl_writer.rename_measure(model, 'Sales', 'Revenue', 'Net Revenue')
    assert not result['ok']
    assert result['ambiguous_files']
    assert snapshot(tmp_path) == before


def test_qualified_measure_reference_ignores_unrelated_same_named_objects():
    value, count = rewrite_dax("'Sales'[Revenue] + 'Other'[Revenue] + \"[Revenue]\"", measures={('sales', 'revenue'): 'Net Revenue'})
    assert value == "'Sales'[Net Revenue] + 'Other'[Revenue] + \"[Revenue]\""
    assert count == 1


@pytest.mark.parametrize('bad', ['invalid', 'missing'])
def test_report_rewrite_refuses_incomplete_scan_without_partial_writes(tmp_path, bad):
    _, _, report = project(tmp_path)
    (report / 'definition/a.json').write_text(json.dumps({'Entity': 'Sales'}))
    if bad == 'invalid':
        (report / 'definition/z.json').write_text('{broken')
        reports = [report]
    else:
        missing = tmp_path / 'Missing.Report'
        missing.mkdir()
        reports = [report, missing]
    before = snapshot(tmp_path)
    result = report_writer.rewrite_model_reference_changes(report_paths=reports, table_renames=[{'table': 'Sales', 'target_table': 'Fact Sales'}])
    assert not result['ok']
    assert snapshot(tmp_path) == before


def test_promotion_requires_dependency_closure_and_preview_does_not_write(tmp_path):
    model, source, report = project(tmp_path)
    extensions(report, [{'name': 'Base', 'expression': 'SUM(Sales[Amount])'},
                        {'name': 'Derived', 'expression': '[Base] + 1'}])
    before = snapshot(tmp_path)
    result = report_writer.migrate_measure_to_model(model_path=model, report_path=report, entity_name='Sales', measure_name='Derived')
    assert not result['ok'] and result['required_dependencies'][0]['name'] == 'Base'
    assert snapshot(tmp_path) == before
    preview = report_writer.migrate_measure_to_model(model_path=model, report_path=report, entity_name='Sales', measure_name='Derived', include_dependencies=True, dry_run=True)
    assert preview['ok'] and [p['name'] for p in preview['promotions']] == ['Base', 'Derived']
    assert snapshot(tmp_path) == before
    applied = report_writer.migrate_measure_to_model(model_path=model, report_path=report, entity_name='Sales', measure_name='Derived', include_dependencies=True)
    assert applied['ok']
    assert 'measure Base = SUM(Sales[Amount])' in source.read_text()
    assert 'measure Derived = [Base] + 1' in source.read_text()


@pytest.mark.parametrize('measures', [
    [{'name': 'Derived', 'expression': '[Missing] + 1'}],
    [{'name': 'Derived', 'expression': '[Base]'}, {'name': 'Base', 'expression': '[Derived]'}],
    [{'name': 'Revenue', 'expression': '1'}],
    [{'name': 'Derived', 'expression': '1', 'unknownSemanticMetadata': 'x'}],
])
def test_promotion_blocks_unresolved_cycles_conflicts_and_metadata_loss(tmp_path, measures):
    model, _, report = project(tmp_path)
    extensions(report, measures)
    before = snapshot(tmp_path)
    result = report_writer.migrate_measure_to_model(model_path=model, report_path=report, entity_name='Sales', measure_name=measures[0]['name'], include_dependencies=True)
    assert not result['ok']
    assert snapshot(tmp_path) == before


def test_dependency_promotion_restores_whole_batch_when_second_write_fails(tmp_path, monkeypatch):
    model, _, report = project(tmp_path)
    extensions(report, [{'name': 'Base', 'expression': '1'}, {'name': 'Derived', 'expression': '[Base]'}])
    before = snapshot(tmp_path)
    original = tmdl_writer.create_measure
    def fail_second(**kwargs):
        if kwargs['name'] == 'Derived':
            raise OSError('injected second write failure')
        return original(**kwargs)
    monkeypatch.setattr(tmdl_writer, 'create_measure', fail_second)
    result = report_writer.migrate_measure_to_model(model_path=model, report_path=report, entity_name='Sales', measure_name='Derived', include_dependencies=True)
    assert not result['ok'] and result['rolled_back']
    assert snapshot(tmp_path) == before


def test_column_rename_updates_model_structure_and_report_expression(tmp_path):
    model, source, report = project(tmp_path,
        'table Sales\n\tcolumn Amount\n\t\tsourceColumn: Amount\n'
        '\tcolumn Label\n\t\tsortByColumn: Amount\n'
        '\thierarchy Details\n\t\tlevel Value\n\t\t\tcolumn: Amount\n'
        '\tmeasure Revenue = SUM(Sales[Amount])\n')
    (model / 'definition/relationships.tmdl').write_text('relationship R\n\tfromColumn: Sales.Amount\n\ttoColumn: Other.Id\n')
    (model / 'definition/role.tmdl').write_text('role Reader\n\ttablePermission Sales =\n\t\t```\n\t\t[Amount] > 0\n\t\t```\n\t\tcolumnPermission Amount\n')
    (model / 'definition/perspective.tmdl').write_text('perspective Executive\n\tperspectiveTable Sales\n\t\tperspectiveColumn Amount\n')
    before = snapshot(tmp_path)
    change = {'table': 'Sales', 'name': 'Amount', 'target_name': 'Net Amount'}
    preview = tmdl_writer.rename_model_metadata(model, column_renames=[change], dry_run=True)
    assert preview['ok'] and snapshot(tmp_path) == before
    assert tmdl_writer.rename_model_metadata(model, column_renames=[change])['ok']
    text = source.read_text()
    assert "column 'Net Amount'" in text
    assert 'sourceColumn: Amount' in text
    assert "sortByColumn: 'Net Amount'" in text
    assert "column: 'Net Amount'" in text
    assert 'SUM(Sales[Net Amount])' in text
    assert "fromColumn: Sales.'Net Amount'" in (model / 'definition/relationships.tmdl').read_text()
    assert '[Net Amount] > 0' in (model / 'definition/role.tmdl').read_text()
    assert "columnPermission 'Net Amount'" in (model / 'definition/role.tmdl').read_text()
    assert "perspectiveColumn 'Net Amount'" in (model / 'definition/perspective.tmdl').read_text()
    extension = extensions(report, [{'name': 'Local', 'expression': 'SUM(Sales[Amount]) + LEN("Sales[Amount]")'}])
    assert report_writer.rewrite_model_reference_changes(report_paths=[report], column_renames=[change])['ok']
    expression = json.loads(extension.read_text())['entities'][0]['measures'][0]['expression']
    assert expression == 'SUM(Sales[Net Amount]) + LEN("Sales[Amount]")'


def test_column_rename_rejects_ambiguous_unqualified_reference(tmp_path):
    model, _, _ = project(tmp_path, 'table Sales\n\tcolumn Amount\n\tmeasure Revenue = [Amount]\n')
    (model / 'definition/tables/Other.tmdl').write_text('table Other\n\tcolumn Amount\n')
    before = snapshot(tmp_path)
    result = tmdl_writer.rename_column(model, 'Sales', 'Amount', 'Net Amount')
    assert not result['ok'] and result['ambiguous_files']
    assert snapshot(tmp_path) == before


def test_combined_table_and_column_rename(tmp_path):
    model, _, _ = project(tmp_path)
    result = tmdl_writer.rename_model_metadata(model, table_renames=[{'table': 'Sales', 'target_table': 'Fact Sales'}],
        column_renames=[{'table': 'Sales', 'name': 'Amount', 'target_name': 'Net Amount'}])
    assert result['ok']
    assert "column 'Net Amount'" in (model / 'definition/tables/Fact Sales.tmdl').read_text()


def test_return_unqualified_measure_and_escaped_literal():
    text = 'VAR X = "a ""[Revenue]""" RETURN [Revenue]'
    actual, _ = rewrite_dax(text, measures={('sales', 'revenue'): 'Net Revenue'})
    assert actual == 'VAR X = "a ""[Revenue]""" RETURN [Net Revenue]'


def test_calculated_column_and_escaped_identifier_rename(tmp_path):
    model, source, _ = project(tmp_path,
        "table Sales\n\tcolumn 'A]mount' = 1\n\tmeasure Total = SUM(Sales[A]]mount])\n")
    result = tmdl_writer.rename_column(model, 'Sales', 'A]mount', 'Net]Amount')
    assert result['ok']
    assert "column 'Net]Amount' = 1" in source.read_text()
    assert 'SUM(Sales[Net]]Amount])' in source.read_text()


def test_table_rename_updates_role_expression_and_perspective_identity(tmp_path):
    model, _, _ = project(tmp_path)
    role = model / 'definition/role.tmdl'
    role.write_text('role Reader\n\ttablePermission Sales = Sales[Amount] > 0\n')
    perspective = model / 'definition/perspective.tmdl'
    perspective.write_text('perspective Executive\n\tperspectiveTable Sales\n\t\tperspectiveMeasure Revenue\n')
    assert tmdl_writer.rename_table(model, 'Sales', 'Fact Sales')['ok']
    assert "tablePermission 'Fact Sales' = 'Fact Sales'[Amount] > 0" in role.read_text()
    assert "perspectiveTable 'Fact Sales'" in perspective.read_text()
