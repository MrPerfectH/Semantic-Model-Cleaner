"""Shared artifact roles for cleanup scans, staging and drift checks.

Resource declarations win over scratch naming. Only the known DAX editor index
is scratch JSON; other JSON and .pbi files retain their metadata guards.
"""
from __future__ import annotations

import json
from pathlib import Path

METADATA_SUFFIXES = {".tmdl", ".json", ".pbir", ".pbism"}


def declared_report_resources(root):
    """Return in-root declared paths, including conservative path collisions.

    Invalid report manifests remain subject to the normal metadata/schema guards;
    this reader does not make them supported or suppress their diagnostics.
    """
    root = Path(root)
    resources = set()
    for manifest in (root / "definition/report.json", root / "report.json"):
        try:
            document = json.loads(manifest.read_bytes())
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(document, dict):
            continue
        packages = document.get("resourcePackages", [])
        if not isinstance(packages, list):
            continue
        for package in packages:
            if not isinstance(package, dict):
                continue
            name, items = package.get("name"), package.get("items", [])
            if not isinstance(name, str) or not isinstance(items, list):
                continue
            for item in items:
                relative = item.get("path") if isinstance(item, dict) else None
                if not isinstance(relative, str):
                    continue
                # PBIR packages are relative to StaticResources/<package>.
                # Also retain a direct in-root path in ambiguous declarations.
                for candidate in (root / "StaticResources" / name / relative,
                                  root / relative):
                    candidate = candidate.resolve()
                    if candidate.is_relative_to(root.resolve()):
                        resources.add(candidate.relative_to(root.resolve()).as_posix().casefold())
    return resources


def artifact_role(root, path, resources):
    """Classify a file, preserving real resources before scratch exclusions."""
    relative = Path(path).relative_to(root).as_posix().casefold()
    if relative in resources or relative.startswith("staticresources/"):
        return "resource"
    if relative == "daxqueries/.pbi/daxqueries.json" or Path(path).suffix.lower() == ".dax":
        return "scratch"
    return "metadata" if Path(path).suffix.lower() in METADATA_SUFFIXES else "resource"
