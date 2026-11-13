"""Public-facing docs must advertise the current release, not an older download."""
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
def test_public_docs_reference_only_the_current_release(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    betas = set(re.findall(r"\d+\.\d+\.\d+b\d+", text))
    assert betas <= {__version__}, f"{relative} mentions {sorted(betas)}, expected only {__version__}"
    assert re.search(rf"(?<![\d.]){re.escape(__version__)}(?![\d.]|b\d)", text), f"{relative} does not mention {__version__}"


def test_landing_page_download_links_point_at_the_current_release():
    html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    assert f"/releases/download/v{__version__}/semantic-model-cleaner-windows-x64-{__version__}.zip" in html
    assert f"/releases/download/v{__version__}/semantic-model-cleaner-windows-x64-{__version__}.zip.sha256" in html
