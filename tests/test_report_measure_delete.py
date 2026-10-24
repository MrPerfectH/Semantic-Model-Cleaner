import json
from pathlib import Path
import pytest
from semantic_model_cleaner import analyzer, change_plan as plans

SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json'

def project(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    (model / 'definition/tables').mkdir(parents=True)
    (model / 'definition/tables/Sales.tmdl').write_text('table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n', encoding='utf-8')
    reports = []
    for parent in ('A', 'B'):
        report = tmp_path / parent / 'Same.Report'
        (report / 'definition').mkdir(parents=True)
        (report / 'definition.pbir').write_text(json.dumps({'version': '4.0', 'datasetReference': {'byPath': {'path': '../../M.SemanticModel'}}}), encoding='utf-8')
        (report / 'definition/report.json').write_text('{}', encoding='utf-8')
        extension(report, [('Sales', 'Unused', '1'), ('Sales', 'Retained', '[Revenue]')])
        reports.append(report)
    return model, reports


def extension(report, measures):
    entities = {}
    for table, name, expression in measures:
        entities.setdefault(table, []).append({'name': name, 'dataType': 'Double', 'expression': expression, 'description': 'Keep literal formatting'})
    path = report / 'definition/reportExtensions.json'
    data = {'$schema': SCHEMA, 'name': 'extension', 'entities': [{'name': table, 'measures': values} for table, values in entities.items()]}
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=4) + '\n').replace('\n', '\r\n').encode())
    return path


def operation(report, *names):
    return {'kind': 'delete_report_measures', 'entries': [{'report_path': str(report.resolve()), 'table': 'Sales', 'name': name} for name in names]}


def test_report_measure_plan_apply_verify_restore(tmp_path):
    model, reports = project(tmp_path)
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)
    plan = plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    assert len(plan['changes']) == 1
    assert plan['changes'][0]['path'].endswith('/definition/reportExtensions.json')
    assert 'Unused' in plan['changes'][0]['diff']
    assert plans._inventory(roots) == before
    assert plans.apply_plan(plan, tmp_path / 'journal')['ok']
    assert plans.verify_plan(plan)['ok']
    assert {i.name for i in analyzer.parse_report_extension_measures(reports[0])} == {'Retained'}
    assert {i.name for i in analyzer.parse_report_extension_measures(reports[1])} == {'Unused', 'Retained'}
    assert plans.restore_plan(plan, tmp_path / 'journal')['ok']
    assert plans._inventory(roots) == before


def test_retained_consumer_blocks_but_closed_chain_deletes(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], [('Sales', 'Leaf', '1'), ('Sales', 'Middle', '[Leaf]'),
                           ('Sales', 'Top', '[Middle]'), ('Sales', 'Retained', '[Revenue]')])
    with pytest.raises(plans.PlanError, match='retained'):
        plans.create_plan(model, reports, [operation(reports[0], 'Leaf')])
    plan = plans.create_plan(model, reports, [operation(reports[0], 'Leaf', 'Middle', 'Top')])
    assert len(plan['validation']['report_measure_deletions']) == 3
    assert plans.apply_plan(plan, tmp_path / 'journal')['ok']
    assert [i.name for i in analyzer.parse_report_extension_measures(reports[0])] == ['Retained']


@pytest.mark.parametrize('surface', ['visual', 'filter', 'bookmark', 'drillthrough',
                                    'conditional_formatting', 'unknown', 'stale'])
def test_every_metadata_surface_blocks_even_opaque_or_stale(tmp_path, surface):
    model, reports = project(tmp_path)
    paths = {
        'visual': 'pages/P/visuals/V/visual.json',
        'filter': 'report.json', 'bookmark': 'bookmarks/X.bookmark.json',
        'drillthrough': 'pages/P/page.json',
        'conditional_formatting': 'pages/P/visuals/V/visual.json',
        'unknown': 'unrecognized.json', 'stale': 'pages/P/visuals/V/visual.json',
    }
    path = reports[0] / 'definition' / paths[surface]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({surface: {'Measure': {
        'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Unused'}}}), encoding='utf-8')
    before = plans._inventory(plans._roots(model, reports))
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    assert plans._inventory(plans._roots(model, reports)) == before


