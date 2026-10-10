"""Public-facing docs must advertise the current beta, not an older download."""
from pathlib import Path
import re

import pytest

from semantic_model_cleaner import __version__


ROOT = Path(__file__).parents[1]
PUBLIC_DOCS = [
    "README.md",
    "docs/index.html",  # GitHub Pages landing page
    "docs/quickstart.md",
    "docs/support.md",
]


@pytest.mark.parametrize("relative", PUBLIC_DOCS)
def test_public_docs_reference_only_the_current_beta(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    versions = set(re.findall(r"\d+\.\d+\.\d+b\d+", text))
    assert versions == {__version__}, f"{relative} mentions {sorted(versions)}, expected only {__version__}"


def test_landing_page_download_links_point_at_the_current_release():
    html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    assert f"/releases/download/v{__version__}/semantic-model-cleaner-windows-x64-{__version__}.zip" in html
    assert f"/releases/download/v{__version__}/semantic-model-cleaner-windows-x64-{__version__}.zip.sha256" in html
