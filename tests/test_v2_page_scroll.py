"""Result tables must not shrink into a small nested scroller (#133)."""
import re

from semantic_model_cleaner.webapp import app


def _css_rule(html, selector):
    match = re.search(r'(?m)^' + re.escape(selector) + r' \{([^}]*)\}', html)
    assert match, selector
    return match.group(1)


def test_result_tables_keep_a_viewport_height_when_content_above_grows():
    html = app.test_client().get('/?ui=v2').get_data(as_text=True)
    rule = _css_rule(html, '.table-container')
    # A flexible basis let the expanded guide squeeze the table to its minimum
    # height, trapping the wheel in a tiny inner scroller.
    assert 'flex: none' in rule
    assert 'height: max(420px, calc(100dvh - 210px))' in rule
    assert '.table-container, .detail-panel { flex-shrink: 1 !important; }' not in html