def test_used_chain_is_not_deletable_as_a_group(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], [('Sales', 'Leaf', '1'), ('Sales', 'Top', '[Leaf]')])
    (reports[0] / 'definition/report.json').write_text(json.dumps({'opaque': 'Sales.Top'}))
    with pytest.raises(plans.PlanError, match='Cannot delete'):
        plans.create_plan(model, reports, [operation(reports[0], 'Leaf', 'Top')])


def test_duplicate_names_across_entities_violate_official_uniqueness(tmp_path):
    model, reports = project(tmp_path)
    (model / 'definition/tables/Other.tmdl').write_text('table Other\n\tcolumn Value\n', encoding='utf-8')
    extension(reports[0], [('Sales', 'Same', '1'), ('Other', 'Same', '2'),
                           ('Sales', 'Consumer', "'Other'[Same]")])
    with pytest.raises(plans.PlanError, match="not unique"):
        plans.create_plan(model, reports, [operation(reports[0], 'Same')])


def test_only_selected_report_participates(tmp_path):
    model, reports = project(tmp_path)
    # An unselected report's use must not retain the same name in selected A.
    (reports[1] / 'definition/report.json').write_text('{"opaque":"Unused"}')
    plan = plans.create_plan(model, [reports[0]], [operation(reports[0], 'Unused')])
    assert plan['changes']
    with pytest.raises(plans.PlanError, match='Unknown or unselected'):
        plans.create_plan(model, [reports[0]], [operation(reports[1], 'Unused')])


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(unknownExpression='[Unused]'),
    lambda d: d.update(entities=None),
    lambda d: d['entities'][0]['measures'][1].update(references={'measures': [{'entity': 'Sales'}]}),
    lambda d: d['entities'][0]['measures'][1].update(expression='SELECTEDMEASURE()'),
    lambda d: d.update({'$schema': 'https://unknown.invalid/schema.json'}),
])
def test_incomplete_extension_metadata_fails_closed(tmp_path, mutation):
    model, reports = project(tmp_path)
    path = reports[0] / 'definition/reportExtensions.json'
    data = json.loads(path.read_bytes())
    mutation(data)
    path.write_text(json.dumps(data), encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    assert path.read_bytes() == before


def test_wrong_model_binding_blocks(tmp_path):
    model, reports = project(tmp_path)
    (reports[0] / 'definition.pbir').write_text('{"datasetReference":{"byPath":{"path":"../Wrong.SemanticModel"}}}')
    with pytest.raises(plans.PlanError, match='bound'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_report_drift_prevents_any_writes(tmp_path):
    model, reports = project(tmp_path)
    plan = plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    path = reports[1] / 'definition/report.json'
    path.write_bytes(b'{"later":true}')
    before = plans._inventory(plans._roots(model, reports))
    with pytest.raises(plans.PlanError, match='Stale plan'):
        plans.apply_plan(plan, tmp_path / 'journal')
    assert plans._inventory(plans._roots(model, reports)) == before


def test_report_identity_cannot_reach_model_writer(tmp_path):
    model, reports = project(tmp_path)
    with pytest.raises(plans.PlanError, match='Report identities'):
        plans.create_plan(model, reports, [{'kind': 'actions', 'actions': [{
            'action': 'delete', 'table': 'Sales', 'name': 'Revenue', 'item_type': 'Measure',
            'report_path': str(reports[0])}]}])


def test_model_name_collision_blocks_report_deletion(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], [('Sales', 'Revenue', '1')])
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [operation(reports[0], 'Revenue')])


