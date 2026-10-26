"""Plan validation analyzes each side once, without changing what it detects."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def visual(report, page, table, name, kind="Measure"):
    write_json(report / f"definition/pages/{page}/visuals/V/visual.json", {"visual": {"query": {"queryState": {
        "Values": {"projections": [{"field": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}}]}}}}})
    write_json(report / f"definition/pages/{page}/page.json", {"name": page, "displayName": page})


@pytest.fixture
def project(tmp_path):
    """Two Reports with the same display name and identical visual paths."""
    model = tmp_path / "M.SemanticModel"
    (model / "definition/tables").mkdir(parents=True)
    (model / "definition/tables/Sales.tmdl").write_text(
        "table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n\tmeasure Cost = 1\n", encoding="utf-8")
    reports = []
    for parent in ("A", "B"):
        report = tmp_path / parent / "Same.Report"
        write_json(report / "definition.pbir", {"datasetReference": {"byPath": {"path": "../../M.SemanticModel"}}})
        write_json(report / "definition/report.json", {})
        reports.append(report)
    visual(reports[0], "P", "Sales", "Revenue")
    visual(reports[1], "P", "Sales", "Gone")  # pre-existing broken reference, same location as A's visual
    write_json(reports[1] / "definition/reportExtensions.json", {"name": "extension", "entities": [
        {"name": "Sales", "measures": [{"name": "Local", "expression": "[Cost]"}]}]})
    visual(reports[1], "L", "Sales", "Local")
    return model, reports


def roots(model, reports):
    return change_plan._roots(model, reports)


def test_one_analysis_groups_issues_like_separate_per_report_analyses(project, monkeypatch):
    model, reports = project
    expected = {key: analyzer.analyze(model.parent, model_paths=[model], report_paths=[path])["report_issues"]
                for key, path in roots(model, reports).items() if key != "model"}
    calls = []
    original = analyzer.analyze
    monkeypatch.setattr(analyzer, "analyze", lambda *a, **kw: calls.append(1) or original(*a, **kw))
    grouped = change_plan._analyze(roots(model, reports))["_report_issues_by_artifact"]
    assert len(calls) == 1
    key = lambda issue: json.dumps(issue, sort_keys=True)
    assert {k: sorted(map(key, v)) for k, v in grouped.items()} == {k: sorted(map(key, v)) for k, v in expected.items()}
    assert grouped["report-1"] == [] and any(i["name"] == "Gone" for i in grouped["report-2"])


def test_new_break_in_one_report_is_not_hidden_by_identical_existing_error_in_its_twin(project):
    model, reports = project
    delete = {"kind": "actions", "actions": [{"action": "delete", "table": "Sales", "name": "Cost", "item_type": "Measure"}]}
    rename = {"kind": "rename", "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Gone"}]}
    # Renaming Revenue to Gone fixes B and keeps A resolved; deleting Cost breaks B's extension measure.
    assert change_plan.create_plan(model, reports, [rename])
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, reports, [delete])


def test_plan_analysis_never_computes_repair_suggestions(project, monkeypatch):
    model, reports = project
    calls = []
    monkeypatch.setattr(analyzer, "_fuzzy_suggestions", lambda *a, **kw: calls.append(1) or [])
    change_plan.create_plan(model, reports, [{"kind": "actions", "actions": [
        {"action": "hide", "table": "Sales", "name": "Cost", "item_type": "Measure"}]}])
    assert calls == []
    full = analyzer.analyze(model.parent, model_paths=[model], report_paths=reports)
    assert calls, "interactive analysis still offers suggestions"
    assert any(i["name"] == "Gone" for i in full["report_issues"])


def test_dax_tokenising_is_cached_but_callers_get_independent_lists():
    from semantic_model_cleaner import reference_tokens
    text = "SUMX('Sales', [Amount]) // note"
    first = reference_tokens.dax_tokens(text)
    first.append("caller mutation")
    second = reference_tokens.dax_tokens(text)
    assert "caller mutation" not in second and second == first[:-1]
    assert reference_tokens.dax_tokens.cache_info().hits >= 1
    assert analyzer._split_dax_comments(text) == analyzer._split_dax_comments(text)
    assert analyzer._split_dax_comments.cache_info().hits >= 1


def test_dax_reference_extraction_is_cached_but_callers_get_independent_sets():
    text = "SUMX('Sales', Sales[Amount]) + [Margin] // [Ignored]"
    first_qualified = analyzer._extract_dax_qualified_refs(text)
    first_unqualified = analyzer._extract_dax_unqualified_refs(text)
    assert first_qualified == {("Sales", "Amount")} and first_unqualified == {"Margin"}
    first_qualified.add(("caller", "mutation"))
    first_unqualified.add("caller mutation")
    assert analyzer._extract_dax_qualified_refs(text) == {("Sales", "Amount")}
    assert analyzer._extract_dax_unqualified_refs(text) == {"Margin"}
    assert analyzer._cached_dax_qualified_refs.cache_info().hits >= 1
    assert analyzer._cached_dax_unqualified_refs.cache_info().hits >= 1


def test_report_level_measure_only_satisfies_references_in_its_own_report(project):
    model, reports = project
    visual(reports[0], "L", "Sales", "Local")  # A uses B's report-level measure name
    result = analyzer.analyze(model.parent, model_paths=[model], report_paths=reports, suggestions=False)
    missing = {(issue["reportPath"], issue["name"]) for issue in result["report_issues"] if issue["name"] == "Local"}
    assert missing == {(str(reports[0].resolve()), "Local")}
