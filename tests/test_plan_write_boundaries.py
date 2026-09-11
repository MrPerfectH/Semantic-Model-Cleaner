"""Public write shortcuts must not bypass the saved, reviewed plan contract."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from semantic_model_cleaner import webapp


ROUTES = {
    'actions': '/api/action',
    'dax': '/api/dax',
    'rename': '/api/model/rename',
    'move': '/api/measure/move',
    'promote': '/api/report-measure/migrate',
    'report_repair': '/api/report/repair-references',
    'clean_stale': '/api/report/cleanup-stale',
    'report_issues': '/api/report/issues/apply',
}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def project(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    report = tmp_path / 'R.Report'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n')
    (tables / 'Measures.tmdl').write_text('table Measures\n\tmeasure Constant = 1\n')
    visual = report / 'definition/pages/P/visuals/V/visual.json'
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({'visual': {
        'query': {'queryState': {'Values': {'projections': [
            {'field': {'Measure': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Revenue'}}},
            {'field': {'Column': {'Expression': {'SourceRef': {'Entity': 'Legacy Sales'}}, 'Property': 'Amount'}}},
        ]}}},
        'objects': {'labels': [{'selector': {'metadata': 'Sales.Gone'}}]},
    }}))
    (report / 'definition/report.json').write_text('{}')
    (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}}))
    (report / 'definition/reportExtensions.json').write_text(json.dumps({'name': 'extension', 'entities': [
        {'name': 'Sales', 'measures': [{'name': 'Local', 'expression': '[Revenue] + 1'}]},
    ]}))
    entry = {'report_path': str(report), 'artifact_path': 'definition/pages/P/visuals/V/visual.json'}
    operations = {
        'actions': {'actions': [{'action': 'hide', 'table': 'Sales', 'name': 'Revenue', 'item_type': 'Measure'}]},
        'dax': {'table': 'Sales', 'name': 'Revenue', 'item_type': 'Measure', 'dax_expression': '2'},
        'rename': {'measure_renames': [{'table': 'Sales', 'name': 'Revenue', 'target_name': 'Net Revenue'}]},
        'move': {'moves': [{'table': 'Sales', 'name': 'Revenue', 'target_table': 'Measures'}]},
        'promote': {'report_path': str(report), 'table': 'Sales', 'name': 'Local'},
        'report_repair': {'table_renames': [{'table': 'Legacy Sales', 'target_table': 'Sales'}]},
        'clean_stale': {'entries': [{**entry, 'source_path': 'visual.objects.labels.[0].selector.metadata',
                                    'selector_value': 'Sales.Gone', 'stale_kind': ''}]},
        'report_issues': {'entries': [{**entry, 'action': 'remove', 'table': 'Legacy Sales', 'name': 'Amount',
                                      'source_path': 'visual.query.queryState.Values.projections.[1].field.Column'}]},
    }
    return model, report, operations


@pytest.mark.parametrize('kind', ROUTES)
@pytest.mark.parametrize('flags', [{}, {'create_backup': True}, {'dry_run': False, 'apply': True, 'force': True},
                                  {'dry_run': 'false'}, {'dry_run': 1}, {'dryRun': 'true'}])
def test_every_legacy_write_route_is_withheld_without_any_file_change(tmp_path, monkeypatch, kind, flags):
    model, report, operations = project(tmp_path)
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'state'))
    original = snapshot(tmp_path)
    response = webapp.app.test_client().post(ROUTES[kind], json={
        'model_path': str(model), 'report_paths': [str(report)], **operations[kind], **flags,
    })
    assert response.status_code == 409, response.json
    assert response.json['ok'] is False
    assert response.json['code'] == 'REVIEWED_PLAN_REQUIRED'
    assert response.json['plan_endpoint'] == '/api/plans'
    assert response.json['operation_kind'] == kind
    assert snapshot(tmp_path) == original


@pytest.mark.parametrize('kind', ROUTES)
def test_legacy_preview_is_read_only_and_does_not_authorize_a_later_write(tmp_path, kind):
    model, report, operations = project(tmp_path)
    original = snapshot(tmp_path)
    client = webapp.app.test_client()
    body = {'model_path': str(model), 'report_paths': [str(report)], **operations[kind]}
    preview = client.post(ROUTES[kind], json={**body, 'dry_run': True, 'create_backup': True})
    if kind in {'actions', 'dax'}:
        assert preview.status_code == 409
    else:
        assert preview.status_code == 200, preview.json
    assert snapshot(tmp_path) == original
    assert client.post(ROUTES[kind], json=body).status_code == 409
    assert snapshot(tmp_path) == original


@pytest.mark.parametrize('kind', ROUTES)
def test_saved_api_plan_still_previews_applies_verifies_receipts_and_restores(tmp_path, monkeypatch, kind):
    model, report, operations = project(tmp_path / 'project')
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'state'))
    original = snapshot(tmp_path / 'project')
    client = webapp.app.test_client()
    response = client.post('/api/plans', json={'model_path': str(model), 'report_paths': [str(report)],
        'operations': [{'kind': kind, **operations[kind]}]})
    assert response.status_code == 200, response.json
    plan = response.json['plan']
    assert plan['changes']
    assert snapshot(tmp_path / 'project') == original
    url = '/api/plans/' + plan['id']
    assert client.post(url + '/verify').json['state'] == 'original'
    applied = client.post(url + '/apply')
    assert applied.status_code == 200, applied.json
    assert applied.json['receipt']['status'] == 'applied'
    assert snapshot(tmp_path / 'project') != original
    assert client.post(url + '/verify').json['state'] == 'applied'
    receipt_file = tmp_path / 'state/plans' / (plan['id'] + '.receipt.json')
    assert json.loads(receipt_file.read_text())['status'] == 'applied'
    restored = client.post(url + '/restore')
    assert restored.status_code == 200, restored.json
    assert client.post(url + '/verify').json['state'] == 'original'
    assert snapshot(tmp_path / 'project') == original


def test_cli_public_dispatch_withholds_apply_even_without_backup(tmp_path):
    model, report, _ = project(tmp_path)
    original = snapshot(tmp_path)
    completed = subprocess.run([sys.executable, '-c',
        'from semantic_model_cleaner.cli import main; main()',
        'clean-stale', str(tmp_path), '--apply', '--no-backup', '--format', 'json'],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload['ok'] is False
    assert payload['applied'] is False
    assert payload['dry_run'] is True
    assert payload['removed_count'] == 0
    assert payload['backup_paths'] == payload['updated_files'] == []
    assert 'smc plan' in payload['error']
    assert payload['errors'] == [payload['error']]
    assert snapshot(tmp_path) == original


@pytest.mark.parametrize('case,expected', [('clean', 0), ('candidates', 1), ('missing', 2), ('invalid_json', 2)])
def test_cli_public_dispatch_uses_clean_findings_error_exit_codes(tmp_path, case, expected):
    _, report, _ = project(tmp_path)
    if case == 'clean':
        (report / 'definition/pages/P/visuals/V/visual.json').write_text('{}')
    elif case == 'invalid_json':
        (report / 'definition/pages/P/visuals/V/visual.json').write_text('{')
    selected = tmp_path / 'missing' if case == 'missing' else tmp_path
    original = snapshot(tmp_path)
    completed = subprocess.run([sys.executable, '-c',
        'from semantic_model_cleaner.cli import main; main()',
        'clean-stale', str(selected), '--format', 'json'],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False)
    assert completed.returncode == expected, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload['ok'] is (expected != 2)
    assert bool(payload['errors']) is (expected == 2)
    assert payload['applied'] is False
    assert snapshot(tmp_path) == original


def test_cli_public_plan_workflow_cleans_then_restores_exact_report_bytes(tmp_path):
    model, report, operations = project(tmp_path / 'project')
    original = snapshot(tmp_path / 'project')
    source = tmp_path / 'operations.json'
    source.write_text(json.dumps([{'kind': 'clean_stale', **operations['clean_stale']}]))
    target = tmp_path / 'reviewed.plan.json'
    journal = tmp_path / 'journal'

    def invoke(*args, expected=0):
        completed = subprocess.run([sys.executable, '-c',
            'from semantic_model_cleaner.cli import main; main()', *map(str, args)],
            cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False)
        assert completed.returncode == expected, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    invoke('plan', tmp_path / 'project', '--model', model, '--report', report,
           '--operations', source, '-o', target)
    plan = json.loads(target.read_text())
    assert plan['changes']
    assert snapshot(tmp_path / 'project') == original
    assert invoke('verify', target, expected=1)['state'] == 'original'
    applied = invoke('apply', target, '--journal-dir', journal)
    assert applied['receipt']['status'] == 'applied'
    assert invoke('verify', target)['state'] == 'applied'
    assert snapshot(tmp_path / 'project') != original
    assert (journal / (plan['id'] + '.receipt.json')).is_file()
    invoke('restore', target, '--journal-dir', journal)
    assert invoke('verify', target, expected=1)['state'] == 'original'
    assert snapshot(tmp_path / 'project') == original