@pytest.mark.parametrize('deleted', [('A',), ('B',), ('C',), ('A', 'C'), ('A', 'B'), ('B', 'C'), ('A', 'B', 'C')])
def test_minimal_writer_preserves_all_retained_bytes(tmp_path, deleted):
    from semantic_model_cleaner import report_measure_delete as deletion
    model, reports = project(tmp_path)
    path = extension(reports[0], [('Sales', name, '1 +\n 2') for name in 'ABC'])
    before = path.read_bytes()
    original = json.loads(before)
    text = before.decode()
    spans = deletion._array_spans(text)[('entities', 0, 'measures')]
    retained = [text[start:end].encode() for index, (start, end) in enumerate(spans)
                if 'ABC'[index] not in deleted]
    deletion.delete_definitions(reports, operation(reports[0], *deleted)['entries'])
    after = path.read_bytes()
    assert all(fragment in after for fragment in retained)
    assert b'\r\n' in after and b'\n' not in after.replace(b'\r\n', b'')
    expected = original
    expected['entities'][0]['measures'] = [m for m in expected['entities'][0]['measures'] if m['name'] not in deleted]
    assert json.loads(after) == expected
    # The writer only removes ranges: every remaining byte is original, in order.
    assert len(after) < len(before)


def test_api_and_cli_export_expose_eligibility_and_exact_identity(tmp_path, monkeypatch):
    from semantic_model_cleaner import webapp
    model, reports = project(tmp_path)
    results = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
    for payload in (webapp._serialize_results(results, model_paths=[model]),
                    json.loads(analyzer.format_json_output(results))):
        local = [r for r in payload['items'] if r['name'] == 'Unused']
        assert len(local) == 2
        assert all(r['reportMeasureDelete']['eligible'] for r in local)
        assert {r['reportMeasureDelete']['entry']['report_path'] for r in local} == {str(p) for p in reports}
    monkeypatch.setenv('SMC_USER_DIR', str(tmp_path / 'state'))
    client = webapp.app.test_client()
    response = client.post('/api/plans', json={'model_path': str(model),
        'report_paths': [str(p) for p in reports], 'operations': [operation(reports[0], 'Unused')]})
    assert response.status_code == 200, response.json
    plan = response.json['plan']
    assert client.post(f"/api/plans/{plan['id']}/apply").json['ok']
    assert client.post(f"/api/plans/{plan['id']}/verify").json['ok']
    assert client.post(f"/api/plans/{plan['id']}/restore").json['ok']


def test_report_apply_failure_rolls_back_exact_bytes(tmp_path, monkeypatch):
    model, reports = project(tmp_path)
    op = operation(reports[0], 'Unused')
    op['entries'] += operation(reports[1], 'Unused')['entries']
    plan = plans.create_plan(model, reports, [op])
    before = plans._inventory(plans._roots(model, reports))
    original = plans._atomic
    fired = False
    def fail(path, content):
        nonlocal fired
        if path.name.endswith('.receipt.json') and not fired and b'"completed": [' in content:
            if json.loads(content).get('completed'):
                fired = True
                raise OSError('injected journal failure')
        return original(path, content)
    monkeypatch.setattr(plans, '_atomic', fail)
    result = plans.apply_plan(plan, tmp_path / 'journal')
    assert not result['ok'] and result['receipt']['status'] == 'rolled_back'
    assert plans._inventory(plans._roots(model, reports)) == before


