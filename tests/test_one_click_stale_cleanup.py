"""Stale Report References are cleaned in one click with Undo (#129)."""
from pathlib import Path

from semantic_model_cleaner.webapp import app

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'semantic_model_cleaner' / 'static'


def test_report_health_offers_one_click_clean_and_optional_review():
    html = app.test_client().get('/?ui=v2').get_data(as_text=True)
    assert 'Clean stale references' in html
    assert 'Review changes first' in html
    # The raw File:/Reference: preview wall and the second apply step are gone.
    assert 'Apply stale cleanup' not in html
    assert 'reportHealthPreviewList' not in html
    assert 'previewReportHealthStaleCleanup' not in html
    assert "'File: ' + file" not in html


def test_one_click_cleanup_uses_the_validated_plan_path_and_offers_undo():
    source = (STATIC / 'detail-workspace.js').read_text(encoding='utf-8')
    start = source.index('async function quickCleanStale(')
    body = source[start:source.index('window.smcQuickCleanStale', start)]
    # Same write path as reviewed plans (ADR 0001): create, then apply the sealed plan.
    assert "apiPost('/api/plans', { operations: [{ kind: 'clean_stale'" in body
    assert "'/apply'" in body
    assert "'/restore'" in body
    assert 'Undo' in body and 'Show changes' in body
    # Anything that needs a human confirmation still goes through the review drawer.
    assert 'confirmations' in body and 'reviewOperations(' in body
    assert "cleanCurrentItemStaleRefs = function () { var item = getItemByKey(detailItemKey); if (item) return quickCleanStale(" in source


def test_stale_group_description_no_longer_asks_for_a_preview():
    from semantic_model_cleaner import webapp
    source = Path(webapp.__file__).read_text(encoding='utf-8')
    assert 'can be previewed before applying repairs' not in source
    assert 'can be removed automatically' in source
