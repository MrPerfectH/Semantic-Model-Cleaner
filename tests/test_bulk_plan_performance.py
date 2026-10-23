"""Bulk change plans must not re-read the scope once per action or per analysis (#169).

The assertions count work (file reads, report scans, schema validations), not
wall time, and compare every cached path byte-for-byte with the uncached one.
"""
import os
from pathlib import Path
import shutil

import pytest

from semantic_model_cleaner import analyzer, change_plan, metadata_validation, tmdl_writer

DEMO = Path(__file__).parents[1] / "src/semantic_model_cleaner/demo_workspace"


def _bulk_model(root: Path, tables: int, columns: int) -> Path:
    model = root / "Bulk.SemanticModel"
    (model / "definition" / "tables").mkdir(parents=True)
    (model / "definition" / "database.tmdl").write_text(
        "database Bulk\n\tcompatibilityLevel: 1600\n", encoding="utf-8")
    lines = ["model Model", "\tculture: en-US", ""] + [f"ref table T{t}" for t in range(tables)]
    (model / "definition" / "model.tmdl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for t in range(tables):
        body = [f"table T{t}", ""]
        for c in range(columns):
            body += [f"\tcolumn C{c}", "\t\tdataType: string", f"\t\tsourceColumn: C{c}", ""]
        body += [f"\tpartition T{t} = m", "\t\tmode: import", "\t\tsource = let x = 1 in x", ""]
        (model / "definition" / "tables" / f"T{t}.tmdl").write_text("\n".join(body), encoding="utf-8")
    return model


def _tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _count_calls(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return calls


def _count_reads(monkeypatch):
    calls = []
    original = Path.read_text

    def counting(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    return calls


def test_bulk_delete_batch_reads_files_once_and_matches_single_deletes(tmp_path, monkeypatch):
    tables, columns = 12, 6
    model = _bulk_model(tmp_path / "batch", tables, columns)
    reference = tmp_path / "reference" / "Bulk.SemanticModel"
    shutil.copytree(model, reference)
    # Two whole tables go (file removed, model ref dropped); the rest lose four columns.
    actions = [{"action": "delete", "table": f"T{t}", "name": f"C{c}", "item_type": "Column"}
               for t in range(tables) for c in range(columns) if t < 2 or c < 4]
    for action in actions:
        assert tmdl_writer.delete_item(reference, action["table"], action["name"], action["item_type"])["ok"]

    reads = _count_reads(monkeypatch)
    results = tmdl_writer.apply_actions(model, actions)

    assert all(result["ok"] and result["written"] for result in results)
    assert sum(1 for result in results if result.get("table_deleted")) == 2
    assert _tree(model) == _tree(reference)
    tmdl_files = tables + 2
    # Before: every action listed and read the table files again (actions x files).
    assert len(reads) <= tmdl_files + 4 * len(actions)
    assert len(reads) < len(actions) * tmdl_files


def test_bulk_delete_cache_sees_each_earlier_deletion(tmp_path):
    model = _bulk_model(tmp_path / "dup", 3, 3)
    before = _tree(model)
    duplicate = {"action": "delete", "table": "T1", "name": "C1", "item_type": "Column"}
    results = tmdl_writer.apply_actions(model, [duplicate, dict(duplicate)])
    assert results[0]["written"] is False and results[1]["ok"] is False
    assert all(result.get("rolled_back") for result in results)
    assert "not found" in results[1]["error"]
    assert _tree(model) == before

    missing = {"action": "delete", "table": "T2", "name": "Nope", "item_type": "Column"}
    results = tmdl_writer.apply_actions(model, [duplicate, missing])
    assert not any(result["ok"] for result in results)
    assert _tree(model) == before


def test_plan_actions_preview_uses_one_read_per_file(tmp_path, monkeypatch):
    model = _bulk_model(tmp_path / "preview", 8, 5)
    actions = [{"action": "delete", "table": f"T{t}", "name": f"C{c}", "item_type": "Column"}
               for t in range(8) for c in range(5)]
    before = _tree(model)
    reads = _count_reads(monkeypatch)
    plan = tmdl_writer.plan_actions(model, actions)
    assert plan["ok"] and plan["valid_action_count"] == len(actions)
    assert len(reads) <= 8 + 2
    assert _tree(model) == before


def _two_report_workspace(tmp_path):
    root = tmp_path / "workspace"
    shutil.copytree(DEMO, root)
    model = next(root.rglob("*.SemanticModel"))
    source = next(root.rglob("*.Report"))
    reports = []
    for name in ("Report A.Report", "Report B.Report"):
        target = source.parent / name
        shutil.copytree(source, target)
        reports.append(target)
    shutil.rmtree(source)
    (model / "definition" / "tables" / "Orders.tmdl").write_text(
        "table Orders\n\tmeasure Broken = [Missing]\n\tcolumn Quantity\n\t\tdataType: int64\n"
        "\t\tsourceColumn: Quantity\n", encoding="utf-8")
    assert all(analyzer.report_binding_status(report, model)["status"] in analyzer.BOUND_REPORT_STATUSES
               for report in reports)
    return root, model, reports


def test_analysis_cache_replays_identical_results_and_scans_each_report_once(tmp_path, monkeypatch):
    root, model, reports = _two_report_workspace(tmp_path)
    scans = _count_calls(monkeypatch, analyzer, "scan_report_visuals")
    parses = _count_calls(monkeypatch, analyzer, "parse_model_items")
    plain = [analyzer.analyze(root, model_paths=[model], report_paths=reports)]
    parses_per_analysis = len(parses)
    plain += [analyzer.analyze(root, model_paths=[model], report_paths=[report]) for report in reports]
    assert len(scans) == 2 * len(reports)
    assert len(parses) == parses_per_analysis * (1 + len(reports))
    del scans[:], parses[:]

    cache = analyzer.AnalysisCache()
    reads = _count_reads(monkeypatch)
    cached = [analyzer.analyze(root, model_paths=[model], report_paths=reports, cache=cache)]
    cached += [analyzer.analyze(root, model_paths=[model], report_paths=[report], cache=cache)
               for report in reports]
    assert len(scans) == len(reports)
    assert len(parses) == parses_per_analysis
    from collections import Counter
    json_reads = Counter(path for path in reads if path.suffix == ".json")
    # every report JSON file is parsed once for all three analyses together
    # (page.json is also opened by the page-name helper)
    assert set(json_reads) == {path for report in reports for path in report.rglob("*.json")}
    assert all(count == (2 if path.name == "page.json" else 1) for path, count in json_reads.items())
    for expected, actual in zip(plain, cached, strict=True):
        assert analyzer.format_json_output(actual) == analyzer.format_json_output(expected)
        assert actual["report_issues"] == expected["report_issues"]
        assert actual["dependency_graphs"] == expected["dependency_graphs"]
        assert actual["summary"] == expected["summary"]
    assert cached[0]["summary"]["broken"] == 1


def test_plan_analysis_scans_each_report_once_per_snapshot(tmp_path, monkeypatch):
    root, model, reports = _two_report_workspace(tmp_path)
    roots = change_plan._roots(model, reports)
    scans = _count_calls(monkeypatch, analyzer, "scan_report_visuals")
    analyses = _count_calls(monkeypatch, analyzer, "analyze")
    result = change_plan._analyze(roots)
    assert len(analyses) == 1 + len(reports)
    assert len(scans) == len(reports)
    assert set(result["_report_issues_by_artifact"]) == {"report-1", "report-2"}
    reference = {key: analyzer.analyze(root, model_paths=[model], report_paths=[path])["report_issues"]
                 for key, path in roots.items() if key != "model"}
    assert result["_report_issues_by_artifact"] == reference


def test_bulk_plan_keeps_guards_and_counts_work(tmp_path, monkeypatch):
    root, model, reports = _two_report_workspace(tmp_path)
    operation = {"kind": "actions", "actions": [
        {"action": "delete", "table": "Orders", "name": "Broken", "item_type": "Measure"}]}
    scans = _count_calls(monkeypatch, analyzer, "scan_report_visuals")
    validations = _count_calls(monkeypatch, metadata_validation, "validate_document")
    plan = change_plan.create_plan(model, reports, [operation])
    # policy check and before snapshot share one scan; the after snapshot scans again
    assert len(scans) == 2 * len(reports)
    json_documents = sum(1 for key in plan["inputs"]
                         if Path(key).suffix in metadata_validation.METADATA_SUFFIXES)
    # The after snapshot validates only documents whose bytes changed (none here).
    assert len(validations) == json_documents
    assert plan["validation"]["pbir_schema"]["before"] == plan["validation"]["pbir_schema"]["after"]
    assert [change["path"] for change in plan["changes"]] == ["model/definition/tables/Orders.tmdl"]
    used = {"kind": "actions", "actions": [
        {"action": "delete", "table": "Sales", "name": "Revenue", "item_type": "Measure"}]}
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, reports, [used])


def test_validate_metadata_memo_replays_only_identical_documents(monkeypatch):
    files = {"a.json": b'{"x": 1}', "b.json": b'{"$schema": "https://example.invalid/x", "y": 2}',
             "c.tmdl": b"table T"}
    fresh = metadata_validation.validate_metadata(files)
    memo = {}
    first = metadata_validation.validate_metadata(files, memo=memo)
    assert first == fresh
    validations = _count_calls(monkeypatch, metadata_validation, "validate_document")
    changed = dict(files, **{"a.json": b'{"x": 2}'})
    second = metadata_validation.validate_metadata(changed, memo=memo)
    assert [call[1]["path"] if len(call) > 1 else None for call in validations] in ([None], [])
    assert len(validations) == 1
    assert second["files"][1] == first["files"][1]
    assert second["files"][0]["content_hash"] != first["files"][0]["content_hash"]
    assert second == metadata_validation.validate_metadata(changed)


def test_inventory_matches_rglob_order_and_rejects_symlinks(tmp_path):
    root = tmp_path / "Scope.SemanticModel"
    for relative in ("definition/model.tmdl", "definition/tables/b.tmdl", "definition/tables/a.tmdl",
                     "definition/pages/p1/visuals/v1/visual.json", "definition/pages/p1/page.json",
                     "definition.pbir", "notes.md", "diag.queryPlans"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    (root / "definition" / "empty").mkdir()
    expected = {f"model/{path.relative_to(root).as_posix()}": path.read_bytes()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix.lower() in change_plan.SUFFIXES}
    actual = change_plan._inventory({"model": root})
    assert list(actual) == list(expected)
    assert actual == expected
    try:
        os.symlink(root / "notes.md", root / "definition" / "link.tmdl")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(change_plan.PlanError, match="Symlinks are not supported"):
        change_plan._inventory({"model": root})


def _reference_fuzzy_suggestions(usage, items):
    """The pre-#169 scoring, kept verbatim as the oracle for the pruned version."""
    from difflib import SequenceMatcher
    target_name = analyzer._normalize_suggestion_text(usage.name)
    target_table = analyzer._normalize_suggestion_text(usage.table)
    if not target_name:
        return []
    candidates = []
    for item in items:
        if not analyzer._item_matches_ref_type(item, usage.ref_type):
            continue
        item_name = analyzer._normalize_suggestion_text(item.name)
        item_table = analyzer._normalize_suggestion_text(item.table)
        if not item_name:
            continue
        if (target_name[0] != item_name[0] and target_name not in item_name
                and item_name not in target_name and target_table != item_table):
            continue
        name_score = SequenceMatcher(None, target_name, item_name).ratio()
        table_score = SequenceMatcher(None, target_table, item_table).ratio() if target_table and item_table else 0.0
        score = (name_score * 0.75) + (table_score * 0.25)
        if target_name == item_name:
            score = max(score, 0.93)
        if score < 0.64:
            continue
        candidates.append({"table": item.table, "name": item.name, "type": item.item_type,
                           "score": round(score, 3), "confidence": analyzer._suggestion_confidence(score),
                           "action": "suggest_replace"})
    candidates.sort(key=lambda s: (-s["score"], s["table"].casefold(), s["name"].casefold()))
    return candidates[:5]


def test_fuzzy_suggestion_pruning_never_changes_the_result():
    import random
    rng = random.Random(169)
    words = ["sales", "revenue", "margin", "amount", "qty", "order", "date", "plant", "cost", "net",
             "gross", "total", "avg", "count", "flag", "id", "key", "name", "status", "type"]

    def phrase():
        return " ".join(rng.choice(words) for _ in range(rng.randint(1, 4)))

    tables = [phrase().title() for _ in range(12)]
    items = [analyzer.ModelItem(item_type=rng.choice(["Measure", "Column", "Calculated Column"]),
                                table=rng.choice(tables), name=phrase()) for _ in range(300)]
    usages = [analyzer.UsageRef(table=rng.choice(tables + [phrase()]), name=phrase(),
                                ref_type=rng.choice(["Measure", "Column", "metadata"]))
              for _ in range(200)]
    usages += [analyzer.UsageRef(table=item.table, name=item.name + "x", ref_type=item.item_type)
               for item in items[:40]]
    for usage in usages:
        assert analyzer._fuzzy_suggestions(usage, items) == _reference_fuzzy_suggestions(usage, items)