def test_explicit_metadata_consumers_and_unknown_schema_block(tmp_path):
    model, reports = project(tmp_path)
    path = reports[0] / 'definition/reportExtensions.json'
    data = json.loads(path.read_bytes())
    data['entities'][0]['measures'][1]['references'] = {
        'measures': [{'schema': 'extension', 'entity': 'Sales', 'name': 'Unused'}]}
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(plans.PlanError, match='retained'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    data['entities'][0]['measures'][1]['references']['measures'][0]['schema'] = 'foreign'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(plans.PlanError, match='retained report extension'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_duplicate_json_keys_and_unknown_report_schema_block(tmp_path):
    model, reports = project(tmp_path)
    path = reports[0] / 'definition/report.json'
    for content in ('{"field":"Unused","field":"other"}',
                    '{"$schema":"https://unknown.invalid/new-schema","unknown":true}'):
        path.write_text(content)
        with pytest.raises(plans.PlanError):
            plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_missing_and_duplicate_identity_are_rejected(tmp_path):
    model, reports = project(tmp_path)
    for op in (operation(reports[0], 'Gone'), operation(reports[0], 'Unused', 'Unused'),
               {'kind': 'delete_report_measures', 'entries': [{'table': 'Sales', 'name': 'Unused'}]}):
        with pytest.raises(plans.PlanError):
            plans.create_plan(model, reports, [op])


def test_ui_routes_report_deletion_through_reviewed_plan():
    root = Path(__file__).parents[1] / 'src/semantic_model_cleaner'
    html = (root / 'templates/index_v2.html').read_text(encoding='utf-8')
    script = (root / 'static/detail-workspace.js').read_text(encoding='utf-8')
    assert "canQueueReportDelete(item)" in html
    assert "act.report_path = item.reportMeasureDelete.entry.report_path" in html
    assert "kind: 'delete_report_measures'" in script
    assert "entries: local.map" in script


def test_forward_slash_paths_canonicalize_before_staging(tmp_path):
    model, reports = project(tmp_path)
    op = operation(reports[0], 'Unused')
    op['entries'][0]['report_path'] = reports[0].as_posix()
    assert plans.create_plan(model, reports, [op])['changes']


def test_name_only_live_binding_does_not_prove_model_identity(tmp_path):
    model, reports = project(tmp_path)
    (reports[0] / 'definition.pbir').write_text(json.dumps({
        'version': '4.0', 'datasetReference': {'byConnection': {
            'connectionString': 'Data Source=powerbi://example;Initial Catalog=M;'}}}))
    with pytest.raises(plans.PlanError, match='byPath'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_invalid_declared_report_schema_blocks(tmp_path):
    model, reports = project(tmp_path)
    (reports[0] / 'definition/report.json').write_text(json.dumps({
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json',
        'unknownExpression': '1'}))
    with pytest.raises(plans.PlanError, match='Invalid or unsupported'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_cli_plan_diff_apply_verify_restore(tmp_path, capsys):
    from semantic_model_cleaner import plan_cli
    model, reports = project(tmp_path)
    operations = tmp_path / 'operations.json'
    operations.write_text(json.dumps({'schema_version': '1.0',
        'operations': [operation(reports[0], 'Unused')]}), encoding='utf-8')
    plan = tmp_path / 'reviewed.json'
    args = ['plan', str(tmp_path), '--model', str(model), '--report', str(reports[0]),
            '--operations', str(operations), '-o', str(plan), '--format', 'json']
    assert plan_cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)['ok']
    assert plan_cli.main(['diff', str(plan)]) == 0
    assert 'Unused' in capsys.readouterr().out
    for command in ('apply', 'verify', 'restore'):
        assert plan_cli.main([command, str(plan), '--journal-dir', str(tmp_path / 'journal'),
                              '--format', 'json']) == 0
        assert json.loads(capsys.readouterr().out)['ok']


def test_non_json_numeric_constants_block(tmp_path):
    model, reports = project(tmp_path)
    (reports[0] / 'definition/report.json').write_text('{"opaque": NaN}')
    with pytest.raises(plans.PlanError, match='Non-JSON numeric'):
        plans.create_plan(model, reports, [operation(reports[0], 'Unused')])


def test_nonmetadata_report_byte_drift_blocks_apply(tmp_path):
    model, reports = project(tmp_path)
    image = reports[0] / 'image.png'
    image.write_bytes(b'original bytes')
    plan = plans.create_plan(model, reports, [operation(reports[0], 'Unused')])
    image.write_bytes(b'changed bytes')
    with pytest.raises(plans.PlanError, match='Stale plan'):
        plans.apply_plan(plan, tmp_path / 'journal')
