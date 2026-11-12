"""Semantic Model Cleaner package."""

import re

__all__ = ["__release_channel__", "__version__"]

__version__ = "0.4.0b10"
# A PEP 440 pre-release (a, b, rc, dev) ships on the beta channel; a final version ships stable.
__release_channel__ = "beta" if re.search(r"(a|b|rc|\.dev)\d+$", __version__) else "stable"
