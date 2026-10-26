"""Regression coverage for combining reviewed caches with main's scope and analysis APIs."""
from copy import deepcopy
import json

import pytest

from semantic_model_cleaner import analyzer, metadata_validation as metadata


@pytest.mark.parametrize("first_enabled", [False, True])
def test_suggestion_mode_does_not_poison_or_leak_shared_cache(tmp_path, monkeypatch, first_enabled):
    model = tmp_path / "M.SemanticModel"
    (model / "definition/tables").mkdir(parents=True)
    (model / "definition/tables/Sales.tmdl").write_text(
        "table Sales\n\tmeasure Revenue = 1\n", encoding="utf-8")
    report = tmp_path / "R.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition.pbir").write_text(
        '{"datasetReference":{"byPath":{"path":"../M.SemanticModel"}}}', encoding="utf-8")
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    visual = report / "definition/pages/P/visuals/V/visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({"visual": {"query": {"queryState": {
        "Values": {"projections": [{"field": {"Measure": {
            "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Revenu"}}}]}
    }}}}), encoding="utf-8")
    calls = []
    original = analyzer._fuzzy_suggestions

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(analyzer, "_fuzzy_suggestions", counted)
    cache = analyzer.AnalysisCache()
    for enabled in (first_enabled, not first_enabled, True):
        result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report],
                                  cache=cache, suggestions=enabled)
        issue = next(i for i in result["report_issues"] if i["name"] == "Revenu")
        assert bool(issue["suggestions"]) is enabled
    assert len(calls) == 1


def test_schema_memo_records_are_isolated_and_revalidate_limit_and_bundle(monkeypatch):
    files = {"report-1/page.json": json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
        "name": "Page", "width": "bad",
    })}
    memo = {}
    fresh = metadata.validate_metadata(files)
    first = metadata.validate_metadata(files, memo=memo)
    assert first["files"][0]["errors"]
    first["files"][0]["errors"].clear()
    replayed = metadata.validate_metadata(files, memo=memo)
    assert replayed == fresh
    replayed["files"][0]["errors"].clear()
    assert metadata.validate_metadata(files, memo=memo) == fresh

    calls = []
    original = metadata.validate_document
    monkeypatch.setattr(metadata, "validate_document",
                        lambda *a, **kw: calls.append(kw) or original(*a, **kw))
    limited = metadata.validate_metadata(files, memo=memo, previous=fresh, error_limit=1)
    assert len(calls) == 1 and limited["files"][0]["truncated"]
    changed_bundle = deepcopy(metadata.bundle_info())
    changed_bundle["commit"] = "different-bundle"
    monkeypatch.setattr(metadata, "bundle_info", lambda: changed_bundle)
    metadata.validate_metadata(files, memo=memo, previous=fresh)
    assert len(calls) == 2
