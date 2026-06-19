#!/usr/bin/env python3
"""
Semantic Model Cleaner — Flask Web App

Local web interface for analyzing Power BI semantic models,
viewing usage results, and performing cleanup actions (move to folder, hide, delete).

Usage:
    semantic-model-cleaner-web [workspace_path]
    semantic-model-cleaner-web --models-path /path/to/models --reports-path /path/to/reports
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import __version__, analyzer, experiments, file_transaction, model_compare, report_writer, tmdl_writer

app = Flask(__name__)

# ── Global state ──────────────────────────────────────────────────────────────

_state = {
    "workspace": None,
    "model_search_roots": None,
    "report_search_roots": None,
    "runtime": experiments.runtime_config(),
    "last_results": None,
    "model_paths": [],
    "report_paths": [],
    "backup_path": None,
    "last_compare_results": None,
}

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:(?![\\/])")


def _cleanup_transaction_roots(model_path: Path | None = None, report_paths: list[Path] | None = None) -> list[Path]:
    roots: list[Path] = []
    if model_path is not None:
        roots.append(model_path / "definition")
    roots.extend(report_path / "definition" for report_path in report_paths or [])
    return roots


def _restore_cleanup_transaction(roots: list[Path], snapshot: dict[Path, str]) -> dict:
    return file_transaction.restore_artifact_files(roots, snapshot)


def _cleanup_action_model_path(data: dict) -> tuple[Path | None, tuple[dict, int] | None]:
    model_path_str = data.get("model_path")
    if not model_path_str:
        if _state["model_paths"]:
            model_path_str = _state["model_paths"][0]
        else:
            return None, ({"error": "No model path specified"}, 400)

    model_path = Path(model_path_str)
    if not model_path.exists():
        return None, ({"error": f"Model path not found: {model_path}"}, 400)
    return model_path, None


def _cleanup_action_plan_response(
    model_path: Path,
    actions: list[dict],
    *,
    create_backup: bool,
    auto_refresh: bool | None = None,
) -> dict:
    plan = tmdl_writer.plan_actions(model_path, actions)
    plan["create_backup"] = create_backup
    plan["backup"] = {
        "requested": create_backup,
        "mode": "will_create_before_apply" if create_backup else "not_requested",
    }
    if auto_refresh is not None:
        plan["auto_refresh"] = auto_refresh
    return plan


def _cleanup_action_invalid_results(plan: dict) -> list[dict]:
    return [
        {
            **entry,
            "ok": False,
            "validated": False,
            "written": False,
            "skipped": bool(entry.get("ok")),
            "error": entry.get("error") or "Skipped because another action in the batch is invalid.",
        }
        for entry in plan.get("actions", [])
    ]


def _normalize_browse_path(raw: str) -> str:
    """Normalize browser-submitted paths before pathlib resolves them.

    The frontend explorer can submit Windows drive paths. On Windows, make sure
    they stay absolute even if the browser/UI drops the slash after the drive
    letter or prefixes the path with an extra slash.
    """
    path = (raw or "").strip()
    if not path or os.name != "nt":
        return path

    path = path.replace("/", "\\")
    if re.match(r"^\\[A-Za-z]:", path):
        path = path[1:]
    if _WINDOWS_DRIVE_PATH.match(path):
        path = path[:2] + "\\" + path[2:].lstrip("\\")
    return path


def _default_workspace_root() -> Path:
    """Use the current working directory as the local-first default root."""
    return Path.cwd().resolve()


def _paths_match(a: Path, b: Path) -> bool:
    """Compare two resolved paths, tolerating case differences on case-insensitive filesystems."""
    if a == b:
        return True
    try:
        return a.samefile(b)
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _platform_display_name(artifact_path: Path) -> str:
    """Read the Fabric display name from an artifact's .platform file, if present.

    The folder name (e.g. PMRA_POC.SemanticModel) is only a local convention;
    the .platform metadata.displayName is the name the artifact is published
    under, so it is what live report connections refer to.
    """
    platform_file = artifact_path / ".platform"
    if not platform_file.is_file():
        return ""
    try:
        payload = json.loads(platform_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    display_name = metadata.get("displayName") if isinstance(metadata, dict) else None
    return display_name.strip() if isinstance(display_name, str) else ""


def _user_data_dir() -> Path:
    return Path(os.environ.get("SMC_USER_DIR") or Path.home() / ".semantic-model-cleaner")


def _bundled_demo_workspace_root() -> Path:
    return Path(__file__).resolve().parent / "demo_workspace"


def _extract_tmdl_table_source_details(model_path: Path | None) -> dict[str, str]:
    """Return table-level source blocks (Power Query / M) when they can be parsed."""
    if model_path is None:
        return {}

    tables_dir = model_path / "definition" / "tables"
    if not tables_dir.exists():
        return {}

    source_by_table: dict[str, str] = {}

    for filepath in sorted(tables_dir.glob("*.tmdl")):
        try:
            lines = filepath.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        current_table = ""
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not line.startswith("\t") and line.startswith("table "):
                current_table = line[6:].strip().strip("'\"")
                i += 1
                continue

            if not current_table:
                i += 1
                continue

            if line.startswith("\t\tsource"):
                rhs = ""
                if "=" in stripped:
                    rhs = stripped.split("=", 1)[1].strip()
                block_lines = []
                if rhs and rhs != "```":
                    block_lines.append(rhs)

                j = i + 1
                while j < len(lines):
                    inner = lines[j]
                    if inner.startswith("\t\t\t"):
                        cleaned = inner.strip()
                        if cleaned and cleaned != "```":
                            block_lines.append(cleaned)
                        j += 1
                        continue
                    if not inner.strip():
                        j += 1
                        continue
                    break

                if block_lines and current_table not in source_by_table:
                    source_by_table[current_table] = "\n".join(block_lines)
                i = j
                continue

            i += 1

    return source_by_table


def _table_usage_status(table_summary: dict) -> str:
    """Map table summary metrics to the same status families used for items."""
    if table_summary.get("field_parameter_issues"):
        count = len(table_summary.get("field_parameter_issues", []))
        noun = "target" if count == 1 else "targets"
        return f"BROKEN ({count} field parameter {noun})"
    used_items = int(table_summary.get("used_item_count", 0) or 0)
    usage_refs = int(table_summary.get("usage_ref_count", 0) or 0)

    if used_items == 0:
        return "NOT USED"
    if usage_refs == 0:
        return "INDIRECT (via: model dependencies)"
    return "USED"


def _table_usage_state(table_summary: dict) -> str:
    used_items = int(table_summary.get("used_item_count", 0) or 0)
    usage_refs = int(table_summary.get("usage_ref_count", 0) or 0)
    if used_items == 0:
        return "Unused"
    if usage_refs == 0:
        return "Indirect"
    return "Used"


def _table_issue_state(table_summary: dict) -> str:
    return "Broken" if table_summary.get("field_parameter_issues") else ""


def _ensure_default_workspace_config() -> None:
    if _state["workspace"]:
        return
    default_root = _default_workspace_root()
    _state["workspace"] = str(default_root)
    if not _state["model_search_roots"]:
        _state["model_search_roots"] = [str(default_root)]
    if not _state["report_search_roots"]:
        _state["report_search_roots"] = [str(default_root)]


def _effective_model_roots() -> list[str]:
    _ensure_default_workspace_config()
    return _state["model_search_roots"] or ([_state["workspace"]] if _state["workspace"] else [])


def _effective_report_roots() -> list[str]:
    _ensure_default_workspace_config()
    return _state["report_search_roots"] or ([_state["workspace"]] if _state["workspace"] else [])


def _discover_initial_artifacts() -> tuple[list[Path], list[Path]]:
    model_roots = [Path(r) for r in _effective_model_roots()]
    report_roots = [Path(r) for r in _effective_report_roots()]
    models = analyzer.discover_models(model_roots)
    reports = analyzer.discover_reports(report_roots)
    return models, reports


def _default_model_selection(models: list[Path]) -> list[Path]:
    if not models:
        return []
    return [models[0]]


def configure_runtime(
    *,
    workspace: str = ".",
    models_path: list[str] | None = None,
    reports_path: list[str] | None = None,
) -> None:
    root = _default_workspace_root()
    _state["workspace"] = str(root)
    _state["model_search_roots"] = [str(root)]
    _state["report_search_roots"] = [str(root)]

    if workspace and workspace != ".":
        selected_root = str(Path(workspace).resolve())
        _state["workspace"] = selected_root
        _state["model_search_roots"] = [selected_root]
        _state["report_search_roots"] = [selected_root]

    if models_path:
        _state["model_search_roots"] = [str(Path(p).resolve()) for p in models_path]
    if reports_path:
        _state["report_search_roots"] = [str(Path(p).resolve()) for p in reports_path]


def print_startup_banner(host: str, port: int, *, debug: bool, mode: str = "web") -> None:
    print("\n  Semantic Model Cleaner")
    print("  ─────────────────────")
    print(f"  Mode      : {mode}")
    print(f"  Workspace : {_state['workspace']}")
    if _state["model_search_roots"]:
        print(f"  Models    : {', '.join(_state['model_search_roots'])}")
    if _state["report_search_roots"]:
        print(f"  Reports   : {', '.join(_state['report_search_roots'])}")
    print(f"  URL       : http://{host}:{port}")
    print(f"  Debug     : {'on' if debug else 'off'}")
    print()


_REPORT_HEALTH_ISSUE_GROUPS = {
    "invalid_pbir_json": {
        "label": "Invalid PBIR JSON",
        "description": "PBIR files could not be parsed, so report analysis may be incomplete until they are repaired.",
    },
    "report_extension_metadata": {
        "label": "Report Extension Measures",
        "description": "Report-level measure metadata needs review before promotion or cleanup decisions.",
    },
    "report_metadata": {
        "label": "Report Metadata Issues",
        "description": "Report metadata needs review before relying on cleanup recommendations.",
    },
}


def _report_health_issue_group_key(issue: dict) -> str:
    issue_type = str(issue.get("issueType", "") or "")
    artifact_kind = str(issue.get("artifactKind", "") or "")
    if issue_type == "invalid_report_json":
        return "invalid_pbir_json"
    if issue_type.startswith("invalid_report_extension") or issue_type == "report_extension_unrecognized_reference":
        return "report_extension_metadata"
    if artifact_kind == "Report Extension":
        return "report_extension_metadata"
    return "report_metadata"


def _highest_severity(items: list[dict]) -> str:
    rank = {"error": 0, "warning": 1, "info": 2}
    severity = "info"
    for item in items:
        candidate = str(item.get("severity", "warning") or "warning")
        if rank.get(candidate, 2) < rank.get(severity, 2):
            severity = candidate
    return severity


# The Report Health banner only previews a few rows per group; the full issue
# list ships separately in reportIssues. Keeping every issue inside each group
# too made /api/analyze responses balloon to tens of MB on large workspaces.
_REPORT_HEALTH_PREVIEW_LIMIT = 5


def _build_report_health(report_issues: list[dict], items: list[dict]) -> dict:
    groups: list[dict] = []

    def _group(
        key: str,
        *,
        label: str,
        severity: str,
        count: int,
        description: str,
        issues: list[dict] | None = None,
        group_items: list[dict] | None = None,
        action: dict | None = None,
    ) -> dict:
        issues = issues or []
        group_items = group_items or []
        return {
            "key": key,
            "label": label,
            "severity": severity,
            "count": count,
            "description": description,
            "issues": issues[:_REPORT_HEALTH_PREVIEW_LIMIT],
            "issueCount": len(issues),
            "items": group_items[:_REPORT_HEALTH_PREVIEW_LIMIT],
            "itemCount": len(group_items),
            "action": action,
        }

    for key in ("invalid_pbir_json", "report_extension_metadata", "report_metadata"):
        issues = [issue for issue in report_issues if _report_health_issue_group_key(issue) == key]
        if not issues:
            continue
        meta = _REPORT_HEALTH_ISSUE_GROUPS[key]
        groups.append(_group(
            key,
            label=meta["label"],
            severity=_highest_severity(issues),
            count=len(issues),
            description=meta["description"],
            issues=issues,
        ))

    stale_items = [
        {
            "type": item.get("type", ""),
            "table": item.get("table", ""),
            "name": item.get("name", ""),
            "staleUsageCount": item.get("staleUsageCount", 0),
        }
        for item in items
        if item.get("staleUsageCount", 0) > 0
    ]
    stale_count = sum(item["staleUsageCount"] for item in stale_items)
    if stale_count:
        groups.append(_group(
            "stale_report_references",
            label="Stale Report References",
            severity="warning",
            count=stale_count,
            description=(
                "Stale PBIR selectors no longer match live visual or bookmark query fields. "
                "Preview cleanup before applying repairs."
            ),
            group_items=stale_items,
            action={
                "type": "cleanup_stale",
                "label": "Preview stale cleanup",
                "entryCount": stale_count,
            },
        ))

    broken_items = [
        {
            "type": item.get("type", ""),
            "table": item.get("table", ""),
            "name": item.get("name", ""),
            "brokenDaxRefs": item.get("brokenDaxRefs", []),
        }
        for item in items
        if item.get("brokenDaxRefs")
    ]
    broken_count = sum(len(item["brokenDaxRefs"]) for item in broken_items)
    if broken_count:
        groups.append(_group(
            "broken_model_references",
            label="Broken Model References",
            severity="error",
            count=broken_count,
            description="Unresolved DAX references block confident cleanup until the broken model dependency is resolved.",
            group_items=broken_items,
        ))

    unsupported_items = []
    unsupported_count = 0
    for item in items:
        triggers = [
            trigger for trigger in item.get("reviewTriggers", [])
            if str(trigger).startswith("Unsupported Metadata:")
        ]
        if not triggers:
            continue
        unsupported_count += len(triggers)
        unsupported_items.append({
            "type": item.get("type", ""),
            "table": item.get("table", ""),
            "name": item.get("name", ""),
            "reviewTriggers": triggers,
        })
    if unsupported_count:
        groups.append(_group(
            "unsupported_metadata",
            label="Unsupported Metadata",
            severity="warning",
            count=unsupported_count,
            description=(
                "Cleanup recommendations were downgraded to Review because documented metadata "
                "can hide dependencies the app does not fully analyze yet."
            ),
            group_items=unsupported_items,
        ))

    return {
        "totalIssueCount": sum(group["count"] for group in groups),
        "groups": groups,
    }


# Root-cause grouping collapses the flat report-issue list into a handful of
# cards keyed by the missing target (broken refs) or selector (stale refs), so a
# single model-side rename that produced thousands of issues reads as one card.
# Presentation-only: it never asserts a rename or applies an action — see
# docs/adr/0001-report-issue-grouping-is-presentation-only.md.
_ROOT_CAUSE_BROKEN_TYPES = {"missing_table", "missing_column", "missing_measure", "missing_report_measure"}
_ROOT_CAUSE_STALE_TYPES = {"stale_visual_selector", "stale_bookmark_projection", "stale_formatting_rule"}


def _report_issue_is_hidden(issue: dict) -> bool:
    return bool(issue.get("visualHidden") or issue.get("pageHidden"))


def _root_cause_group_for_issue(issue: dict) -> tuple[str, str] | None:
    """Return (kind, targetLabel) for a groupable issue, or None to leave it out
    of the cards (it is still counted in the impact totals)."""
    issue_type = str(issue.get("issueType", "") or "")
    if issue_type in _ROOT_CAUSE_BROKEN_TYPES:
        table = str(issue.get("table", "") or "").strip()
        return "broken", table or "(unknown table)"
    if issue_type in _ROOT_CAUSE_STALE_TYPES:
        selector = str(issue.get("selectorValue", "") or "").strip()
        table = str(issue.get("table", "") or "").strip()
        name = str(issue.get("name", "") or "").strip()
        label = selector or (f"{table}[{name}]" if table else "") or "(stale reference)"
        return "stale", label
    return None


def _build_report_root_cause_groups(report_issues: list[dict]) -> dict:
    total = len(report_issues)
    hidden_total = sum(1 for issue in report_issues if _report_issue_is_hidden(issue))

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    groups: dict[str, dict] = {}
    grouped_count = 0
    for issue in report_issues:
        target = _root_cause_group_for_issue(issue)
        if target is None:
            continue
        grouped_count += 1
        kind, label = target
        group_key = f"{kind}:{label.casefold()}"
        # Stamp the key onto the serialized issue so the frontend filters by it
        # directly rather than recomputing the casing in JS — Python str.casefold()
        # and JS toLowerCase() diverge on non-ASCII identifiers (ß, final sigma, …),
        # which would otherwise make a card filter the table to an empty set.
        issue["rootCauseGroupKey"] = group_key
        group = groups.get(group_key)
        if group is None:
            group = {
                "kind": kind,
                "targetLabel": label,
                "groupKey": group_key,
                "totalCount": 0,
                "visibleCount": 0,
                "hiddenCount": 0,
                "_reports": set(),
                "_pages": set(),
                "_issueTypes": set(),
                "_severityRank": severity_rank["info"],
                "sampleLocations": [],
                "topHint": None,
            }
            groups[group_key] = group
        hidden = _report_issue_is_hidden(issue)
        group["totalCount"] += 1
        group["hiddenCount" if hidden else "visibleCount"] += 1
        if issue.get("report"):
            group["_reports"].add(issue["report"])
        if issue.get("page"):
            group["_pages"].add(issue["page"])
        if issue.get("issueType"):
            group["_issueTypes"].add(issue["issueType"])
        group["_severityRank"] = min(
            group["_severityRank"], severity_rank.get(issue.get("severity", "warning"), severity_rank["info"])
        )
        if len(group["sampleLocations"]) < _REPORT_HEALTH_PREVIEW_LIMIT:
            group["sampleLocations"].append({
                "report": issue.get("report", ""),
                "page": issue.get("page", ""),
                "visualId": issue.get("visualId", ""),
                "artifactPath": issue.get("artifactPath", ""),
                "hidden": hidden,
            })
        if group["topHint"] is None:
            for suggestion in issue.get("suggestions", []) or []:
                if suggestion.get("action") == "suggest_replace" and suggestion.get("table") and suggestion.get("name"):
                    group["topHint"] = {
                        "table": suggestion["table"],
                        "name": suggestion["name"],
                        "confidence": suggestion.get("confidence", ""),
                    }
                    break

    serialized_groups = [
        {
            "kind": group["kind"],
            "targetLabel": group["targetLabel"],
            "groupKey": group["groupKey"],
            "totalCount": group["totalCount"],
            "visibleCount": group["visibleCount"],
            "hiddenCount": group["hiddenCount"],
            "reportCount": len(group["_reports"]),
            "pageCount": len(group["_pages"]),
            "issueTypes": sorted(group["_issueTypes"]),
            "severity": ("error", "warning", "info")[group["_severityRank"]],
            "sampleLocations": group["sampleLocations"],
            "topHint": group["topHint"],
        }
        for group in groups.values()
    ]
    # Visible-first: groups touching visible report surfaces sort ahead, then by size.
    serialized_groups.sort(key=lambda g: (-g["visibleCount"], -g["totalCount"], g["targetLabel"].casefold()))

    return {
        "totalCount": total,
        "visibleCount": total - hidden_total,
        "hiddenCount": hidden_total,
        "groupedCount": grouped_count,
        "groups": serialized_groups,
    }


def _serialize_results(results: dict) -> dict:
    """Serialize analyzer results for JSON API responses."""
    def _issue_state(status: str, broken_refs: list[str] | None, stale_usage_count: int = 0) -> str:
        has_broken = (status or "").startswith("BROKEN") or bool(broken_refs)
        has_stale = stale_usage_count > 0
        if has_broken and has_stale:
            return "Broken + Stale"
        if has_broken:
            return "Broken"
        if has_stale:
            return "Stale"
        return ""

    def _usage_state(
        *,
        status: str,
        usage_count: int,
        measure_dependent_count: int,
        relationship_ref_count: int,
        other_model_use_count: int,
        stale_usage_count: int,
    ) -> str:
        if usage_count > 0:
            return "Used"
        if (
            (status or "").startswith("INDIRECT")
            or measure_dependent_count > 0
            or relationship_ref_count > 0
            or other_model_use_count > 0
        ):
            return "Indirect"
        if stale_usage_count > 0:
            return "Stale only"
        return "Unused"

    def _delete_safety(item_payload: dict) -> str:
        if item_payload.get("isInferred"):
            return "Keep"
        if item_payload.get("status", "").startswith("BROKEN"):
            return "Blocked"
        risk = item_payload.get("removalRisk") or ""
        if risk == "Safe":
            return "Safe"
        if risk == "Review":
            return "Review"
        if risk == "Do not remove":
            return "Keep"
        if risk == "Caution":
            return "Blocked"
        if analyzer.is_used_status(item_payload.get("status", "")):
            return "Blocked"
        return "Review"

    items_by_key = {r["item"].key: r["item"] for r in results["items"]}
    rows_by_key = {r["item"].key: r for r in results["items"]}
    model_name = results.get("summary", {}).get("models", [""])[0]
    model_path = next((Path(p) for p in _state.get("model_paths", []) if Path(p).name == model_name), None)
    table_source_details = _extract_tmdl_table_source_details(model_path)
    dax_measure_deps = analyzer.build_dax_dependency_graph(list(items_by_key.values()))
    dax_column_deps = analyzer.build_dax_column_deps(list(items_by_key.values()))
    dax_table_deps = analyzer.build_dax_table_deps(list(items_by_key.values()))
    relationship_details = analyzer.parse_relationship_details(model_path) if model_path else []
    rls_refs = analyzer.parse_rls_roles(model_path) if model_path else []
    reverse_measure_deps: dict[tuple[str, str], set[tuple[str, str]]] = {}
    reverse_column_deps: dict[tuple[str, str], set[tuple[str, str]]] = {}
    relationship_counts: dict[tuple[str, str], int] = {}
    rls_keys = {analyzer.normalize_key(tbl, col) for _, tbl, col in rls_refs}
    sort_target_keys: set[tuple[str, str]] = set()

    for item in items_by_key.values():
        if item.sort_by_column and item.item_type in ("Column", "Calculated Column"):
            sort_target_keys.add(analyzer.normalize_key(item.table, item.sort_by_column))

    for rel in relationship_details:
        from_key = analyzer.normalize_key(rel.from_table, rel.from_column)
        to_key = analyzer.normalize_key(rel.to_table, rel.to_column)
        relationship_counts[from_key] = relationship_counts.get(from_key, 0) + 1
        relationship_counts[to_key] = relationship_counts.get(to_key, 0) + 1

    for source_key, deps in dax_measure_deps.items():
        for dep_key in deps:
            reverse_measure_deps.setdefault(dep_key, set()).add(source_key)

    for source_key, deps in dax_column_deps.items():
        for dep_key in deps:
            reverse_column_deps.setdefault(dep_key, set()).add(source_key)

    items = []
    for r in results["items"]:
        reports_used = sorted({u.report for u in r["usages"] if u.report})
        pages_used = sorted({u.page for u in r["usages"] if u.page})
        visual_types = sorted({u.visual_type for u in r["usages"] if u.visual_type})
        contexts = sorted({u.context for u in r["usages"] if u.context})
        item = r["item"]
        key = item.key
        status = r["status"]
        dax_expression = (item.dax_body or "").strip() or None
        m_source_details = table_source_details.get(item.table) if item.item_type == "Column" else None
        indirect_via = []
        if status.startswith("INDIRECT (via: ") and status.endswith(")"):
            indirect_via = [part.strip() for part in status[15:-1].split(",") if part.strip()]
        dependent_measure_keys = sorted(
            key_ref for key_ref in
            (reverse_measure_deps.get(key, set()) | reverse_column_deps.get(key, set()))
            if items_by_key.get(key_ref) and items_by_key[key_ref].item_type == "Measure"
        )
        report_used_measure_keys = [
            dep_key for dep_key in dependent_measure_keys
            if rows_by_key.get(dep_key, {}).get("usages")
        ]
        relationship_ref_count = relationship_counts.get(analyzer.normalize_key(*key), 0)
        other_model_uses = []
        if status.startswith("USED (Field Parameter:"):
            other_model_uses.append("Field param")
        if analyzer.normalize_key(*key) in rls_keys:
            other_model_uses.append("RLS")
        if item.is_key:
            other_model_uses.append("Key")
        if analyzer.normalize_key(*key) in sort_target_keys:
            other_model_uses.append("Sort")
        if "Hierarchy" in status:
            other_model_uses.append("Hierarchy")
        report_use_summary = (
            "No"
            if not r["usages"]
            else f"{len(reports_used)} rpt | {len(pages_used)} pg | {len(r['usages'])} refs"
        )

        payload_item = {
            "type": item.item_type,
            "table": item.table,
            "name": item.name,
            "sourceKind": item.source_kind,
            "sourceArtifact": item.source_artifact or None,
            "sourceFile": item.source_file or None,
            "displayFolder": item.display_folder,
            "formatString": item.format_string or None,
            "isHidden": item.is_hidden,
            "isKey": item.is_key,
            "isInferred": item.is_inferred,
            "sortByColumn": item.sort_by_column or None,
            "daxExpression": dax_expression,
            "mSourceDetails": m_source_details,
            "status": status,
            "statusDetail": status,
            "removalRisk": r.get("removal_risk", "") or None,
            "reviewTriggers": r.get("review_triggers", []),
            "brokenDaxRefs": r.get("broken_dax_refs", []),
            "brokenDaxRefDetails": r.get("broken_dax_ref_details", []),
            "reportCount": len(reports_used),
            "pageCount": len(pages_used),
            "pagesUsed": pages_used,
            "visualTypes": visual_types,
            "contexts": contexts,
            "usageCount": len(r["usages"]),
            "reportUseSummary": report_use_summary,
            "measureDependentCount": len(dependent_measure_keys),
            "measureDependentItems": sorted(analyzer.format_item_ref(dep) for dep in dependent_measure_keys),
            "reportUsedMeasureDependentCount": len(report_used_measure_keys),
            "reportUsedMeasureDependentItems": sorted(analyzer.format_item_ref(dep) for dep in report_used_measure_keys),
            "relationshipRefCount": relationship_ref_count,
            "otherModelUses": other_model_uses,
            "otherModelUseCount": len(other_model_uses),
            "indirectVia": indirect_via,
            "dependsOnMeasures": sorted(analyzer.format_item_ref(dep) for dep in dax_measure_deps.get(key, set())),
            "dependsOnColumns": sorted(analyzer.format_item_ref(dep) for dep in dax_column_deps.get(key, set())),
            "dependsOnTables": sorted(dax_table_deps.get(key, set()), key=str.casefold),
            "commentedRefs": sorted(analyzer.extract_dax_commented_refs(item.dax_body or "")),
            "usedByItems": sorted(
                analyzer.format_item_ref(dep) for dep in
                (reverse_measure_deps.get(key, set()) | reverse_column_deps.get(key, set()))
            ),
            "usageDetails": [
                {
                    "report": u.report,
                    "page": u.page,
                    "visualType": u.visual_type,
                    "visualTitle": u.visual_title or "",
                    "visualId": u.visual_id or "",
                    "context": u.context,
                    "sourcePath": u.source_path or "",
                    "artifactKind": u.artifact_kind or "",
                    "artifactPath": u.artifact_path or "",
                    "refType": u.ref_type,
                    "staleKind": u.stale_kind or "",
                }
                for u in r["usages"]
            ],
            "staleUsageCount": len(r.get("stale_usages", [])),
            "staleUsageDetails": [
                {
                    "report": u.report,
                    "page": u.page,
                    "visualType": u.visual_type,
                    "visualTitle": u.visual_title or "",
                    "visualId": u.visual_id or "",
                    "context": u.context,
                    "sourcePath": u.source_path or "",
                    "artifactKind": u.artifact_kind or "",
                    "artifactPath": u.artifact_path or "",
                    "selectorValue": u.selector_value or "",
                    "refType": u.ref_type,
                    "staleKind": u.stale_kind or "",
                }
                for u in r.get("stale_usages", [])
            ],
        }
        payload_item["usageState"] = _usage_state(
            status=status,
            usage_count=payload_item["usageCount"],
            measure_dependent_count=payload_item["measureDependentCount"],
            relationship_ref_count=payload_item["relationshipRefCount"],
            other_model_use_count=payload_item["otherModelUseCount"],
            stale_usage_count=payload_item["staleUsageCount"],
        )
        payload_item["issueState"] = _issue_state(status, payload_item["brokenDaxRefs"], payload_item["staleUsageCount"])
        payload_item["deleteSafety"] = _delete_safety(payload_item)
        items.append(payload_item)

    item_display_state = {
        (payload_item["type"], payload_item["table"], payload_item["name"]): {
            "usageState": payload_item["usageState"],
            "issueState": payload_item["issueState"],
            "deleteSafety": payload_item["deleteSafety"],
        }
        for payload_item in items
    }

    references = []
    for r in results["items"]:
        item = r["item"]
        status = r["status"]
        risk = r.get("removal_risk", "") or None
        display_state = item_display_state.get((item.item_type, item.table, item.name), {})
        if r["usages"]:
            for u in r["usages"]:
                references.append({
                    "type": item.item_type,
                    "table": item.table,
                    "name": item.name,
                    "sourceKind": item.source_kind,
                    "sourceArtifact": item.source_artifact or None,
                    "sourceFile": item.source_file or None,
                    "isHidden": item.is_hidden,
                    "displayFolder": item.display_folder,
                    "formatString": item.format_string or None,
                    "report": u.report,
                    "page": u.page,
                    "visualType": u.visual_type,
                    "visualTitle": u.visual_title or "",
                    "visualId": u.visual_id or "",
                    "context": u.context,
                    "sourcePath": u.source_path or "",
                    "artifactKind": u.artifact_kind or "",
                    "artifactPath": u.artifact_path or "",
                    "selectorValue": u.selector_value or "",
                    "isStale": False,
                    "staleKind": u.stale_kind or "",
                    "status": status,
                    "usageState": display_state.get("usageState", "Unused"),
                    "issueState": display_state.get("issueState", _issue_state(status, r.get("broken_dax_refs", []), len(r.get("stale_usages", [])))),
                    "removalRisk": risk,
                    "deleteSafety": display_state.get("deleteSafety", _delete_safety({
                        "status": status,
                        "isInferred": item.is_inferred,
                        "removalRisk": risk,
                    })),
                    "reviewTriggers": r.get("review_triggers", []),
                    "brokenDaxRefs": r.get("broken_dax_refs", []),
                    "brokenDaxRefDetails": r.get("broken_dax_ref_details", []),
                })
        else:
            references.append({
                "type": item.item_type,
                "table": item.table,
                "name": item.name,
                "sourceKind": item.source_kind,
                "sourceArtifact": item.source_artifact or None,
                "sourceFile": item.source_file or None,
                "isHidden": item.is_hidden,
                "displayFolder": item.display_folder,
                "formatString": item.format_string or None,
                "report": "",
                "page": "",
                "visualType": "",
                "visualTitle": "",
                "visualId": "",
                "context": "",
                "sourcePath": "",
                "artifactKind": "",
                "artifactPath": "",
                "selectorValue": "",
                "isStale": False,
                "staleKind": "",
                "status": status,
                "usageState": display_state.get("usageState", "Unused"),
                "issueState": display_state.get("issueState", _issue_state(status, r.get("broken_dax_refs", []), len(r.get("stale_usages", [])))),
                "removalRisk": risk,
                "deleteSafety": display_state.get("deleteSafety", _delete_safety({
                    "status": status,
                    "isInferred": item.is_inferred,
                    "removalRisk": risk,
                })),
                "reviewTriggers": r.get("review_triggers", []),
                "brokenDaxRefs": r.get("broken_dax_refs", []),
                "brokenDaxRefDetails": r.get("broken_dax_ref_details", []),
            })
        for u in r.get("stale_usages", []):
            references.append({
                "type": item.item_type,
                "table": item.table,
                "name": item.name,
                "sourceKind": item.source_kind,
                "sourceArtifact": item.source_artifact or None,
                "sourceFile": item.source_file or None,
                "isHidden": item.is_hidden,
                "displayFolder": item.display_folder,
                "formatString": item.format_string or None,
                "report": u.report,
                "page": u.page,
                "visualType": u.visual_type,
                "visualTitle": u.visual_title or "",
                "visualId": u.visual_id or "",
                "context": u.context,
                "sourcePath": u.source_path or "",
                "artifactKind": u.artifact_kind or "",
                "artifactPath": u.artifact_path or "",
                "selectorValue": u.selector_value or "",
                "isStale": True,
                "staleKind": u.stale_kind or "",
                "status": status,
                "usageState": display_state.get("usageState", "Unused"),
                "issueState": display_state.get("issueState", _issue_state(status, r.get("broken_dax_refs", []), len(r.get("stale_usages", [])))),
                "removalRisk": risk,
                "deleteSafety": display_state.get("deleteSafety", _delete_safety({
                    "status": status,
                    "isInferred": item.is_inferred,
                    "removalRisk": risk,
                })),
                "reviewTriggers": r.get("review_triggers", []),
                "brokenDaxRefs": r.get("broken_dax_refs", []),
                "brokenDaxRefDetails": r.get("broken_dax_ref_details", []),
            })

    tables = []
    for table in results.get("table_summaries", []):
        table_usage_status = _table_usage_status(table)
        tables.append({
            "name": table["name"],
            "roleLabel": table.get("role_label", ""),
            "roleReason": table.get("role_reason", ""),
            "usageStatus": table_usage_status,
            "usageState": _table_usage_state(table),
            "issueState": _table_issue_state(table),
            "itemCount": table.get("item_count", 0),
            "measureCount": table.get("measure_count", 0),
            "columnCount": table.get("column_count", 0),
            "calculatedColumnCount": table.get("calculated_column_count", 0),
            "directReportMeasureCount": table.get("direct_report_measure_count", 0),
            "directReportColumnCount": table.get("direct_report_column_count", 0),
            "usedItemCount": table.get("used_item_count", 0),
            "unusedItemCount": table.get("unused_item_count", 0),
            "hiddenItemCount": table.get("hidden_item_count", 0),
            "usageRefCount": table.get("usage_ref_count", 0),
            "reportCount": table.get("report_count", 0),
            "reports": table.get("reports", []),
            "pageCount": table.get("page_count", 0),
            "pages": table.get("pages", []),
            "relationshipCount": table.get("relationship_count", 0),
            "activeRelationshipCount": table.get("active_relationship_count", 0),
            "inactiveRelationshipCount": table.get("inactive_relationship_count", 0),
            "oneToManyCount": table.get("one_to_many_count", 0),
            "manyToOneCount": table.get("many_to_one_count", 0),
            "oneToOneCount": table.get("one_to_one_count", 0),
            "manyToManyCount": table.get("many_to_many_count", 0),
            "relatedTables": table.get("related_tables", []),
            "relationshipOnlyColumns": table.get("relationship_only_columns", []),
            "singleColumnMeasures": table.get("single_column_measures", []),
            "externalDaxDependents": table.get("external_dax_dependents", []),
            "relationships": [
                {
                    "name": rel.get("name", ""),
                    "localColumn": rel.get("local_column", ""),
                    "otherTable": rel.get("other_table", ""),
                    "otherColumn": rel.get("other_column", ""),
                    "cardinality": rel.get("cardinality", ""),
                    "isActive": rel.get("is_active", True),
                    "role": rel.get("role", ""),
                }
                for rel in table.get("relationships", [])
            ],
            "signals": table.get("signals", []),
            "fieldParameterIssues": table.get("field_parameter_issues", []),
            "items": [
                {
                    "name": item.get("name", ""),
                    "ref": item.get("ref", ""),
                    "type": item.get("type", ""),
                    "status": item.get("status", ""),
                    "removalRisk": item.get("removal_risk"),
                    "reviewTriggers": item.get("review_triggers", []),
                    "brokenDaxRefs": item.get("broken_dax_refs", []),
                    "brokenDaxRefDetails": item.get("broken_dax_ref_details", []),
                    "usageCount": item.get("usage_count", 0),
                }
                for item in table.get("items", [])
            ],
        })

    report_issues = results.get("report_issues", [])
    return {
        "summary": results["summary"],
        "tables": tables,
        "warnings": results.get("warnings", []),
        "reportIssues": report_issues,
        "reportHealth": _build_report_health(report_issues, items),
        "rootCauseGroups": _build_report_root_cause_groups(report_issues),
        "items": items,
        "references": references,
    }


def _analysis_download_basename(results: dict) -> str:
    models = results.get("summary", {}).get("models", [])
    if not models:
        return "analysis"
    return models[0].replace(".SemanticModel", "")


def _build_stamp() -> str:
    """Create a short build stamp for the UI header."""
    package_version = f"v{__version__}"

    try:
        repo_root = Path(__file__).resolve().parents[2]
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "--exit-code"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode != 0
        state = "dirty" if dirty else "clean"
        return f"{package_version} | commit {commit} | {state}"
    except Exception:
        return f"{package_version} | commit unknown"


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    models, reports = _discover_initial_artifacts()
    selected_models = _default_model_selection(models)
    selected_reports = reports
    return render_template(
        "index.html",
        build_stamp=_build_stamp(),
        default_root=_state.get("workspace") or str(_default_workspace_root()),
        runtime=_state.get("runtime") or experiments.runtime_config(),
        initial_models=[{"path": str(m), "name": m.name.replace(".SemanticModel", "")} for m in selected_models],
        initial_reports=[{"path": str(r), "name": analyzer.report_display_name(r)} for r in selected_reports],
    )


@app.route("/api/browse", methods=["GET"])
def api_browse():
    """Browse filesystem directories to pick model/report folders.

    Query params:
      path — directory to list (default: workspace root or home)
    Returns sorted list of entries: { name, path, type }
    type is one of: "dir", "model", "report"
    """
    try:
        raw = _normalize_browse_path(request.args.get("path", ""))
        if not raw:
            raw = _state["workspace"] or str(Path.home())
        target = Path(raw).resolve()

        if not target.is_dir():
            return jsonify({"error": f"Not a directory: {target}"}), 400

        entries = []
        try:
            children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return jsonify({"error": f"Permission denied: {target}"}), 403

        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name.endswith(".SemanticModel"):
                    entry_type = "model"
                elif child.name.endswith(".Report"):
                    entry_type = "report"
                else:
                    entry_type = "dir"
                entries.append({"name": child.name, "path": str(child), "type": entry_type})

        parent = str(target.parent) if target != target.parent else None
        return jsonify({"current": str(target), "parent": parent, "entries": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discover", methods=["GET", "POST"])
def api_discover():
    """Discover available models and reports.

    POST body (optional): { "model_roots": [...], "report_roots": [...] }
    Paths can be direct .SemanticModel/.Report dirs, parent folders, or
    a single folder containing both.
    """
    try:
        body = request.get_json(silent=True) or {} if request.method == "POST" else {}

        # Custom roots from POST override CLI defaults
        model_roots = body.get("model_roots") or _effective_model_roots()
        report_roots = body.get("report_roots") or _effective_report_roots()

        models = analyzer.discover_models([Path(r) for r in model_roots])
        reports = analyzer.discover_reports([Path(r) for r in report_roots])

        _state["model_paths"] = [str(m) for m in models]
        _state["report_paths"] = [str(r) for r in reports]

        return jsonify({
            "models": [{"path": str(m), "name": m.name.replace(".SemanticModel", "")} for m in models],
            "reports": [{"path": str(r), "name": analyzer.report_display_name(r)} for r in reports],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports/find-connected", methods=["POST"])
def api_find_connected_reports():
    """Find PBIR reports whose definition.pbir references the selected local Semantic Model."""
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        search_root_str = _normalize_browse_path(str(data.get("search_root", "") or ""))

        if not model_path_str:
            return jsonify({"error": "No model path specified"}), 400
        model_path = Path(model_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400
        if not search_root_str:
            return jsonify({"error": "No search folder specified"}), 400
        search_root = Path(search_root_str).resolve()
        if not search_root.is_dir():
            return jsonify({"error": f"Search folder not found: {search_root}"}), 400

        model_path = model_path.resolve()
        model_name = model_path.name.replace(".SemanticModel", "")
        model_display_name = _platform_display_name(model_path)
        # Live report connections refer to the published (display) name; the folder
        # name is only a fallback for workspaces without a .platform file.
        model_name_candidates = {
            candidate.casefold()
            for candidate in (model_display_name, model_name)
            if candidate
        }
        selected_model_label = model_display_name or model_name
        reports_by_path: dict[Path, dict] = {}
        report_statuses = []
        scanned_files = 0
        warnings = []

        for report_root in analyzer.discover_reports([search_root]):
            report_root = report_root.resolve()
            definition_file = report_root / "definition.pbir"
            status = {
                "path": str(report_root),
                "name": analyzer.report_display_name(report_root),
                "definitionFile": str(definition_file.resolve()),
                "status": "not_connected",
                "message": "definition.pbir references a different local Semantic Model.",
            }
            if not definition_file.is_file():
                status["status"] = "missing_definition"
                status["message"] = "Missing definition.pbir."
                report_statuses.append(status)
                warnings.append(f"{report_root.name}: {status['message']}")
                continue

            scanned_files += 1
            try:
                definition = json.loads(definition_file.read_text(encoding="utf-8"))
            except OSError as exc:
                warnings.append(f"Skipped {definition_file}: {exc}")
                continue
            except json.JSONDecodeError as exc:
                status["status"] = "invalid_definition"
                status["message"] = f"Invalid definition.pbir JSON: {exc.msg}"
                report_statuses.append(status)
                warnings.append(f"{report_root.name}: {status['message']}")
                continue
            if not isinstance(definition, dict):
                status["status"] = "invalid_definition"
                status["message"] = "Invalid definition.pbir JSON: expected a JSON object."
                report_statuses.append(status)
                warnings.append(f"{report_root.name}: {status['message']}")
                continue

            dataset_reference = definition.get("datasetReference", {})
            if isinstance(dataset_reference, dict) and "byConnection" in dataset_reference:
                connection = dataset_reference.get("byConnection")
                published_name = ""
                if isinstance(connection, dict):
                    connection_string = connection.get("connectionString")
                    if isinstance(connection_string, str):
                        catalog_match = re.search(
                            r"initial catalog\s*=\s*([^;]+)", connection_string, re.IGNORECASE
                        )
                        if catalog_match:
                            published_name = catalog_match.group(1).strip()
                if published_name:
                    status["publishedModelName"] = published_name
                if published_name and published_name.casefold() in model_name_candidates:
                    status["status"] = "connected_by_name"
                    status["message"] = (
                        f"Live connection to a published semantic model named '{published_name}', "
                        "which matches the selected Semantic Model. Matched by name, not by folder path."
                    )
                    report_statuses.append(status)
                    reports_by_path.setdefault(report_root, {
                        "path": str(report_root),
                        "name": analyzer.report_display_name(report_root),
                        "status": "connected_by_name",
                        "definitionFiles": [],
                    })
                    reports_by_path[report_root]["definitionFiles"].append(str(definition_file.resolve()))
                    continue
                status["status"] = "remote"
                if published_name:
                    status["message"] = (
                        f"Live connection to a published semantic model named '{published_name}', "
                        f"which does not match the selected model '{selected_model_label}'."
                    )
                else:
                    status["message"] = (
                        "Live connection to a published semantic model in the Power BI service; "
                        "no model name could be read from the connection string."
                    )
                report_statuses.append(status)
                warnings.append(f"{report_root.name}: {status['message']}")
                continue

            by_path = dataset_reference.get("byPath", {}) if isinstance(dataset_reference, dict) else {}
            referenced_path = by_path.get("path") if isinstance(by_path, dict) else None
            if not isinstance(referenced_path, str) or not referenced_path.strip():
                status["status"] = "missing_dataset_reference"
                status["message"] = "definition.pbir does not include datasetReference.byPath.path."
                report_statuses.append(status)
                warnings.append(f"{report_root.name}: {status['message']}")
                continue
            resolved_reference = (definition_file.parent / referenced_path).resolve()
            status["resolvedModelPath"] = str(resolved_reference)
            if not _paths_match(resolved_reference, model_path):
                report_statuses.append(status)
                continue

            status["status"] = "connected"
            status["message"] = "definition.pbir references the selected local Semantic Model."
            report_statuses.append(status)
            reports_by_path.setdefault(report_root, {
                "path": str(report_root),
                "name": analyzer.report_display_name(report_root),
                "status": "connected",
                "definitionFiles": [],
            })
            reports_by_path[report_root]["definitionFiles"].append(str(definition_file.resolve()))

        reports = sorted(reports_by_path.values(), key=lambda item: item["name"].casefold())
        return jsonify({
            "model_name": model_name,
            "model_display_name": model_display_name,
            "search_root": str(search_root),
            "scanned_definition_files": scanned_files,
            "reports": reports,
            "reportStatuses": sorted(report_statuses, key=lambda item: item["name"].casefold()),
            "warnings": warnings,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/demo", methods=["POST"])
def api_demo():
    """Load the bundled demo workspace.

    Copies the packaged demo workspace to a writable location under the user
    data directory so cleanup actions never touch installed package files.
    Loading again resets the copy to its original state.
    """
    try:
        source = _bundled_demo_workspace_root()
        if not source.is_dir():
            return jsonify({"error": "The bundled demo workspace is missing from this installation."}), 500

        target = _user_data_dir() / "demo-workspace"
        reset = target.exists()
        if reset:
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)

        _state["workspace"] = str(target)
        _state["model_search_roots"] = [str(target)]
        _state["report_search_roots"] = [str(target)]

        models = analyzer.discover_models([target])
        reports = analyzer.discover_reports([target])
        _state["model_paths"] = [str(m) for m in models]
        _state["report_paths"] = [str(r) for r in reports]

        return jsonify({
            "workspace": str(target),
            "reset": reset,
            "models": [{"path": str(m), "name": m.name.replace(".SemanticModel", "")} for m in models],
            "reports": [{"path": str(r), "name": analyzer.report_display_name(r)} for r in reports],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Run analysis and return JSON results."""
    try:
        data = request.get_json(silent=True) or {}
        model_paths = data.get("model_paths", _state["model_paths"])
        report_paths = data.get("report_paths", _state["report_paths"])

        if not model_paths or not report_paths:
            return jsonify({"error": "No model or reports selected. Run discover first."}), 400
        if len(model_paths) != 1:
            return jsonify({
                "error": "Select exactly one semantic model and one or more reports before analyzing.",
            }), 400
        missing = [p for p in [*model_paths, *report_paths] if not Path(p).is_dir()]
        if missing:
            return jsonify({
                "error": "These folders were not found: "
                + ", ".join(str(p) for p in missing)
                + ". Check that the paths still exist and try again.",
            }), 400
        _state["model_paths"] = model_paths
        _state["report_paths"] = report_paths

        results = analyzer.analyze(
            workspace=Path(_state["workspace"]) if _state["workspace"] else Path("."),
            model_paths=[Path(p) for p in model_paths],
            report_paths=[Path(p) for p in report_paths],
        )

        _state["last_results"] = results
        return jsonify(_serialize_results(results))
    except analyzer.UnsupportedSemanticModelError as e:
        return jsonify({"error": str(e)}), 400
    except SystemExit:
        return jsonify({"error": "Analysis failed — no models or reports found at the given paths."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/compare", methods=["POST"])
def api_compare():
    """Run a model-to-model TMDL comparison and return JSON results."""
    try:
        data = request.get_json(silent=True) or {}
        baseline_path_str = (
            data.get("baseline_model_path")
            or data.get("baselineModelPath")
            or data.get("baseline_path")
        )
        candidate_path_str = (
            data.get("candidate_model_path")
            or data.get("candidateModelPath")
            or data.get("candidate_path")
        )

        if not baseline_path_str or not candidate_path_str:
            return jsonify({"error": "Baseline and candidate model paths are required."}), 400

        results = model_compare.compare_models(
            Path(_normalize_browse_path(str(baseline_path_str))),
            Path(_normalize_browse_path(str(candidate_path_str))),
        )
        _state["last_compare_results"] = results
        return jsonify(results)
    except model_compare.UnsupportedCompareModelError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _compare_download_basename(results: dict) -> str:
    baseline = str(results.get("baselineModel", {}).get("name", "Baseline") or "Baseline")
    candidate = str(results.get("candidateModel", {}).get("name", "Candidate") or "Candidate")

    def clean(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return cleaned or "Model"

    return f"{clean(baseline)}_vs_{clean(candidate)}_model_compare"


@app.route("/api/compare/export", methods=["GET"])
def api_compare_export():
    """Download the latest model compare results for review."""
    try:
        results = _state.get("last_compare_results")
        if not results:
            return jsonify({"error": "No compare results available. Run compare first."}), 400

        export_format = request.args.get("format", "").strip().lower()
        base_name = _compare_download_basename(results)

        if export_format == "json":
            payload = json.dumps(results, indent=2).encode("utf-8")
            return send_file(
                io.BytesIO(payload),
                mimetype="application/json",
                as_attachment=True,
                download_name=f"{base_name}.json",
            )

        if export_format in {"md", "markdown"}:
            payload = model_compare.format_markdown_output(results).encode("utf-8")
            return send_file(
                io.BytesIO(payload),
                mimetype="text/markdown",
                as_attachment=True,
                download_name=f"{base_name}.md",
            )

        if export_format == "csv":
            payload = model_compare.format_csv_output(results).encode("utf-8")
            return send_file(
                io.BytesIO(payload),
                mimetype="text/csv",
                as_attachment=True,
                download_name=f"{base_name}.csv",
            )

        return jsonify({"error": f"Unsupported compare export format: {export_format or '(empty)'}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export", methods=["GET"])
def api_export():
    """Download the latest analysis as JSON or XLSX."""
    try:
        results = _state.get("last_results")
        if not results:
            return jsonify({"error": "No analysis results available. Run analysis first."}), 400

        export_format = request.args.get("format", "").strip().lower()
        base_name = _analysis_download_basename(results)

        if export_format == "json":
            payload = analyzer.format_json_output(results).encode("utf-8")
            return send_file(
                io.BytesIO(payload),
                mimetype="application/json",
                as_attachment=True,
                download_name=f"{base_name}_usage_analysis.json",
            )

        if export_format == "xlsx":
            payload = analyzer.create_xlsx_bytes(results)
            return send_file(
                io.BytesIO(payload),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=f"{base_name}_usage_analysis.xlsx",
            )

        return jsonify({"error": f"Unsupported export format: {export_format or '(empty)'}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/action", methods=["POST"])
def api_action():
    """Apply actions (move_to_folder, move_to_table_group, hide, unhide, delete)."""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        actions = data.get("actions", [])
        if not actions:
            return jsonify({"error": "No actions specified"}), 400

        model_path, error = _cleanup_action_model_path(data)
        if error:
            payload, status = error
            return jsonify(payload), status

        create_backup = bool(data.get("create_backup", False))
        plan = _cleanup_action_plan_response(
            model_path,
            actions,
            create_backup=create_backup,
            auto_refresh=data.get("auto_refresh"),
        )
        git_warning = tmdl_writer.check_git_dirty(model_path)
        if not plan["ok"]:
            results = _cleanup_action_invalid_results(plan)
            return jsonify({
                "ok": False,
                "results": results,
                "errors": [result.get("error") for result in results if result.get("error")],
                "plan": plan,
                "backup_path": None,
                "git_warning": git_warning,
            })

        backup_path = None
        if create_backup:
            backup_path = str(tmdl_writer.create_backup(model_path))
            _state["backup_path"] = backup_path

        results = tmdl_writer.apply_actions(model_path, actions)
        ok = all(result.get("ok") for result in results)

        return jsonify({
            "ok": ok,
            "results": results,
            "errors": [result.get("error") for result in results if result.get("error")],
            "plan": plan,
            "backup_path": backup_path,
            "git_warning": git_warning,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/action/preview", methods=["POST"])
def api_action_preview():
    """Preview queued cleanup actions without writing TMDL files."""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        actions = data.get("actions", [])
        if not actions:
            return jsonify({"error": "No actions specified"}), 400

        model_path, error = _cleanup_action_model_path(data)
        if error:
            payload, status = error
            return jsonify(payload), status

        plan = _cleanup_action_plan_response(
            model_path,
            actions,
            create_backup=bool(data.get("create_backup", False)),
            auto_refresh=data.get("auto_refresh"),
        )
        return jsonify({
            "ok": plan["ok"],
            "plan": plan,
            "errors": plan["errors"],
            "git_warning": tmdl_writer.check_git_dirty(model_path),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dax", methods=["POST"])
def api_dax():
    """Update DAX for a measure or calculated column."""
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        table = (data.get("table") or "").strip()
        name = (data.get("name") or "").strip()
        item_type = (data.get("item_type") or "").strip()
        dax_expression = data.get("dax_expression")

        if not model_path_str:
            return jsonify({"error": "No model path specified"}), 400
        if not table or not name or not item_type:
            return jsonify({"error": "Missing required fields: table, name, item_type"}), 400
        if item_type not in ("Measure", "Calculated Column"):
            return jsonify({"error": "DAX editing is only supported for Measure and Calculated Column"}), 400
        if dax_expression is None:
            return jsonify({"error": "Missing required field: dax_expression"}), 400

        model_path = Path(model_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400

        if data.get("create_backup", False):
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))

        git_warning = tmdl_writer.check_git_dirty(model_path)
        result = tmdl_writer.set_dax_expression(
            model_path=model_path,
            table=table,
            name=name,
            item_type=item_type,
            dax_expression=str(dax_expression),
            source_file=data.get("source_file") or data.get("sourceFile"),
        )

        if not result.get("ok"):
            return jsonify(result), 400

        return jsonify({
            "result": result,
            "backup_path": _state["backup_path"],
            "git_warning": git_warning,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report-measure/migrate", methods=["POST"])
def api_migrate_report_measure():
    """Promote a report-level measure into the semantic model."""
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        report_path_str = data.get("report_path") or (_state["report_paths"][0] if _state["report_paths"] else None)
        table = (data.get("table") or "").strip()
        name = (data.get("name") or "").strip()
        target_table = (data.get("target_table") or "").strip() or None
        target_name = (data.get("target_name") or "").strip() or None

        if not model_path_str or not report_path_str:
            return jsonify({"error": "Model path and report path are required"}), 400
        if not table or not name:
            return jsonify({"error": "Missing required fields: table, name"}), 400

        model_path = Path(model_path_str)
        report_path = Path(report_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400
        if not report_path.exists():
            return jsonify({"error": f"Report path not found: {report_path}"}), 400

        backup_paths = {}
        if data.get("create_backup", False):
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))
            backup_paths["model"] = _state["backup_path"]
            backup_paths["report"] = str(report_writer.create_backup(report_path))

        git_warning = tmdl_writer.check_git_dirty(model_path)
        transaction_roots = _cleanup_transaction_roots(model_path, [report_path])
        snapshot = file_transaction.snapshot_artifact_files(transaction_roots)
        try:
            result = report_writer.migrate_measure_to_model(
                model_path=model_path,
                report_path=report_path,
                entity_name=table,
                measure_name=name,
                target_table=target_table,
                target_name=target_name,
            )
        except Exception as exc:
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            return jsonify({
                "ok": False,
                "error": str(exc),
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }), 400
        if not result.get("ok"):
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            result = {
                **result,
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }
            return jsonify(result), 400

        return jsonify({
            "result": result,
            "backup_path": _state["backup_path"],
            "backup_paths": backup_paths or None,
            "git_warning": git_warning,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/measure/move", methods=["POST"])
def api_move_measure_to_table():
    """Move model measures to another table and rewrite selected PBIR reports."""
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        moves = data.get("moves") or []
        report_path_values = data.get("report_paths") or _state["report_paths"]
        dry_run = bool(data.get("dry_run", False))

        if not model_path_str:
            return jsonify({"error": "No model path specified"}), 400
        if not moves:
            return jsonify({"error": "No measure moves specified"}), 400
        if not report_path_values:
            return jsonify({"error": "No selected reports provided"}), 400

        model_path = Path(model_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400

        report_paths = [Path(str(value)) for value in report_path_values]
        for report_path in report_paths:
            if not report_path.exists():
                return jsonify({"error": f"Report path not found: {report_path}"}), 400

        model_preview = tmdl_writer.move_measures_to_tables(model_path, moves, dry_run=True)
        if not model_preview.get("ok"):
            return jsonify(model_preview), 400

        report_preview = report_writer.rewrite_measure_table_references(
            report_paths=report_paths,
            moves=moves,
            dry_run=True,
        )
        if not report_preview.get("ok"):
            return jsonify(report_preview), 400

        git_warning = tmdl_writer.check_git_dirty(model_path)
        if dry_run:
            return jsonify({
                "ok": True,
                "dry_run": True,
                "model_result": model_preview,
                "report_result": report_preview,
                "selected_report_count": len(report_paths),
                "git_warning": git_warning,
            })

        backup_paths = {"model": None, "reports": []}
        if data.get("create_backup", False):
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))
            backup_paths["model"] = _state["backup_path"]
            for report_path in report_paths:
                backup_paths["reports"].append(str(report_writer.create_backup(report_path)))

        transaction_roots = _cleanup_transaction_roots(model_path, report_paths)
        snapshot = file_transaction.snapshot_artifact_files(transaction_roots)
        model_result = tmdl_writer.move_measures_to_tables(model_path, moves, dry_run=False)
        if not model_result.get("ok"):
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            model_result = {
                **model_result,
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }
            return jsonify(model_result), 400

        report_result = report_writer.rewrite_measure_table_references(
            report_paths=report_paths,
            moves=moves,
            dry_run=False,
        )
        if not report_result.get("ok"):
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            return jsonify({
                "ok": False,
                "error": report_result.get("error") or "Report rewrite failed",
                "model_result": model_result,
                "report_result": report_result,
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }), 400

        return jsonify({
            "ok": True,
            "dry_run": False,
            "model_result": model_result,
            "report_result": report_result,
            "backup_path": _state["backup_path"],
            "backup_paths": backup_paths,
            "selected_report_count": len(report_paths),
            "git_warning": git_warning,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/model/rename", methods=["POST"])
def api_rename_model_metadata():
    """Rename semantic-model tables/measures and rewrite selected PBIR reports."""
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        table_renames = data.get("table_renames") or []
        measure_renames = data.get("measure_renames") or []
        report_path_values = data.get("report_paths") or _state["report_paths"]
        dry_run = bool(data.get("dry_run", False))

        if not model_path_str:
            return jsonify({"error": "No model path specified"}), 400
        if not table_renames and not measure_renames:
            return jsonify({"error": "No table or measure renames specified"}), 400
        if not report_path_values:
            return jsonify({"error": "No selected reports provided"}), 400

        model_path = Path(model_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400

        report_paths = [Path(str(value)) for value in report_path_values]
        for report_path in report_paths:
            if not report_path.exists():
                return jsonify({"error": f"Report path not found: {report_path}"}), 400

        model_preview = tmdl_writer.rename_model_metadata(
            model_path,
            table_renames=table_renames,
            measure_renames=measure_renames,
            dry_run=True,
        )
        if not model_preview.get("ok"):
            return jsonify(model_preview), 400

        report_preview = report_writer.rewrite_model_reference_changes(
            report_paths=report_paths,
            table_renames=table_renames,
            measure_renames=measure_renames,
            dry_run=True,
        )
        if not report_preview.get("ok"):
            return jsonify(report_preview), 400

        git_warning = tmdl_writer.check_git_dirty(model_path)
        if dry_run:
            return jsonify({
                "ok": True,
                "dry_run": True,
                "model_result": model_preview,
                "report_result": report_preview,
                "selected_report_count": len(report_paths),
                "git_warning": git_warning,
            })

        backup_paths = {"model": None, "reports": []}
        if data.get("create_backup", False):
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))
            backup_paths["model"] = _state["backup_path"]
            for report_path in report_paths:
                backup_paths["reports"].append(str(report_writer.create_backup(report_path)))

        transaction_roots = _cleanup_transaction_roots(model_path, report_paths)
        snapshot = file_transaction.snapshot_artifact_files(transaction_roots)
        model_result = tmdl_writer.rename_model_metadata(
            model_path,
            table_renames=table_renames,
            measure_renames=measure_renames,
            dry_run=False,
        )
        if not model_result.get("ok"):
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            model_result = {
                **model_result,
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }
            return jsonify(model_result), 400

        report_result = report_writer.rewrite_model_reference_changes(
            report_paths=report_paths,
            table_renames=table_renames,
            measure_renames=measure_renames,
            dry_run=False,
        )
        if not report_result.get("ok"):
            rollback = _restore_cleanup_transaction(transaction_roots, snapshot)
            return jsonify({
                "ok": False,
                "error": report_result.get("error") or "Report rewrite failed",
                "model_result": model_result,
                "report_result": report_result,
                "rolled_back": rollback["ok"],
                "rollback": rollback,
            }), 400

        return jsonify({
            "ok": True,
            "dry_run": False,
            "model_result": model_result,
            "report_result": report_result,
            "backup_path": _state["backup_path"],
            "backup_paths": backup_paths,
            "selected_report_count": len(report_paths),
            "git_warning": git_warning,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/cleanup-stale", methods=["POST"])
def api_cleanup_stale_report_metadata():
    """Remove stale formatting selectors from selected PBIR report files."""
    try:
        data = request.get_json(silent=True) or {}
        entries = data.get("entries", [])
        dry_run = bool(data.get("dry_run") or data.get("dryRun"))
        if not entries:
            return jsonify({"error": "No stale selector entries provided"}), 400

        backup_paths = []
        if data.get("create_backup", False) and not dry_run:
            for report_path_str in sorted({str(entry.get("report_path", "") or "").strip() for entry in entries if entry.get("report_path")}):
                report_path = Path(report_path_str)
                if not report_path.exists():
                    return jsonify({"error": f"Report path not found: {report_path}"}), 400
                backup_paths.append(str(report_writer.create_backup(report_path)))

        result = report_writer.cleanup_stale_metadata_selectors(entries=entries, dry_run=dry_run)
        if not result.get("ok"):
            return jsonify(result), 400

        return jsonify({
            "result": result,
            "removed_count": result.get("removed_count", 0),
            "backup_paths": backup_paths or None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/issues/apply", methods=["POST"])
def api_apply_report_issue_actions():
    """Apply exact report-health row actions to PBIR report files."""
    try:
        data = request.get_json(silent=True) or {}
        entries = data.get("entries", [])
        dry_run = bool(data.get("dry_run") or data.get("dryRun"))
        if not entries:
            return jsonify({"error": "No report issue actions provided"}), 400

        backup_paths = []
        if data.get("create_backup", False) and not dry_run:
            for report_path_str in sorted({str(entry.get("report_path", "") or "").strip() for entry in entries if entry.get("report_path")}):
                report_path = Path(report_path_str)
                if not report_path.exists():
                    return jsonify({"error": f"Report path not found: {report_path}"}), 400
                backup_paths.append(str(report_writer.create_backup(report_path)))

        result = report_writer.apply_report_issue_actions(entries=entries, dry_run=dry_run)
        if not result.get("ok"):
            return jsonify(result), 400

        return jsonify({
            "result": result,
            "dry_run": dry_run,
            "updated_reference_count": result.get("updated_reference_count", 0),
            "updated_file_count": result.get("updated_file_count", 0),
            "backup_paths": backup_paths or None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/repair-references", methods=["POST"])
def api_repair_report_references():
    """Repair report references that point at a renamed semantic-model table.

    Report-only: this rewrites the selected PBIR reports to point at the
    user-chosen replacement table and NEVER renames the model (the model is
    already correct in the rename-fallout case). It routes through the
    transactional rewrite engine (snapshot + validate + rollback) and supports
    dry_run so the UI can preview the true reference count before writing.
    """
    try:
        data = request.get_json(silent=True) or {}
        table_renames = data.get("table_renames") or []
        column_renames = data.get("column_renames") or []
        report_path_values = data.get("report_paths") or _state["report_paths"]
        dry_run = bool(data.get("dry_run") or data.get("dryRun"))

        for label, renames in (("table_renames", table_renames), ("column_renames", column_renames)):
            if not isinstance(renames, list) or any(not isinstance(entry, dict) for entry in renames):
                return jsonify({"error": f"{label} must be a list of objects"}), 400

        clean_table_renames = []
        for rename in table_renames:
            table = str((rename or {}).get("table", "") or "").strip()
            target = str((rename or {}).get("target_table", "") or "").strip()
            if not table or not target:
                return jsonify({"error": "Each table rename needs a non-empty table and target_table"}), 400
            clean_table_renames.append({"table": table, "target_table": target})

        clean_column_renames = []
        for rename in column_renames:
            table = str((rename or {}).get("table", "") or "").strip()
            name = str((rename or {}).get("name", "") or "").strip()
            target_name = str((rename or {}).get("target_name", "") or "").strip()
            if not table or not name or not target_name:
                return jsonify({"error": "Each column rename needs a non-empty table, name and target_name"}), 400
            entry = {"table": table, "name": name, "target_name": target_name}
            target_table = str((rename or {}).get("target_table", "") or "").strip()
            if target_table:
                entry["target_table"] = target_table
            clean_column_renames.append(entry)

        if not clean_table_renames and not clean_column_renames:
            return jsonify({"error": "No table or column renames provided"}), 400
        if not report_path_values:
            return jsonify({"error": "No selected reports provided"}), 400

        report_paths = [Path(str(value)) for value in report_path_values]
        for report_path in report_paths:
            if not report_path.exists():
                return jsonify({"error": f"Report path not found: {report_path}"}), 400

        backup_paths = []
        if data.get("create_backup", False) and not dry_run:
            for report_path in report_paths:
                backup_paths.append(str(report_writer.create_backup(report_path)))

        result = report_writer.rewrite_model_reference_changes(
            report_paths=report_paths,
            table_renames=clean_table_renames or None,
            column_renames=clean_column_renames or None,
            dry_run=dry_run,
        )
        if not result.get("ok"):
            return jsonify(result), 400

        # Keep the response bounded: totals + a small sample of files, dropping
        # the verbose per-reference update lists.
        sample_files = [
            {
                "file": entry.get("file"),
                "report": entry.get("report"),
                "referenceCount": entry.get("reference_count", 0),
            }
            for entry in (result.get("updated_files") or [])[:_REPORT_HEALTH_PREVIEW_LIMIT]
        ]
        warnings = result.get("warnings", []) or []
        return jsonify({
            "ok": True,
            "dry_run": dry_run,
            "updated_reference_count": result.get("updated_reference_count", 0),
            "updated_file_count": result.get("updated_file_count", 0),
            "sample_files": sample_files,
            "warnings": warnings[:_REPORT_HEALTH_PREVIEW_LIMIT],
            "warning_count": len(warnings),
            "backup_paths": backup_paths or None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backup", methods=["GET"])
def api_backup_info():
    """Get current backup info."""
    return jsonify({
        "backup_path": _state["backup_path"],
    })


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Semantic Model Cleaner Web App (one semantic model, one or more reports)"
    )
    parser.add_argument("workspace", nargs="?", default=".",
                        help="Workspace root (default: current directory)")
    parser.add_argument("--models-path", nargs="+",
                        help="Path(s) to search for the single .SemanticModel directory to analyze")
    parser.add_argument("--reports-path", nargs="+",
                        help="Path(s) to search for .Report directories")
    parser.add_argument("--port", type=int, default=5001,
                        help="Port to run on (default: 5001)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable Flask debug mode and auto-reload")
    parser.add_argument(
        "--experimental",
        action="append",
        default=[],
        help="Enable an experimental feature key such as compare-models",
    )

    args = parser.parse_args()

    _state["runtime"] = experiments.runtime_config(extra_experiments=args.experimental)
    configure_runtime(
        workspace=args.workspace,
        models_path=args.models_path,
        reports_path=args.reports_path,
    )
    print_startup_banner(args.host, args.port, debug=args.debug)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
