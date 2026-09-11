"""Fail when package, runtime, and release-tag identities disagree."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semantic_model_cleaner import __release_channel__, __version__  # noqa: E402


def verify(tag: str = "") -> dict:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = project["project"]["version"]
    errors = []
    if package_version != __version__:
        errors.append(f"pyproject version {package_version} != runtime version {__version__}")
    if __release_channel__ != "beta":
        errors.append(f"public beta requires release channel beta, got {__release_channel__}")
    if not re.fullmatch(r"\d+\.\d+\.\d+b\d+", __version__):
        errors.append(f"public beta version is not a PEP 440 beta: {__version__}")
    expected_tag = f"v{__version__}"
    if tag and tag != expected_tag:
        errors.append(f"release tag {tag} != {expected_tag}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "name": project["project"]["name"],
        "version": __version__,
        "channel": __release_channel__,
        "tag": expected_tag,
        "windows_archive": f"semantic-model-cleaner-windows-x64-{__version__}.zip",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="", help="Tag to compare; empty means no tag build")
    args = parser.parse_args()
    print(json.dumps(verify(args.tag), sort_keys=True))


if __name__ == "__main__":
    main()
