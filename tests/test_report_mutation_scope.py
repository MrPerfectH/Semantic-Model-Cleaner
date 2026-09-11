"""Report-local mutations must preserve exact ownership at every entry point."""
import json

import pytest

from semantic_model_cleaner import change_plan, report_writer


@pytest.mark.parametrize('writer', [report_writer.apply_report_issue_actions,
                                   report_writer.cleanup_stale_metadata_selectors])
@pytest.mark.parametrize('escape', ['parent', 'absolute', 'symlink', 'missing_owner'])
def test_report_actions_refuse_cross_report_artifacts_before_writing(tmp_path, writer, escape):
    report = tmp_path / 'first' / 'Same.Report'
    sibling = tmp_path / 'second' / 'Same.Report'
    report.mkdir(parents=True)
    sibling.mkdir(parents=True)
    target = sibling / 'visual.json'
    original = json.dumps({'value': 'must remain untouched'}).encode()
    target.write_bytes(original)
    local = report / 'local.json'
    local.write_bytes(original)
    if escape == 'symlink':
        try:
            (report / 'linked').symlink_to(sibling, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f'Directory symlinks unavailable on this platform: {exc}')
    artifact = {'parent': '../../second/Same.Report/visual.json',
                'absolute': str(target), 'symlink': 'linked/visual.json',
                'missing_owner': str(target)}[escape]
    entry = {'report_path': '' if escape == 'missing_owner' else str(report),
             'artifact_path': artifact, 'action': 'remove', 'source_path': 'value',
             'selector_value': 'value'}
    # Include an earlier valid operation: all entry paths must pass before writes.
    result = writer(entries=[dict(entry, report_path=str(report), artifact_path='local.json'), entry])
    assert result['ok'] is False
    assert 'report' in result['error'].lower()
    assert target.read_bytes() == original
    assert local.read_bytes() == original


def test_promotion_refuses_implicit_owner_when_report_names_collide(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(report_writer, 'migrate_measure_to_model', lambda **kwargs: calls.append(kwargs) or {'ok': True})
    roots = {'model': tmp_path / 'M.SemanticModel',
             'report-1': tmp_path / 'one' / 'Same.Report',
             'report-2': tmp_path / 'two' / 'Same.Report'}
    with pytest.raises(change_plan.PlanError, match='exact report_path'):
        change_plan._execute({'kind': 'promote', 'table': 'Sales', 'name': 'Local'}, roots)
    assert calls == []
    change_plan._execute({'kind': 'promote', 'table': 'Sales', 'name': 'Local',
                          'report_path': str(roots['report-2'])}, roots)
    assert calls[0]['report_path'] == roots['report-2']


@pytest.mark.parametrize('kind', ['rename', 'move'])
def test_model_refactoring_cannot_narrow_selected_report_propagation(tmp_path, kind):
    roots = {'model': tmp_path / 'M.SemanticModel',
             'report-1': tmp_path / 'one' / 'Same.Report',
             'report-2': tmp_path / 'two' / 'Same.Report'}
    with pytest.raises(change_plan.PlanError, match='every report'):
        change_plan._execute({'kind': kind, 'report_paths': [str(roots['report-1'])]}, roots)


def test_report_only_repair_preserves_explicit_single_report_scope(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(report_writer, 'rewrite_model_reference_changes',
                        lambda **kwargs: calls.append(kwargs) or {'ok': True})
    roots = {'model': tmp_path / 'M.SemanticModel',
             'report-1': tmp_path / 'one' / 'Same.Report',
             'report-2': tmp_path / 'two' / 'Same.Report'}
    change_plan._execute({'kind': 'report_repair', 'report_paths': [str(roots['report-2'])],
                          'table_renames': [{'table': 'Old', 'target_table': 'New'}]}, roots)
    assert calls[0]['report_paths'] == [roots['report-2']]
