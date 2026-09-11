"""Schema evidence must reach both reviewed writes and unsuppressible CI output."""
import json
from pathlib import Path

import pytest

from semantic_model_cleaner import change_plan as plans
from semantic_model_cleaner.ci import run_check
from test_change_plans import project, hide_operation


def declared_page(report):
    fixture = Path(__file__).parent / 'fixtures/schema-validation/page-valid.json'
    page = report / 'definition/pages/SchemaProbe/page.json'
    page.parent.mkdir(parents=True)
    page.write_bytes(fixture.read_bytes())
    return page


@pytest.mark.parametrize('change', ['invalid_type', 'remove_declaration'])
def test_plan_rejects_writer_schema_regression_without_touching_sources(tmp_path, monkeypatch, change):
    model, report = project(tmp_path)
    declared_page(report)
    original = plans._inventory(plans._roots(model, [report]))
    execute = plans._execute

    def faulty_writer(operation, roots):
        execute(operation, roots)
        staged_report = next(path for key, path in roots.items() if key != 'model')
        page = staged_report / 'definition/pages/SchemaProbe/page.json'
        document = json.loads(page.read_text())
        if change == 'invalid_type':
            document['width'] = 'not a number'
        else:
            document.pop('$schema')
        page.write_text(json.dumps(document))

    monkeypatch.setattr(plans, '_execute', faulty_writer)
    with pytest.raises(plans.PlanError, match='schema'):
        plans.create_plan(model, [report], [hide_operation(model)])
    assert plans._inventory(plans._roots(model, [report])) == original


def test_ci_schema_errors_remain_visible_under_baseline(tmp_path):
    model, report = project(tmp_path)
    page = declared_page(report)
    document = json.loads(page.read_text())
    document['width'] = 'not a number'
    page.write_text(json.dumps(document))
    _, first = run_check(model.parent.parent)
    baseline = {'schema_version': '1.0', 'fingerprints': [f['fingerprint'] for f in first['findings']]}
    code, output = run_check(model.parent.parent, baseline=baseline)
    errors = [f for f in output['findings'] if f['rule_id'] == 'SMC011']
    assert code == 1
    assert errors and all(not f['suppressed'] for f in errors)
    assert any('SchemaProbe/page.json' in f['path'] for f in errors)
