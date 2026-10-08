"""Both layouts declare an icon so browsers do not request a missing /favicon.ico."""
import pytest

from semantic_model_cleaner import webapp


@pytest.mark.parametrize('layout', ['classic', 'v2'])
def test_layouts_link_a_served_svg_icon(layout):
    client = webapp.app.test_client()
    html = client.get('/?ui=' + layout).get_data(as_text=True)
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in html
    icon = client.get('/static/favicon.svg')
    assert icon.status_code == 200
    assert icon.mimetype == 'image/svg+xml'
    assert b'<svg' in icon.get_data()
