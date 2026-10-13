"""The default object workspace must ship as a self-contained browser surface."""
from semantic_model_cleaner.webapp import app


def test_v2_serves_detail_workspace_assets():
    client = app.test_client()
    response = client.get('/?ui=v2')
    assert response.status_code == 200
    assert b'detail-workspace.js' in response.data
    assert b'detail-workspace.css' in response.data
    for path, marker in [
        ('/static/detail-workspace.js', b'aria-controls'),
        ('/static/detail-workspace.css', b'focus-visible'),
    ]:
        asset = client.get(path)
        assert asset.status_code == 200
        assert marker in asset.data


def test_v2_navigation_uses_native_buttons():
    html = app.test_client().get('/?ui=v2').get_data(as_text=True)
    assert '<div class="view-tab' not in html
    assert 'data-view="details" id="tabDetails"' in html


def test_v2_analysis_limitations_have_their_own_view_not_a_banner_everywhere():
    html = app.test_client().get('/?ui=v2').get_data(as_text=True)
    assert 'data-view="limitations" id="tabLimitations"' in html
    assert 'body:not(.limitations-view) #analysisLimitationsBanner { display: none !important; }' in html
    assert "document.body.classList.toggle('limitations-view', view === 'limitations');" in html
