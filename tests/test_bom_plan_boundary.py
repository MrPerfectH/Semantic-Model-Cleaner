"""BOM analysis must not enable writers that miss a BOM-prefixed declaration."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan, webapp


def project(tmp_path, newline='\n'):
    model = tmp_path / 'M.SemanticModel'
    report = tmp_path / 'R.Report'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_bytes(('\ufefftable Sales' + newline + '\tmeasure Idle = 1' + newline).encode())
    (tables / 'Other.tmdl').write_text('table Other\n\tmeasure Constant = 1\n')
    (model / 'definition/model.tmdl').write_text('model Model\n\tref table Sales\n\tref table Other\n')
    (report / 'definition').mkdir(parents=True)
    (report / 'definition/report.json').write_text('{}')
    (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}}))
    return model, report


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('operation', [
    {'kind': 'rename', 'table_renames': [{'table': 'Sales', 'target_table': 'Fact Sales'}]},
    {'kind': 'rename', 'measure_renames': [{'table': 'Sales', 'name': 'Idle', 'target_name': 'Renamed'}]},
    {'kind': 'actions', 'actions': [{'action': 'hide', 'table': 'Sales', 'name': 'Idle', 'item_type': 'Measure'}]},
    {'kind': 'actions', 'actions': [{'action': 'delete', 'table': 'Sales', 'name': 'Idle', 'item_type': 'Measure'}]},
    {'kind': 'move', 'moves': [{'table': 'Sales', 'name': 'Idle', 'target_table': 'Other'}]},
    {'kind': 'move', 'moves': [{'table': 'Other', 'name': 'Constant', 'target_table': 'Sales'}]},
])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_bom_model_changes_refuse_atomically_after_analyzing_correctly(tmp_path, operation, newline):
    model, report = project(tmp_path, newline)
    before = snapshot(tmp_path)
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert any(row['item'].name == 'Idle' and row['item'].table == 'Sales' for row in result['items'])
    # Even a valid operation placed first must not be applied as a partial batch.
    operations = [{'kind': 'actions', 'actions': [
        {'action': 'hide', 'table': 'Other', 'name': 'Constant', 'item_type': 'Measure'},
    ]}, operation]
    with pytest.raises(change_plan.PlanError, match='UTF-8 BOM'):
        change_plan.create_plan(model, [report], operations)
    response = webapp.app.test_client().post('/api/plans', json={
        'model_path': str(model), 'report_paths': [str(report)], 'operations': operations,
    })
    assert response.status_code == 400
    assert 'UTF-8 BOM' in response.json['error']
    assert snapshot(tmp_path) == before


def test_previously_saved_bom_plan_cannot_apply_after_upgrade(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    operation = {'kind': 'rename', 'table_renames': [{'table': 'Sales', 'target_table': 'Fact Sales'}]}
    # Simulate the previous version, which accepted this incorrect unused-table preview.
    with monkeypatch.context() as previous_version:
        previous_version.setattr(change_plan, '_require_supported_write_encoding', lambda inventory: None)
        old_plan = change_plan.create_plan(model, [report], [operation])
    before = snapshot(tmp_path)
    with pytest.raises(change_plan.PlanError, match='UTF-8 BOM'):
        change_plan.apply_plan(old_plan, tmp_path / 'receipts')
    assert snapshot(tmp_path) == before
