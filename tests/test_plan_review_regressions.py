"""Independent plan review regressions; run against integrated plan modules."""
import json

import pytest

from semantic_model_cleaner import change_plan, plan_cli


def project(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    report = tmp_path / 'R.Report'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tmeasure Revenue = 1\n\tcolumn Spare\n')
    (report / 'definition').mkdir(parents=True)
    (report / 'definition/report.json').write_text('{}')
    (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../M.SemanticModel'}}}))
    return model, report


def hide():
    return {'kind': 'actions', 'actions': [{'action': 'hide', 'table': 'Sales', 'name': 'Revenue', 'item_type': 'Measure'}]}


def test_plan_rejects_second_identical_missing_reference_in_different_visual(tmp_path):
    model, report = project(tmp_path)
    for visual, name in [('A', 'Gone'), ('B', 'Spare')]:
        path = report / 'definition/pages/P/visuals' / visual / 'visual.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'visual': {'query': {'Column': {
            'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': name}}}}))
    with pytest.raises(change_plan.PlanError, match='unresolved references'):
        change_plan.create_plan(model, [report], [{'kind': 'report_repair',
            'column_renames': [{'table': 'Sales', 'name': 'Spare', 'target_name': 'Gone'}]}])


def test_cli_plan_output_cannot_overwrite_selected_metadata(tmp_path, capsys):
    model, report = project(tmp_path)
    ops = tmp_path / 'operations.json'
    ops.write_text(json.dumps([hide()]))
    target = report / 'definition/report.json'
    before = target.read_bytes()
    code = plan_cli.main(['plan', str(tmp_path), '--model', str(model), '--report', str(report),
                         '--operations', str(ops), '-o', str(target)])
    capsys.readouterr()
    assert code == 2
    assert target.read_bytes() == before


def test_apply_rejects_journal_directory_inside_selected_scope(tmp_path):
    model, report = project(tmp_path)
    plan = change_plan.create_plan(model, [report], [hide()])
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    with pytest.raises(change_plan.PlanError):
        change_plan.apply_plan(plan, model / 'journals')
    assert change_plan._inventory(roots) == before


def test_relative_report_action_path_never_mutates_original_during_preview(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    target = report / 'definition/pages/P/visuals/V/visual.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'visual': {'query': {'Column': {
        'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Spare'}}}}))
    before = target.read_bytes()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, [report], [{'kind': 'report_issues', 'entries': [{
            'report_path': 'R.Report', 'artifact_path': 'definition/pages/P/visuals/V/visual.json',
            'source_path': 'visual.query.Column', 'table': 'Sales', 'name': 'Spare',
            'action': 'replace', 'target_table': 'Sales', 'target_name': 'Gone',
        }]}])
    assert target.read_bytes() == before
