"""Structured deletion diagnostics over the public plan interface."""
import json

from test_bulk_cleanup_flow import project


def test_plan_returns_all_policy_blockers_with_action_identity_and_locations(tmp_path, capsys):
    from semantic_model_cleaner import plan_cli
    model, reports = project(tmp_path)
    operations = tmp_path / 'ops.json'
    requested = [dict(action='delete', table='Sales', name=name, item_type=kind) for name, kind in (
        ('ParameterTarget', 'Measure'), ('ExtensionTarget', 'Measure'), ('Guarded', 'Column'), ('Spare', 'Measure'))]
    requested.append(dict(action='delete', table='Links', name='Value', item_type='Column'))
    operations.write_text(json.dumps([{'kind': 'actions', 'actions': requested}]), encoding='utf-8')
    assert plan_cli.main(['plan', str(tmp_path), '--operations', str(operations),
                          '-o', str(tmp_path / 'plan.json'), '--format', 'json']) == 2
    result = json.loads(capsys.readouterr().out)
    blockers = result['blockers']
    assert {b['action_index'] for b in blockers} == {0, 1, 2, 4}
    assert all(b['operation_index'] == 0 and b['rule_id'] == 'SMC-D006' for b in blockers)
    assert all(b['reason'] and b['resolution'] and b['item_type'] for b in blockers)
    link = next(b for b in blockers if b['table'] == 'Links')
    assert link['location']['page'] == 'Weekly' and link['location']['visual'] == 'V'
    assert 'webUrl' in link['location']['json_path']
    assert result['blocked_action_count'] == 4 and result['remaining_action_count'] == 1
    assert not (tmp_path / 'plan.json').exists()


def test_new_reference_errors_are_complete_sentences_with_structured_owners(tmp_path, capsys):
    from semantic_model_cleaner import plan_cli
    model, _ = project(tmp_path)
    operations = tmp_path / 'ops.json'
    operations.write_text(json.dumps([dict(kind='dax', table='Sales', name=name,
        item_type='Measure', dax_expression='[Absent]') for name in ('Spare', 'Top')]), encoding='utf-8')
    assert plan_cli.main(['plan', str(tmp_path), '--operations', str(operations),
                          '-o', str(tmp_path / 'plan.json'), '--format', 'json']) == 2
    result = json.loads(capsys.readouterr().out)
    assert {b['name'] for b in result['blockers']} == {'Spare', 'Top'}
    assert {b['operation_index'] for b in result['blockers']} == {0, 1}
    assert all(b['rule_id'] == 'SMC-PLAN-REFERENCE' and b['resolution'] for b in result['blockers'])
    assert "('model'," not in result['error']
