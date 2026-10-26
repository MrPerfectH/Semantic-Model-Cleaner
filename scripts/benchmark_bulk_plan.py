#!/usr/bin/env python3
"""Successful synthetic bulk deletion, phase timings and exact-output evidence (#169).

Always generates a NEW fixture. Select the engine revision with PYTHONPATH; no
customer project is accepted. Planning is timed separately from apply/recovery.
"""
import argparse
from contextlib import ExitStack
import cProfile
from functools import wraps
import hashlib
import inspect
import json
from pathlib import Path
import platform
import pstats
import time
from unittest.mock import patch

from semantic_model_cleaner import analyzer, change_plan, cleanup_policy, metadata_validation, tmdl_writer

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def generate_fixture(output, *, deletions=787, tables=40, columns=33, measures=16,
                     reports=8, pages_per_report=20, visuals=5067):
    sizes = (deletions, tables, columns, measures, reports, pages_per_report, visuals)
    if any(type(value) is not int or value < 1 for value in sizes):
        raise ValueError("All fixture sizes must be positive integers.")
    if tables > 100 or columns > 100 or measures > 100 or reports > 100 or pages_per_report > 100 or visuals > 100000:
        raise ValueError("Fixture exceeds the supported synthetic size limits.")
    pages = reports * pages_per_report
    if visuals < pages or deletions > tables * (columns + measures - 2):
        raise ValueError("Require at least one visual per page and enough unused items for the requested deletions.")
    output = Path(output)
    if output.is_symlink() or output.exists():
        raise ValueError("Output must be a new directory; existing paths and symlinks are refused.")
    output.mkdir(parents=True, exist_ok=False)
    root = output.resolve() / "project"
    model = root / "Bulk.SemanticModel"
    folder = model / "definition/tables"
    folder.mkdir(parents=True)
    (model / "definition/model.tmdl").write_text("model Model\n\tculture: en-US\n" +
        "".join(f"\nref table T{index:03d}\n" for index in range(tables)), encoding="utf-8")
    for index in range(tables):
        table = f"T{index:03d}"
        lines = [f"table {table}", f"\tmeasure Keep = SUM({table}[C{columns - 1:02d}])"]
        for number in range(measures - 1):
            lines.append(f"\tmeasure Idle{number:02d} = {number + 1}")
        for number in range(columns):
            lines += [f"\tcolumn C{number:02d}", "\t\tdataType: int64", f"\t\tsourceColumn: C{number:02d}"]
        names = ", ".join(f'"C{number:02d}"' for number in range(columns))
        lines += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =",
                  f"\t\t\t#table({{{names}}}, {{{{{', '.join('0' for _ in range(columns))}}}}})"]
        (folder / (table + ".tmdl")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    candidates = {"Measure": [(f"T{table:03d}", f"Idle{item:02d}") for item in range(measures - 1) for table in range(tables)],
                  "Column": [(f"T{table:03d}", f"C{item:02d}") for item in range(columns - 1) for table in range(tables)]}
    measure_count = min(len(candidates["Measure"]), deletions * 35 // 100)
    column_count = min(len(candidates["Column"]), deletions - measure_count)
    measure_count = deletions - column_count
    actions = [{"action": "delete", "table": table, "name": name, "item_type": kind}
               for kind, count in (("Measure", measure_count), ("Column", column_count))
               for table, name in candidates[kind][:count]]
    report_paths = []
    visual_index = 0
    for index in range(reports):
        report = root / f"Report{index:02d}.Report"
        report_paths.append(report)
        _json(report / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": "../Bulk.SemanticModel"}}})
        _json(report / "definition/report.json", {})
        for number in range(pages_per_report):
            page_index = index * pages_per_report + number
            page = report / "definition/pages" / f"P{number:03d}"
            _json(page / "page.json", {"$schema": SCHEMA + "page/2.1.0/schema.json", "name": page.name,
                "displayName": page.name, "displayOption": "FitToPage", "height": 720, "width": 1280})
            count = visuals // pages + (page_index < visuals % pages)
            for item in range(count):
                table = f"T{visual_index % tables:03d}"
                name = f"V{item:03d}"
                _json(page / "visuals" / name / "visual.json", {"$schema": SCHEMA + "visualContainer/2.9.0/schema.json",
                    "name": name, "position": {"x": 0, "y": 0, "height": 100, "width": 200},
                    "visual": {"visualType": "card", "query": {"queryState": {"Values": {"projections": [
                        {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": "Keep"}},
                         "queryRef": table + ".Keep"}]}}}}})
                visual_index += 1
    operations = [{"kind": "actions", "actions": actions}]
    _json(output / "operations.json", operations)
    return root, model, report_paths, operations, {"items": tables * (columns + measures),
        "delete_actions": len(actions), "operations": 1, "tables": tables, "reports": reports,
        "pages": pages, "visuals": visual_index}


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def benchmark(output, *, profile=False, **sizes):
    root, model, reports, operations, counts = generate_fixture(output, **sizes)
    output = Path(output)
    before = _snapshot(root)
    phases, reads = {}, {"text": 0, "bytes": 0}

    def timed(label, function):
        @wraps(function)
        def measured(*args, **kwargs):
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                return function(*args, **kwargs)
            finally:
                record = phases.setdefault(label, {"calls": 0, "wall_s": 0.0, "cpu_s": 0.0})
                record["calls"] += 1
                record["wall_s"] += time.perf_counter() - wall
                record["cpu_s"] += time.process_time() - cpu
        return measured

    def counted(kind, function):
        def read(*args, **kwargs):
            reads[kind] += 1
            return function(*args, **kwargs)
        return read

    keywords = {}
    parameters = inspect.signature(change_plan.create_plan).parameters
    if "known_reports" in parameters:
        keywords["known_reports"] = reports
    if "report_search_roots" in parameters:
        keywords["report_search_roots"] = [root]
    profiler = cProfile.Profile() if profile else None
    targets = [(change_plan, "_inventory", "metadata_inventory"),
               (change_plan, "_resource_inventory", "resource_inventory"),
               (change_plan, "_analyze", "plan_analysis"),
               (cleanup_policy, "evaluate_deletion_policy", "deletion_policy"),
               (metadata_validation, "validate_metadata", "schema_validation"),
               (tmdl_writer, "apply_actions", "staged_writes")]
    with ExitStack() as stack:
        for module, name, label in targets:
            if hasattr(module, name):
                stack.enter_context(patch.object(module, name, timed(label, getattr(module, name))))
        for name, kind in (("read_text", "text"), ("read_bytes", "bytes")):
            stack.enter_context(patch.object(Path, name, counted(kind, getattr(Path, name))))
        wall, cpu = time.perf_counter(), time.process_time()
        if profiler:
            profiler.enable()
        try:
            plan = change_plan.create_plan(model, reports, operations, **keywords)
        finally:
            if profiler:
                profiler.disable()
        elapsed = {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu}
    if _snapshot(root) != before:
        raise AssertionError("Planning modified fixture inputs.")
    _json(output / "plan.json", plan)
    top = []
    if profiler:
        profiler.dump_stats(str(output / "planning.pstats"))
        stats = pstats.Stats(profiler).stats
        for (filename, line, function), (primitive, calls, own, total, _) in sorted(stats.items(), key=lambda item: -item[1][3])[:20]:
            top.append({"file": Path(filename).name, "line": line, "function": function,
                        "calls": calls, "primitive_calls": primitive, "own_s": own, "cumulative_s": total})
    applied = change_plan.apply_plan(plan, output / "journal")
    if not applied["ok"] or not change_plan.verify_plan(plan)["ok"]:
        raise AssertionError("Apply or verification failed.")
    remaining = len(analyzer.parse_model_items(model))
    if remaining != counts["items"] - counts["delete_actions"]:
        raise AssertionError("Unexpected number of model items after cleanup.")
    if not change_plan.restore_plan(plan, output / "journal")["ok"] or _snapshot(root) != before:
        raise AssertionError("Restore did not recover every fixture byte.")
    result = {"ok": True, "environment": {"python": platform.python_version(), "system": platform.system(),
              "machine": platform.machine()}, "fixture": counts, "profiled": profile, "planning": elapsed,
              "phases_inclusive": phases, "planning_reads": reads, "top_cumulative_functions": top,
              "changed_files": len(plan["changes"]), "equivalence": {key: _hash(plan[key]) for key in ("inputs", "outputs", "changes", "validation")},
              "proof": {"planning_read_only": True, "apply_verified": True, "removed_items": counts["items"] - remaining,
                        "restored_byte_exact": True}, "validation": plan["validation"]}
    _json(output / "benchmark.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New output directory for the synthetic fixture, plan and evidence.")
    parser.add_argument("--profile", action="store_true", help="Also write planning.pstats; compare profiled runs only to profiled runs.")
    for name, default in (("deletions", 787), ("tables", 40), ("columns", 33), ("measures", 16),
                          ("reports", 8), ("pages-per-report", 20), ("visuals", 5067)):
        parser.add_argument("--" + name, type=int, default=default)
    args = vars(parser.parse_args(argv))
    try:
        print(json.dumps(benchmark(**args), indent=2))
        return 0
    except (ValueError, OSError, AssertionError, change_plan.PlanError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
