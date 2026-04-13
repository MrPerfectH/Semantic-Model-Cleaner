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
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import __version__, analyzer, experiments, tmdl_writer

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
}

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:(?![\\/])")


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


def _serialize_results(results: dict) -> dict:
    """Serialize analyzer results for JSON API responses."""
    def _delete_safety(item_payload: dict) -> str:
        if item_payload.get("isInferred"):
            return "Do not remove"
        if item_payload.get("status", "").startswith("BROKEN"):
            return "Blocked"
        risk = item_payload.get("removalRisk") or ""
        if risk == "Safe":
            return "Safe"
        if risk == "Review":
            return "Review"
        if risk == "Do not remove":
            return "Do not remove"
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
            "displayFolder": item.display_folder,
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
                    "context": u.context,
                    "refType": u.ref_type,
                }
                for u in r["usages"]
            ],
        }
        payload_item["deleteSafety"] = _delete_safety(payload_item)
        items.append(payload_item)

    references = []
    for r in results["items"]:
        item = r["item"]
        status = r["status"]
        risk = r.get("removal_risk", "") or None
        if r["usages"]:
            for u in r["usages"]:
                references.append({
                    "type": item.item_type,
                    "table": item.table,
                    "name": item.name,
                    "isHidden": item.is_hidden,
                    "displayFolder": item.display_folder,
                    "report": u.report,
                    "page": u.page,
                    "visualType": u.visual_type,
                    "visualTitle": u.visual_title or "",
                    "context": u.context,
                    "status": status,
                    "removalRisk": risk,
                    "reviewTriggers": r.get("review_triggers", []),
                    "brokenDaxRefs": r.get("broken_dax_refs", []),
                    "brokenDaxRefDetails": r.get("broken_dax_ref_details", []),
                })
        else:
            references.append({
                "type": item.item_type,
                "table": item.table,
                "name": item.name,
                "isHidden": item.is_hidden,
                "displayFolder": item.display_folder,
                "report": "",
                "page": "",
                "visualType": "",
                "visualTitle": "",
                "context": "",
                "status": status,
                "removalRisk": risk,
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

    return {
        "summary": results["summary"],
        "tables": tables,
        "warnings": results.get("warnings", []),
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
        _state["model_paths"] = model_paths
        _state["report_paths"] = report_paths

        results = analyzer.analyze(
            workspace=Path(_state["workspace"]) if _state["workspace"] else Path("."),
            model_paths=[Path(p) for p in model_paths],
            report_paths=[Path(p) for p in report_paths],
        )

        _state["last_results"] = results
        return jsonify(_serialize_results(results))
    except SystemExit:
        return jsonify({"error": "Analysis failed — no models or reports found at the given paths."}), 400
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
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        actions = data.get("actions", [])
        if not actions:
            return jsonify({"error": "No actions specified"}), 400

        model_path_str = data.get("model_path")
        if not model_path_str:
            # Use first discovered model
            if _state["model_paths"]:
                model_path_str = _state["model_paths"][0]
            else:
                return jsonify({"error": "No model path specified"}), 400

        model_path = Path(model_path_str)
        if not model_path.exists():
            return jsonify({"error": f"Model path not found: {model_path}"}), 400

        # Create backup only if requested by user and not already done this session
        if data.get("create_backup", False) and _state["backup_path"] is None:
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))

        # Git dirty check
        git_warning = tmdl_writer.check_git_dirty(model_path)

        # Validate actions
        for act in actions:
            if act.get("action") not in ("move_to_folder", "move_to_table_group", "hide", "unhide", "delete"):
                return jsonify({"error": f"Invalid action: {act.get('action')}"}), 400
            for field in ("table", "name", "item_type"):
                if not act.get(field):
                    return jsonify({"error": f"Missing field '{field}' in action"}), 400

        results = tmdl_writer.apply_actions(model_path, actions)

        return jsonify({
            "results": results,
            "backup_path": _state["backup_path"],
            "git_warning": git_warning,
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

        if data.get("create_backup", False) and _state["backup_path"] is None:
            _state["backup_path"] = str(tmdl_writer.create_backup(model_path))

        git_warning = tmdl_writer.check_git_dirty(model_path)
        result = tmdl_writer.set_dax_expression(
            model_path=model_path,
            table=table,
            name=name,
            item_type=item_type,
            dax_expression=str(dax_expression),
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
