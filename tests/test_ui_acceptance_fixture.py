"""The UI acceptance fixture exercises the real analyzer and reviewed writers."""
from collections import Counter
import importlib.util
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, change_plan, metadata_validation, webapp


spec = importlib.util.spec_from_file_location('ui_fixture',
    Path(__file__).parents[1] / 'scripts/generate_ui_acceptance_fixture.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_fixture_real_analysis_reference_visibility_and_dependency_direction(tmp_path):
    fixture = generator.generate_fixture(tmp_path / 'fixture')
    model, reports = fixture['model'], fixture['reports']
    assert all(analyzer.report_binding_status(report, model)['status'] == 'connected' for report in reports)
    validation = metadata_validation.validate_report_paths(reports, workspace=fixture['root'])
    assert validation['ok'], [file for file in validation['files'] if file['status'] != 'valid']
    assert validation['counts']['not_validated'] == 0
    result = analyzer.analyze(fixture['root'], model_paths=[model], report_paths=reports)
    assert result['coverage']['complete']
    payload = webapp._serialize_results(result, model_paths=[str(model)])
    sales = next(table for table in payload['tables'] if table['name'] == 'Sales')
    assert len(sales['items']) == sales['itemCount'] == 45
    items = {item['name']: item for item in sales['items']}
    assert set(Counter(item['deleteSafety'] for item in payload['items'])) == {'Safe', 'Review', 'Blocked', 'Keep'}
    assert items['Revenue']['usageState'] == 'Used'
    assert items['Amount']['usageState'] == 'Indirect'
    assert not items['Amount']['usageDetails']
    assert ('Sales', 'Amount') in {(item['table'], item['name']) for item in items['Revenue']['dependencyItems']}
    assert ('Sales', 'Revenue') in {(item['table'], item['name']) for item in items['Amount']['dependentItems']}
    assert ('Sales', 'Amount') not in {(item['table'], item['name']) for item in items['Revenue']['dependentItems']}
    references = items['Revenue']['usageDetails']
    assert len({(row['reportPath'], row['artifactPath'], row['sourcePath']) for row in references}) >= 150
    assert Counter((row['pageHidden'], row['visualHidden']) for row in references) == {
        (False, False): 40, (False, True): 40, (True, False): 40, (True, True): 40,
    }
    assert items['DateKey']['relationshipRefCount'] == 1
    assert items['DateKey']['deleteSafety'] == 'Blocked'
    assert items['SortOrder']['otherModelUses'] == ['Sort']
    assert items['SortOrder']['deleteSafety'] == 'Blocked'
    assert items['Safe Cleanup Candidate']['deleteSafety'] == 'Safe'
    assert items['Safe Cleanup Candidate']['usageState'] == 'Unused'
    assert items['Unused Base']['removalRisk'] == 'Caution'
    assert items['Hidden Notes']['deleteSafety'] == 'Review'
    assert items['Inferred Value']['deleteSafety'] == 'Keep'
    assert items['Broken Revenue']['issueState'] == 'Broken'
    assert generator.LONG_NAME in items and generator.QUOTED_NAME in items
    local = items['Revenue vs Target']
    assert local['sourceKind'] == 'report'
    assert Path(local['sourceFile']).is_relative_to(reports[0])
    assert ('Sales', 'Report Target') in {(item['table'], item['name']) for item in local['dependencyItems']}
    assert {'missing_measure', 'stale_visual_selector'} <= {issue['issueType'] for issue in result['report_issues']}


def test_fixture_promotion_closure_and_safe_cleanup_are_real_restorable_plans(tmp_path):
    fixture = generator.generate_fixture(tmp_path / 'fixture')
    before = snapshot(fixture['root'])
    proof = generator.describe_fixture(fixture)
    assert proof['promotion_without_dependencies']['ok'] is False
    assert [item['name'] for item in proof['promotion_without_dependencies']['required_dependencies']] == ['Report Target']
    assert proof['promotion_with_dependencies']['ok'] is True
    assert [item['name'] for item in proof['promotion_with_dependencies']['promotions']] == ['Report Target', 'Revenue vs Target']
    assert snapshot(fixture['root']) == before
    promotion = {'kind': 'promote', 'report_path': str(fixture['reports'][0]),
                 'table': 'Sales', 'name': 'Revenue vs Target'}
    with pytest.raises(change_plan.PlanError, match='dependencies'):
        change_plan.create_plan(fixture['model'], fixture['reports'], [promotion])
    for operation in (
        {**promotion, 'include_dependencies': True},
        {'kind': 'actions', 'actions': [{'action': 'delete', 'table': 'Sales',
          'name': 'Safe Cleanup Candidate', 'item_type': 'Measure'}]},
    ):
        plan = change_plan.create_plan(fixture['model'], fixture['reports'], [operation])
        assert plan['changes']
        assert snapshot(fixture['root']) == before
        applied = change_plan.apply_plan(plan, tmp_path / 'journal')
        assert applied['ok'], applied
        assert change_plan.verify_plan(plan)['ok']
        if operation['kind'] == 'promote':
            names = {item.name for item in analyzer.parse_model_items(fixture['model'])}
            assert {'Report Target', 'Revenue vs Target'} <= names
        else:
            assert 'Safe Cleanup Candidate' not in {item.name for item in analyzer.parse_model_items(fixture['model'])}
        assert change_plan.restore_plan(plan, tmp_path / 'journal')['ok']
        assert snapshot(fixture['root']) == before


def test_fixture_is_deterministic_and_refuses_existing_content(tmp_path, capsys):
    first = generator.generate_fixture(tmp_path / 'first')
    empty = tmp_path / 'second'
    empty.mkdir()
    second = generator.generate_fixture(empty)
    original = snapshot(first['root'])
    assert snapshot(second['root']) == original
    assert generator.main([str(first['root'])]) == 2
    assert 'refusing' in capsys.readouterr().out
    assert snapshot(first['root']) == original
    output_file = tmp_path / 'file'
    output_file.write_text('retain this')
    with pytest.raises(ValueError):
        generator.generate_fixture(output_file)
    assert output_file.read_text() == 'retain this'


def test_fixture_refuses_output_symlinks(tmp_path):
    target = tmp_path / 'existing'
    target.mkdir()
    (target / 'keep.txt').write_text('retain this')
    original = snapshot(target)
    link = tmp_path / 'link'
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('This host does not allow creating directory symlinks.')
    with pytest.raises(ValueError):
        generator.generate_fixture(link)
    assert snapshot(target) == original
