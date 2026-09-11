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
import gzip
import hashlib
from functools import wraps
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import __version__, analyzer, experiments, file_transaction, model_compare, report_writer, tmdl_writer
from . import change_plan, cleanup_policy
from .analysis_jobs import AnalysisJobs

app = Flask(__name__)
_analysis_jobs = AnalysisJobs()

def _invalidates_analysis(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        with _analysis_jobs.invalidate():
            _state["last_results"] = None
            return fn(*args, **kwargs)
    return guarded


def _analysis_source_fingerprint(roots, progress=None):
    """Hash local metadata only; never read report binary assets or data caches."""
    digest = hashlib.sha256()
    for root in sorted(set(roots)):
        base = Path(root)
        if not base.is_dir():
            raise ValueError("Analysis source disappeared. Analyze the current selection again.")
        for path in sorted(base.rglob('*')):
            if path.is_file() and (path.name == '.platform'
                                   or path.suffix.lower() in {'.json', '.tmdl', '.bim', '.pbir', '.pbip'}):
                if progress:
                    progress('Checking source metadata')
                digest.update(str(path).encode('utf-8'))
                digest.update(b'\0')
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                digest.update(b'\0')
    return digest.digest()


@app.after_request
def compress_browser_json(response):
    # The browser negotiates compression; CLI/test clients keep plain JSON.
    if (response.mimetype == 'application/json' and not response.direct_passthrough
            and 'Content-Encoding' not in response.headers):
        response.vary.add('Accept-Encoding')
        if request.accept_encodings['gzip'] > 0:
            content = response.get_data()
            if len(content) >= 4096:
                packed = gzip.compress(content, compresslevel=3, mtime=0)
                if len(packed) < len(content):
                    response.set_data(packed)
                    response.headers['Content-Encoding'] = 'gzip'
    return response


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
    policy = cleanup_policy.evaluate_deletion_policy(
        model_path, [Path(p) for p in _state.get("report_paths", [])], actions)
    plan["policy"] = policy
    if not policy["ok"]:
        plan["ok"] = False
        plan["errors"] = list(plan.get("errors", [])) + policy["errors"]
        for entry in plan.get("actions", []):
            if entry.get("action") in ("delete", "delete_table"):
                entry["ok"] = False
                entry["error"] = "; ".join(policy["errors"])
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


def _report_binding_scope(model_path, report_paths) -> dict:
    """Use the same binding evidence for initial selection and every web analysis."""
    scope = {"selected": [], "excluded": []}
    names = analyzer.model_name_candidates(Path(model_path))
    label = analyzer.model_label(Path(model_path))
    seen = set()
    for report in report_paths:
        path = str(Path(report).resolve())
        if path in seen:
            continue
        seen.add(path)
        binding = analyzer.report_binding_status(Path(path), Path(model_path), names=names, label=label)
        binding.pop("scanned", None)
        binding.pop("warning", None)
        group = "selected" if binding["status"] in analyzer.BOUND_REPORT_STATUSES else "excluded"
        scope[group].append(binding)
    return scope


def _record_report_scope(results, scope):
    results["report_binding"] = scope
    results.setdefault("warnings", []).extend({
        "code": "REPORT_SCOPE_EXCLUDED", "severity": "warning",
        "message": f"Excluded {row['name']} from analysis: {row['message']}",
        "artifactPath": row["definitionFile"],
    } for row in scope["excluded"])


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
                "Item-level stale references overlap report issues above and are not added to the total. "
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
            description="Separate model signal, not part of the report issue total. Unresolved DAX references block confident cleanup until the broken model dependency is resolved.",
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
        "totalIssueCount": len(report_issues),
        "signalCounts": {"staleReferences": stale_count, "brokenModelReferences": broken_count,
                         "unsupportedMetadata": unsupported_count},
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
                "reportPath": issue.get("reportPath", ""),
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


def _serialize_results(results: dict, model_paths=None) -> dict:
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

    items_by_key = {analyzer.item_identity(r["item"]): r["item"] for r in results["items"]}
    rows_by_key = {analyzer.item_identity(r["item"]): r for r in results["items"]}
    model_name = results.get("summary", {}).get("models", [""])[0]
    model_path = next((Path(p) for p in (model_paths if model_paths is not None else _state.get("model_paths", [])) if Path(p).name == model_name), None)
    table_source_details = _extract_tmdl_table_source_details(model_path)
    graphs = results.get("dependency_graphs") or analyzer.scoped_dependency_graphs(list(items_by_key.values()))
    dax_measure_deps, dax_column_deps, dax_table_deps = (graphs[name] for name in ("measures", "columns", "tables"))

    def identity_payload(identity):
        target = items_by_key[identity]
        return {"type": target.item_type, "table": target.table, "name": target.name,
                "sourceKind": target.source_kind, "sourceFile": target.source_file or None}

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
        report_paths_used = sorted({u.report_path or u.report for u in r["usages"] if u.report_path or u.report})
        pages_used = sorted({u.page for u in r["usages"] if u.page})
        visual_types = sorted({u.visual_type for u in r["usages"] if u.visual_type})
        contexts = sorted({u.context for u in r["usages"] if u.context})
        item = r["item"]
        key = analyzer.item_identity(item)
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
        relationship_ref_count = relationship_counts.get(analyzer.normalize_key(*item.key), 0)
        other_model_uses = []
        if status.startswith("USED (Field Parameter:"):
            other_model_uses.append("Field param")
        if analyzer.normalize_key(*item.key) in rls_keys:
            other_model_uses.append("RLS")
        if item.is_key:
            other_model_uses.append("Key")
        if analyzer.normalize_key(*item.key) in sort_target_keys:
            other_model_uses.append("Sort")
        if "Hierarchy" in status:
            other_model_uses.append("Hierarchy")
        report_use_summary = (
            "No"
            if not r["usages"]
            else f"{len(report_paths_used)} rpt | {len(pages_used)} pg | {len(r['usages'])} refs"
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
            "dataType": getattr(item, "data_type", "") or None,
            "sourceColumn": getattr(item, "source_column", "") or None,
            "description": getattr(item, "description", "") or None,
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
            "reportCount": len(report_paths_used),
            "reportPaths": report_paths_used,
            "pageCount": len({(u.report_path or u.report, u.page) for u in r["usages"] if u.page}),
            "pagesUsed": pages_used,
            "visualTypes": visual_types,
            "contexts": contexts,
            "usageCount": len(r["usages"]),
            "reportUseSummary": report_use_summary,
            "measureDependentCount": len(dependent_measure_keys),
            "measureDependentItems": sorted(analyzer.format_item_ref(dep[-2:]) for dep in dependent_measure_keys),
            "reportUsedMeasureDependentCount": len(report_used_measure_keys),
            "reportUsedMeasureDependentItems": sorted(analyzer.format_item_ref(dep[-2:]) for dep in report_used_measure_keys),
            "relationshipRefCount": relationship_ref_count,
            "otherModelUses": other_model_uses,
            "otherModelUseCount": len(other_model_uses),
            "indirectVia": indirect_via,
            "dependencyItems": [identity_payload(dep) for dep in sorted(dax_measure_deps.get(key, set()) | dax_column_deps.get(key, set()))],
            "dependentItems": [identity_payload(dep) for dep in sorted(reverse_measure_deps.get(key, set()) | reverse_column_deps.get(key, set()))],
            "dependsOnMeasures": sorted(analyzer.format_item_ref(dep[-2:]) for dep in dax_measure_deps.get(key, set())),
            "dependsOnColumns": sorted(analyzer.format_item_ref(dep[-2:]) for dep in dax_column_deps.get(key, set())),
            "dependsOnTables": sorted(dax_table_deps.get(key, set()), key=str.casefold),
            "commentedRefs": sorted(analyzer.extract_dax_commented_refs(item.dax_body or "")),
            "usedByItems": sorted(
                analyzer.format_item_ref(dep[-2:]) for dep in
                (reverse_measure_deps.get(key, set()) | reverse_column_deps.get(key, set()))
            ),
            "usageDetails": [
                {
                    "report": u.report,
                    "reportPath": u.report_path,
                    "page": u.page,
                    "pageHidden": u.page_hidden,
                    "visualHidden": u.visual_hidden,
                    "visualType": u.visual_type,
                    "visualTitle": u.visual_title or "",
                    "visualId": u.visual_id or "",
                    "context": u.context,
                    "sourcePath": u.source_path or "",
                    "artifactKind": u.artifact_kind or "",
                    "artifactPath": u.artifact_path or "",
                    "refType": u.ref_type,
                    "staleKind": u.stale_kind or "",
                    "selectorValue": u.selector_value or "",
                }
                for u in r["usages"]
            ],
            "staleUsageCount": len(r.get("stale_usages", [])),
            "staleUsageDetails": [
                {
                    "report": u.report,
                    "reportPath": u.report_path,
                    "page": u.page,
                    "pageHidden": u.page_hidden,
                    "visualHidden": u.visual_hidden,
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
        (payload_item["type"], payload_item["table"], payload_item["name"], payload_item.get("sourceFile")): {
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
        display_state = item_display_state.get((item.item_type, item.table, item.name, item.source_file or None), {})
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
                    "reportPath": u.report_path,
                    "page": u.page,
                    "pageHidden": u.page_hidden,
                    "visualHidden": u.visual_hidden,
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
                "reportPath": "",
                "page": "",
                "pageHidden": False,
                "visualHidden": False,
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
                "reportPath": u.report_path,
                "page": u.page,
                    "pageHidden": u.page_hidden,
                    "visualHidden": u.visual_hidden,
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

    canonical_items = {(item["type"], item["table"], item["name"], item.get("sourceFile")): item for item in items}
    tables = []
    for table in results.get("table_summaries", []):
        children = [canonical_items.get((child.get("type"), table["name"], child.get("name"), child.get("source_file") or None), {
            "name": child.get("name", ""), "type": child.get("type", ""),
            "table": table["name"], "usageState": "Unknown", "issueState": "Unknown",
            "deleteSafety": "Review", "usageCount": child.get("usage_count", 0),
        }) for child in table.get("items", [])]
        issue_counts = {
            "Broken": sum(bool(child.get("brokenDaxRefs")) or "Broken" in child.get("issueState", "") for child in children),
            "Stale": sum(bool(child.get("staleUsageCount")) or "Stale" in child.get("issueState", "") for child in children),
        }
        if table.get("field_parameter_issues"):
            issue_counts["Broken"] = max(1, issue_counts["Broken"])
        table_usage_status = _table_usage_status(table)
        tables.append({
            "name": table["name"],
            "roleLabel": table.get("role_label", ""),
            "roleReason": table.get("role_reason", ""),
            "usageStatus": table_usage_status,
            "usageState": _table_usage_state(table),
            "issueState": " / ".join(key for key, count in issue_counts.items() if count),
            "issueCounts": issue_counts,
            "cleanupCounts": {state: sum(child.get("deleteSafety") == state for child in children)
                              for state in ("Safe", "Review", "Blocked", "Keep")},
            "sourceKind": "model" if any(c.get("sourceKind") == "model" for c in children) else "report",
            "mSourceDetails": table_source_details.get(table["name"]),
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
            "items": [{**child, "ref": analyzer.format_item_ref((table["name"], child["name"]))} for child in children],
        })

    report_issues = results.get("report_issues", [])
    return {
        "summary": results["summary"],
        "reportBinding": results.get("report_binding"),
        "coverage": results.get("coverage", {}),
        "tables": tables,
        "warnings": results.get("warnings", []),
        "reportIssues": report_issues,
        "reportHealth": _build_report_health(report_issues, items),
        "rootCauseGroups": _build_report_root_cause_groups(report_issues),
        "items": items,
        "references": references,
    }


def _compact_browser_results(payload):
    """Transmit each item/source once; the browser restores the legacy view model."""
    by_identity = {(i['type'], i['table'], i['name'], i.get('sourceFile')): n
                   for n, i in enumerate(payload['items'])}
    for table in payload['tables']:
        table['itemIndices'] = [by_identity[(i['type'], i['table'], i['name'], i.get('sourceFile'))]
                                for i in table.pop('items')]
    for item in payload['items']:
        if item.get('mSourceDetails') is not None:
            item['mSourceTable'] = item['table']
            item.pop('mSourceDetails')
    payload.pop('references')
    payload['_transport'] = 'smc-browser-v1'
    return payload


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
    report_binding = (_report_binding_scope(selected_models[0], reports) if selected_models
                      else {"selected": [], "excluded": []})
    selected_reports = [Path(row["path"]) for row in report_binding["selected"]]
    # Layout preview toggle: ?ui=v2 opts into the new layout, ?ui=classic opts
    # back out; the choice sticks via cookie until changed. Default: v2.
    requested_ui = request.args.get("ui", "").strip().lower()
    if requested_ui not in ("v2", "classic"):
        requested_ui = request.cookies.get("smc_ui", "v2")
    template = "index_v2.html" if requested_ui == "v2" else "index.html"
    response = app.make_response(render_template(
        template,
        build_stamp=_build_stamp(),
        default_root=_state.get("workspace") or str(_default_workspace_root()),
        runtime=_state.get("runtime") or experiments.runtime_config(),
        initial_models=[{"path": str(m), "name": m.name.replace(".SemanticModel", "")} for m in selected_models],
        initial_reports=[{"path": str(r), "name": analyzer.report_display_name(r)} for r in selected_reports],
        initial_report_binding=report_binding,
    ))
    response.set_cookie("smc_ui", "v2" if template == "index_v2.html" else "classic", max_age=60 * 60 * 24 * 365)
    return response


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
@_invalidates_analysis
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
        model_display_name = analyzer.platform_display_name(model_path)
        # Live report connections refer to the published (display) name; the folder
        # name is only a fallback for workspaces without a .platform file.
        model_name_candidates = analyzer.model_name_candidates(model_path)
        selected_model_label = analyzer.model_label(model_path)
        reports_by_path: dict[Path, dict] = {}
        report_statuses = []
        scanned_files = 0
        warnings = []

        for report_root in analyzer.discover_reports([search_root]):
            report_root = report_root.resolve()
            binding = analyzer.report_binding_status(
                report_root,
                model_path,
                names=model_name_candidates,
                label=selected_model_label,
            )
            if binding["scanned"]:
                scanned_files += 1
            warning = binding.pop("warning", None)
            binding.pop("scanned", None)
            report_statuses.append(binding)
            if warning:
                warnings.append(warning)
            if binding["status"] not in analyzer.BOUND_REPORT_STATUSES:
                continue

            reports_by_path.setdefault(report_root, {
                "path": str(report_root),
                "name": analyzer.report_display_name(report_root),
                "status": binding["status"],
                "definitionFiles": [],
            })
            reports_by_path[report_root]["definitionFiles"].append(binding["definitionFile"])

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
@_invalidates_analysis
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
@_invalidates_analysis
def api_analyze():
    """Run analysis and return JSON results."""
    try:
        data = request.get_json(silent=True) or {}
        model_paths = data.get("model_paths", _state["model_paths"])
        report_paths = data.get("report_paths", _state["report_paths"])

        if not isinstance(model_paths, list) or not isinstance(report_paths, list) or not model_paths or not report_paths:
            return jsonify({"error": "No model or reports selected. Run discover first."}), 400
        if len(model_paths) != 1:
            return jsonify({
                "error": "Select exactly one semantic model and one or more reports before analyzing.",
            }), 400
        missing = [p for p in [*model_paths, *report_paths] if not isinstance(p, str) or not Path(p).is_dir()]
        if missing:
            return jsonify({
                "error": "These folders were not found: "
                + ", ".join(str(p) for p in missing)
                + ". Check that the paths still exist and try again.",
            }), 400
        scope = _report_binding_scope(model_paths[0], report_paths)
        report_paths = [row["path"] for row in scope["selected"]]
        if not report_paths:
            return jsonify({"error": "No connected reports selected. Check report bindings or choose another model.",
                            "reportBinding": scope}), 400

        results = analyzer.analyze(
            workspace=Path(_state["workspace"]) if _state["workspace"] else Path("."),
            model_paths=[Path(p) for p in model_paths],
            report_paths=[Path(p) for p in report_paths],
        )

        _record_report_scope(results, scope)
        _state.update(model_paths=model_paths, report_paths=report_paths, last_results=results)
        return jsonify(_serialize_results(results))
    except analyzer.UnsupportedSemanticModelError as e:
        return jsonify({"error": str(e)}), 400
    except SystemExit:
        return jsonify({"error": "Analysis failed — no models or reports found at the given paths."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analysis-jobs", methods=["POST"])
def api_start_analysis_job():
    data = request.get_json(silent=True) or {}
    models = data.get("model_paths", _state["model_paths"])
    reports = data.get("report_paths", _state["report_paths"])
    if not isinstance(models, list) or len(models) != 1 or not isinstance(reports, list) or not reports:
        return jsonify({"error": "Select exactly one semantic model and one or more reports."}), 400
    try:
        if any(not isinstance(p, str) or not Path(p).is_dir() for p in models + reports):
            raise ValueError("Selected model/report folders were not found.")
        requested_reports = reports
        scope = _report_binding_scope(models[0], requested_reports)
        reports = [row["path"] for row in scope["selected"]]
        if not reports:
            return jsonify({"error": "No connected reports selected. Check report bindings or choose another model.",
                            "reportBinding": scope}), 400
        workspace = Path(_state["workspace"] or ".")
        raw = {}
        def run(progress):
            before = _analysis_source_fingerprint(models + requested_reports, progress)
            if _report_binding_scope(models[0], requested_reports) != scope:
                raise ValueError('Report bindings changed before analysis. Analyze the current selection again.')
            progress("Reading selected metadata")
            result = analyzer.analyze(workspace=workspace, model_paths=[Path(p) for p in models],
                                      report_paths=[Path(p) for p in reports], progress=progress)
            from .metadata_validation import validate_report_paths
            schema = validate_report_paths(reports, workspace=workspace, progress=progress)
            _record_report_scope(result, scope)
            progress("Preparing browser results")
            payload = _compact_browser_results(_serialize_results(result, model_paths=models))
            payload['schemaValidation'] = schema
            if _analysis_source_fingerprint(models + requested_reports, progress) != before:
                raise ValueError('Source metadata changed during analysis. Analyze the current selection again.')
            if _report_binding_scope(models[0], requested_reports) != scope:
                raise ValueError('Report bindings changed during analysis. Analyze the current selection again.')
            raw['results'] = result
            return payload
        def publish(payload):
            _state.update(model_paths=models, report_paths=reports, last_results=raw['results'])
        job = _analysis_jobs.start(run, publish)
        return jsonify({"job": job}), 202
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 409


@app.route("/api/analysis-jobs/<identity>", methods=["GET", "DELETE"])
def api_analysis_job(identity):
    try:
        job = _analysis_jobs.cancel(identity) if request.method == "DELETE" else _analysis_jobs.get(identity)
        return jsonify({"job": job})
    except KeyError:
        return jsonify({"error": "Analysis job not found or expired."}), 404


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
@_invalidates_analysis
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
@_invalidates_analysis
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
@_invalidates_analysis
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

        options = {"include_dependencies": bool(data.get("include_dependencies", False)),
                   "allow_metadata_loss": bool(data.get("allow_metadata_loss", False))}
        preview = report_writer.migrate_measure_to_model(
            model_path=model_path, report_path=report_path, entity_name=table,
            measure_name=name, target_table=target_table, target_name=target_name,
            dry_run=True, **options)
        if not preview.get("ok") or data.get("dry_run", False):
            return jsonify({"ok": preview.get("ok", False), "result": preview}), (200 if preview.get("ok") else 400)
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
                **options,
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
@_invalidates_analysis
def api_move_measure_to_table():
    """Move model measures to another table and rewrite selected PBIR reports."""
    transaction_roots = []
    snapshot = None
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
        rollback = _restore_cleanup_transaction(transaction_roots, snapshot) if snapshot is not None else None
        return jsonify({"ok": False, "error": str(e),
                        "rolled_back": bool(rollback and rollback["ok"]), "rollback": rollback}), 500


@app.route("/api/model/rename", methods=["POST"])
@_invalidates_analysis
def api_rename_model_metadata():
    """Rename semantic-model tables/measures and rewrite selected PBIR reports."""
    transaction_roots = []
    snapshot = None
    try:
        data = request.get_json(silent=True) or {}
        model_path_str = data.get("model_path") or (_state["model_paths"][0] if _state["model_paths"] else None)
        table_renames = data.get("table_renames") or []
        measure_renames = data.get("measure_renames") or []
        column_renames = data.get("column_renames") or []
        report_path_values = data.get("report_paths") or _state["report_paths"]
        dry_run = bool(data.get("dry_run", False))

        if not model_path_str:
            return jsonify({"error": "No model path specified"}), 400
        if not table_renames and not measure_renames and not column_renames:
            return jsonify({"error": "No table, measure or column renames specified"}), 400
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
            column_renames=column_renames,
            dry_run=True,
        )
        if not model_preview.get("ok"):
            return jsonify(model_preview), 400

        report_preview = report_writer.rewrite_model_reference_changes(
            report_paths=report_paths,
            table_renames=table_renames,
            measure_renames=measure_renames,
            column_renames=column_renames,
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
            column_renames=column_renames,
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
            column_renames=column_renames,
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
        rollback = _restore_cleanup_transaction(transaction_roots, snapshot) if snapshot is not None else None
        return jsonify({"ok": False, "error": str(e),
                        "rolled_back": bool(rollback and rollback["ok"]), "rollback": rollback}), 500


@app.route("/api/report/cleanup-stale", methods=["POST"])
@_invalidates_analysis
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
@_invalidates_analysis
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
@_invalidates_analysis
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


# Shared, persisted plans used by the v2 UI and headless automation.
def _plan_directory() -> Path:
    return _user_data_dir() / "plans"


def _stored_plan(plan_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", plan_id):
        raise change_plan.PlanError("Invalid plan identity")
    return change_plan.load_plan(_plan_directory() / f"{plan_id}.plan.json")


@app.route("/api/plans", methods=["GET", "POST"])
def api_plans():
    try:
        if request.method == "GET":
            directory = _plan_directory()
            plans, receipts = [], []
            for path in sorted(directory.glob("*.plan.json"), reverse=True):
                plan = change_plan.load_plan(path)
                summary = {k: v for k, v in plan.items() if k not in {"inputs", "outputs", "changes"}}
                summary["changes"] = [{k: v for k, v in change.items() if k not in {"before", "after"}} for change in plan["changes"]]
                plans.append(summary)
            for path in sorted(directory.glob("*.receipt.json"), reverse=True):
                receipts.append(json.loads(path.read_text()))
            return jsonify({"plans": plans, "receipts": receipts})
        data = request.get_json(silent=True) or {}
        model_path, error = _cleanup_action_model_path(data)
        if error:
            return jsonify(error[0]), error[1]
        reports = data.get("report_paths") if "report_paths" in data else _state["report_paths"]
        plan = change_plan.create_plan(model_path, reports or [], data.get("operations"))
        change_plan.save_plan(plan, _plan_directory())
        return jsonify({"ok": True, "plan": plan})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/plans/<plan_id>", methods=["GET"])
def api_get_plan(plan_id):
    try:
        return jsonify({"ok": True, "plan": _stored_plan(plan_id)})
    except (ValueError, OSError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/plans/<plan_id>/<operation>", methods=["POST"])
def api_plan_operation(plan_id, operation):
    try:
        plan = _stored_plan(plan_id)
        if operation == "apply":
            with _analysis_jobs.invalidate():
                _state["last_results"] = None
                result = change_plan.apply_plan(plan, _plan_directory())
        elif operation == "restore":
            with _analysis_jobs.invalidate():
                _state["last_results"] = None
                result = change_plan.restore_plan(plan, _plan_directory())
        elif operation == "recover-lock":
            result = change_plan.recover_interrupted_lock(plan, _plan_directory())
        elif operation == "verify":
            result = change_plan.verify_plan(plan)
        else:
            return jsonify({"ok": False, "error": "Unknown plan operation"}), 404
        if operation in {"apply", "restore"} and result.get("ok"):
            _state["last_results"] = None
        return jsonify(result), 200 if result.get("ok") else 409
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409


def _review_scope(data):
    models = data.get('model_paths', _state['model_paths'])
    reports = data.get('report_paths', _state['report_paths'])
    if not isinstance(models, list) or len(models) != 1 or not isinstance(reports, list) or not reports:
        raise ValueError('Select one model and its reports before reviewing policy.')
    workspace = Path(data.get('project_path') or _state['workspace'] or '.').resolve()
    paths = [Path(p).resolve() for p in models + reports]
    if any(not p.is_dir() or not p.is_relative_to(workspace) for p in paths):
        raise ValueError('The policy project folder must contain the selected model and report folders.')
    return workspace, paths[0], paths[1:]


@app.route('/api/review-findings', methods=['POST'])
def api_review_findings():
    from . import review_policy
    try:
        workspace, model, reports = _review_scope(request.get_json(silent=True) or {})
        result = review_policy.review_findings(workspace, model, reports)
        return jsonify({**result, 'project_path': str(workspace),
                        'policy': review_policy.load_policy(workspace)})
    except (ValueError, OSError, TypeError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/review-policy', methods=['PUT'])
def api_save_review_policy():
    from . import review_policy
    try:
        data = request.get_json(silent=True) or {}
        workspace, _, _ = _review_scope(data)
        policy = review_policy.save_policy(workspace, data.get('policy'), expected_digest=data.get('expected_digest'))
        return jsonify({'ok': True, 'policy': policy})
    except (ValueError, OSError, TypeError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/review-policy/decisions', methods=['POST', 'DELETE'])
def api_review_decisions():
    from . import review_policy
    try:
        data = request.get_json(silent=True) or {}
        workspace, _, _ = _review_scope(data)
        if request.method == 'DELETE':
            policy = review_policy.remove_decision(workspace, data.get('decision_id'))
        else:
            policy = review_policy.add_decision(workspace, data.get('finding') or {}, data.get('scope') or {},
                disposition=data.get('disposition'), reason=data.get('reason'), owner=data.get('owner'),
                expires_on=data.get('expires_on'))
        return jsonify({'ok': True, 'policy': policy})
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/naming-preview', methods=['POST'])
def api_naming_preview():
    from . import review_policy
    try:
        data = request.get_json(silent=True) or {}
        workspace, model, reports = _review_scope(data)
        return jsonify(review_policy.naming_preview(workspace, model, reports, policy=data.get('policy')))
    except (ValueError, OSError, TypeError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


if __name__ == "__main__":
    main()
