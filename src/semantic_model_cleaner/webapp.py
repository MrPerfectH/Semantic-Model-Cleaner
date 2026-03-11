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
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import analyzer, tmdl_writer

app = Flask(__name__)

# ── Global state ──────────────────────────────────────────────────────────────

_state = {
    "workspace": None,
    "model_search_roots": None,
    "report_search_roots": None,
    "last_results": None,
    "model_paths": [],
    "report_paths": [],
    "backup_path": None,
}


def _serialize_results(results: dict) -> dict:
    """Serialize analyzer results for JSON API responses."""
    items = []
    for r in results["items"]:
        pages_used = sorted({u.page for u in r["usages"] if u.page})
        visual_types = sorted({u.visual_type for u in r["usages"] if u.visual_type})
        contexts = sorted({u.context for u in r["usages"] if u.context})

        items.append({
            "type": r["item"].item_type,
            "table": r["item"].table,
            "name": r["item"].name,
            "displayFolder": r["item"].display_folder,
            "isHidden": r["item"].is_hidden,
            "isKey": r["item"].is_key,
            "isInferred": r["item"].is_inferred,
            "sortByColumn": r["item"].sort_by_column or None,
            "status": r["status"],
            "removalRisk": r.get("removal_risk", "") or None,
            "pagesUsed": pages_used,
            "visualTypes": visual_types,
            "contexts": contexts,
            "usageCount": len(r["usages"]),
        })

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
            })

    return {
        "summary": results["summary"],
        "warnings": results.get("warnings", []),
        "items": items,
        "references": references,
    }


def _analysis_download_basename(results: dict) -> str:
    models = results.get("summary", {}).get("models", [])
    if not models:
        return "analysis"
    return models[0].replace(".SemanticModel", "")


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/browse", methods=["GET"])
def api_browse():
    """Browse filesystem directories to pick model/report folders.

    Query params:
      path — directory to list (default: workspace root or home)
    Returns sorted list of entries: { name, path, type }
    type is one of: "dir", "model", "report"
    """
    try:
        raw = request.args.get("path", "").strip()
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
        model_roots = body.get("model_roots") or _state["model_search_roots"] or ([_state["workspace"]] if _state["workspace"] else [])
        report_roots = body.get("report_roots") or _state["report_search_roots"] or ([_state["workspace"]] if _state["workspace"] else [])

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
    """Apply actions (move_to_folder, hide, unhide, delete) to selected items."""
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
            if act.get("action") not in ("move_to_folder", "hide", "unhide", "delete"):
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

    args = parser.parse_args()

    _state["workspace"] = str(Path(args.workspace).resolve())
    if args.models_path:
        _state["model_search_roots"] = [str(Path(p).resolve()) for p in args.models_path]
    if args.reports_path:
        _state["report_search_roots"] = [str(Path(p).resolve()) for p in args.reports_path]

    print("\n  Semantic Model Cleaner")
    print("  ─────────────────────")
    print(f"  Workspace : {_state['workspace']}")
    if _state["model_search_roots"]:
        print(f"  Models    : {', '.join(_state['model_search_roots'])}")
    if _state["report_search_roots"]:
        print(f"  Reports   : {', '.join(_state['report_search_roots'])}")
    print(f"  URL       : http://{args.host}:{args.port}")
    print(f"  Debug     : {'on' if args.debug else 'off'}")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
