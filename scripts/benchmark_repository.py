#!/usr/bin/env python3
"""Read-only metadata benchmark. Outputs counts/timings only, never model values.

Import the implementation being measured using PYTHONPATH. For comparable RSS
peaks, run each model in a fresh process. ru_maxrss is a process high-water mark.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import gzip
import io
import json
from pathlib import Path
import platform
try:
    import resource
except ImportError:  # Windows can still measure timings and transport sizes.
    resource = None
import statistics
import time

from semantic_model_cleaner import analyzer, webapp


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def benchmark_repository(workspace: Path, *, model_index: int = 0, repeats: int = 3) -> dict:
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    workspace = Path(workspace).resolve()
    models = analyzer.discover_models([workspace])
    if model_index < 0 or model_index >= len(models):
        raise ValueError("Model index is out of range")
    model = models[model_index]
    reports = analyzer.filter_reports_bound_to_model(analyzer.discover_reports([workspace]), model)
    if not reports:
        raise ValueError("Selected model has no locally matched reports")
    records = []
    counts = {}
    for _ in range(repeats):
        started = time.perf_counter()
        # Redirect all analyzer diagnostics too: privacy is the default for these
        # benchmark outputs even when the inspected project is malformed.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = analyzer.analyze(workspace, model_paths=[model], report_paths=reports)
        analyzed = time.perf_counter()
        payload = webapp._serialize_results(result, model_paths=[model])
        serialized = time.perf_counter()
        full = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        full_encoded = time.perf_counter()
        packed = webapp._compact_browser_results(payload)
        compacted = time.perf_counter()
        compact = json.dumps(packed, ensure_ascii=False, separators=(",", ":")).encode()
        compact_encoded = time.perf_counter()
        compressed = gzip.compress(compact, compresslevel=3, mtime=0)
        finished = time.perf_counter()
        records.append({"analysis_s": analyzed - started, "full_serialization_s": serialized - analyzed,
                        "full_json_s": full_encoded - serialized, "compact_transform_s": compacted - full_encoded,
                        "compact_json_s": compact_encoded - compacted, "gzip_s": finished - compact_encoded,
                        "total_wall_s": finished - started, "full_json_bytes": len(full),
                        "compact_json_bytes": len(compact), "gzip_bytes": len(compressed),
                        "peak_rss_bytes": _peak_rss_bytes()})
        counts = {"model_items": len(result["items"]), "tables": len(result.get("table_summaries", [])),
                  "reports": len(reports), "live_references": result["summary"]["total_usage_refs"],
                  "report_issues": len(result.get("report_issues", [])), "warnings": len(result.get("warnings", [])),
                  "scan_complete": result.get("coverage", {}).get("complete", False)}
        # Drop large graphs between repeats rather than retaining last payloads.
        del result, payload, packed, full, compact, compressed
    return {"schema_version": "1.0", "ok": True, "model_index": model_index,
            "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
            "counts": counts, "repeats": repeats, "samples": records,
            "medians": {key: (statistics.median(record[key] for record in records) if records[0][key] is not None else None) for key in records[0]},
            "peak_rss_bytes": max((record["peak_rss_bytes"] or 0 for record in records), default=0) or None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--model-index", type=int, default=0, help="Zero-based sorted discovery index; no names are emitted")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        result = benchmark_repository(args.workspace, model_index=args.model_index, repeats=args.repeats)
        print(json.dumps(result, indent=2))
        return 0
    except (Exception, SystemExit) as exc:
        # Do not print exception messages: parsers may include customer names,
        # snippets, or paths. Reproduce locally with ordinary tools to diagnose.
        print(json.dumps({"schema_version": "1.0", "ok": False, "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
