"""Reports screen leads with what is missing from the model (variant A)."""
from pathlib import Path

from semantic_model_cleaner.webapp import app

ROOT = Path(__file__).resolve().parents[1] / 'src/semantic_model_cleaner'


def test_reports_screen_loads_missing_items_after_navigation():
    html = app.test_client().get('/?ui=v2').get_data(as_text=True)
    assert html.index('workspace-navigation.js') < html.index('missing-items.js')
    assert html.index('detail-workspace.js') < html.index('missing-items.js')
    assert app.test_client().get('/static/missing-items.js').status_code == 200


def test_finding_rows_filter_by_missing_item_and_problem_type():
    template = (ROOT / 'templates/index_v2.html').read_text(encoding='utf-8')
    assert "issue.missingItemKey !== reportIssueMissingItemFilter" in template
    assert "issue.issueType !== reportIssueTypeFilter" in template
    # The grouped list replaces root-cause cards and the raw findings panel.
    assert '#rootCausePanel, #reportHealthBanner { display: none !important; }' in template


def test_fixes_go_through_the_reviewed_plan_and_schema_moves_to_scan_details():
    module = (ROOT / 'static/missing-items.js').read_text(encoding='utf-8')
    navigation = (ROOT / 'static/workspace-navigation.js').read_text(encoding='utf-8')
    assert 'window.smcReviewOperations([op]' in module
    assert "kind: 'report_repair'" in module
    assert '/api/report/' not in module, 'No direct writes from the Reports list'
    assert "$('analysisLimitationsBanner').after(schemaPanel)" in navigation
    assert 'reportInventory' not in navigation
