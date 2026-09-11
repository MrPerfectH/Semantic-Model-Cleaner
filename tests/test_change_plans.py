import json
import os
from pathlib import Path
import shutil

import pytest

from semantic_model_cleaner import change_plan as plans


def project(tmp_path):
    source = Path(__file__).parents[1] / 'src/semantic_model_cleaner/demo_workspace'
    root = tmp_path / 'project'
    shutil.copytree(source, root)
    model = next(root.rglob('*.SemanticModel'))
    report = next(root.rglob('*.Report'))
    return model, report


def hide_operation(model):
    from semantic_model_cleaner import analyzer
    item = next(i for i in analyzer.parse_model_items(model) if i.item_type == 'Measure')
    return {'kind': 'actions', 'actions': [{'action': 'hide', 'table': item.table, 'name': item.name, 'item_type': item.item_type}]}


def test_preview_apply_verify_restore_byte_exact(tmp_path):
    model, report = project(tmp_path)
    original = plans._inventory(plans._roots(model, [report]))
    # Existing Windows CRLF must survive restore exactly.
    for key, value in original.items():
        if key.endswith('.tmdl'):
            plans._path(plans._roots(model, [report]), key).write_bytes(value.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    original = plans._inventory(plans._roots(model, [report]))
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    assert plan['changes'] and plan['changes'][0]['diff']
    assert plans._inventory(plans._roots(model, [report])) == original
    assert not (tmp_path / 'journal').exists()
    result = plans.apply_plan(plan, tmp_path / 'journal')
    assert result['ok'], result
    assert plans.verify_plan(plan)['ok']
    assert plans.restore_plan(plan, tmp_path / 'journal')['ok']
    assert plans._inventory(plans._roots(model, [report])) == original


def test_stale_preview_refuses_any_write(tmp_path):
    model, report = project(tmp_path)
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    path = next(model.rglob('*.tmdl'))
    path.write_bytes(path.read_bytes() + b'\n// user edit\n')
    before = plans._inventory(plans._roots(model, [report]))
    with pytest.raises(plans.PlanError, match='Stale plan'):
        plans.apply_plan(plan, tmp_path / 'journal')
    assert plans._inventory(plans._roots(model, [report])) == before


def test_restore_refuses_later_user_edits(tmp_path):
    model, report = project(tmp_path)
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    assert plans.apply_plan(plan, tmp_path / 'journal')['ok']
    path = plans._path(plans._roots(model, [report]), plan['changes'][0]['path'])
    path.write_bytes(path.read_bytes() + b'\n// later edit\n')
    before = path.read_bytes()
    with pytest.raises(plans.PlanError, match='subsequent edits'):
        plans.restore_plan(plan, tmp_path / 'journal')
    assert path.read_bytes() == before


def test_apply_failure_restores_and_records_receipt(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    before = plans._inventory(plans._roots(model, [report]))
    original = plans._atomic
    fired = False
    def fail_after_write(path, content):
        nonlocal fired
        if path.name.endswith('.receipt.json') and not fired and b'"completed": [' in content and b'model/definition/' in content:
            receipt = json.loads(content)
            if receipt.get('completed'):
                fired = True
                raise OSError('injected journal failure')
        return original(path, content)
    monkeypatch.setattr(plans, '_atomic', fail_after_write)
    result = plans.apply_plan(plan, tmp_path / 'journal')
    assert not result['ok']
    assert result['receipt']['status'] == 'rolled_back'
    assert plans._inventory(plans._roots(model, [report])) == before


def test_edited_plan_rejected(tmp_path):
    model, report = project(tmp_path)
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    plan['changes'][0]['path'] = 'model/../../outside.tmdl'
    with pytest.raises(plans.PlanError, match='edited plan'):
        plans.apply_plan(plan, tmp_path / 'journal')


def test_new_broken_dax_prevents_plan(tmp_path):
    model, report = project(tmp_path)
    op = hide_operation(model)['actions'][0]
    with pytest.raises(plans.PlanError, match='unresolved references'):
        plans.create_plan(model, [report], [{'kind': 'dax', 'table': op['table'], 'name': op['name'],
            'item_type': 'Measure', 'dax_expression': "SUM('Missing Table'[Missing Column])"}])


def test_nested_table_states_are_canonical(tmp_path):
    from semantic_model_cleaner import analyzer, webapp
    root = Path(__file__).parents[1] / 'examples/product-qa-workspace'
    model = next(root.rglob('*.SemanticModel'))
    report = next(root.rglob('*.Report'))
    results = analyzer.analyze(root, model_paths=[model], report_paths=[report])
    payload = webapp._serialize_results(results)
    sales = next(t for t in payload['tables'] if t['name'] == 'Sales')
    revenue = next(i for i in sales['items'] if i['name'] == 'Revenue')
    amount = next(i for i in sales['items'] if i['name'] == 'Amount')
    assert revenue['usageState'] == 'Used'
    assert amount['usageState'] == 'Indirect'
    assert sales['issueCounts']['Broken'] > 0
    assert sales['issueCounts']['Stale'] > 0


def test_shared_plan_api_lifecycle(tmp_path, monkeypatch):
    from semantic_model_cleaner import webapp
    model, report = project(tmp_path)
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'state'))
    client = webapp.app.test_client()
    preview = client.post('/api/plans', json={'model_path': str(model), 'report_paths': [str(report)], 'operations': [hide_operation(model)]})
    assert preview.status_code == 200, preview.json
    plan = preview.json['plan']
    applied = client.post(f'/api/plans/{plan["id"]}/apply')
    assert applied.status_code == 200, applied.json
    assert client.post(f'/api/plans/{plan["id"]}/verify').json['ok']
    assert client.get('/api/plans').json['receipts'][0]['status'] == 'applied'
    assert client.post(f'/api/plans/{plan["id"]}/restore').json['ok']


def test_nested_source_path_cannot_escape_stage(tmp_path):
    model, report = project(tmp_path)
    op = hide_operation(model)
    outside = tmp_path / 'outside.tmdl'
    outside.write_text('table Sales\n\tmeasure Revenue = 1\n')
    op['actions'][0]['source_file'] = str(outside)
    original = outside.read_bytes()
    with pytest.raises(plans.PlanError, match='outside staged'):
        plans.create_plan(model, [report], [op])
    assert outside.read_bytes() == original


def test_live_lock_recovery_refused(tmp_path):
    import os
    model, report = project(tmp_path)
    plan = plans.create_plan(model, [report], [hide_operation(model)])
    journal = tmp_path / 'journal'
    assert plans.apply_plan(plan, journal)['ok']
    lock = journal / (plans._digest(str(model.resolve()).encode()) + '.lock')
    lock.write_text(json.dumps({'pid': os.getpid(), 'model': str(model.resolve())}))
    with pytest.raises(plans.PlanError, match='still running|POSIX'):
        plans.recover_interrupted_lock(plan, journal)
    assert lock.exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_atomic_replacement_preserves_existing_permissions(tmp_path):
    path = tmp_path / 'model.tmdl'
    path.write_bytes(b'before')
    path.chmod(0o640)
    plans._atomic(path, b'after')
    assert path.read_bytes() == b'after'
    assert path.stat().st_mode & 0o777 == 0o640
