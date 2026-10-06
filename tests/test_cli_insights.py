"""Public read-query behavior over real synthetic PBIR/TMDL, not mocked verdicts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from semantic_model_cleaner import analyzer, ci, insights


ROOT = Path(__file__).parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def visual(report, page, table="Sales", name="Top", kind="Measure", stale=False):
    value = {"visual": {"visualType": "card", "query": {kind: {
        "Expression": {"SourceRef": {"Entity": table}}, "Property": name}}}}
    if stale:
        value["visual"]["objects"] = {"labels": [{"selector": {"metadata": "Sales.Spare"}}]}
    write_json(report / f"definition/pages/{page}/visuals/V/visual.json", value)
    write_json(report / f"definition/pages/{page}/page.json", {"name": page, "displayName": "Overview"})


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Zażółć project"
    model = root / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tcolumn Amount\n\tcolumn Label\n\t\tsortByColumn: Sort\n"
        "\tcolumn Sort\n\tcolumn Key\n\t\tisKey\n"
        "\tmeasure Base = SUM(Sales[Amount])\n\tmeasure Middle = [Base] * 2\n"
        "\tmeasure Top = [Middle] + 1\n\tmeasure Spare = 7\n"
        "\tmeasure Retained = 1\n\tmeasure IdleConsumer = [Retained]\n"
        "\tmeasure 'Zażółć 🚀' = 1\n", encoding="utf-8")
    (tables / "Other.tmdl").write_text(
        "table Other\n\tmeasure Top = COUNTROWS(Target)\n", encoding="utf-8")
    (tables / "Target.tmdl").write_text("table Target\n\tcolumn Id\n", encoding="utf-8")
    reports = []
    for parent in ("A", "B"):
        report = root / parent / "Same.Report"
        write_json(report / "definition.pbir", {"datasetReference": {"byPath": {"path": "../../M.SemanticModel"}}})
        write_json(report / "definition/report.json", {})
        visual(report, "P1", stale=True)
        reports.append(report)
    visual(reports[0], "P2", table="Other")
    return root, model, reports


def query(project, **selection):
    return insights.Insights(*insights.select_scope(project[0], **selection))


def run(args, *, cwd=None, code=0, json_output=True):
    result = subprocess.run([sys.executable, "-m", "semantic_model_cleaner", *map(str, args)],
                            cwd=cwd or ROOT, capture_output=True, timeout=40,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="0",
                                     PYTHONIOENCODING="cp1252:strict"))
    assert result.returncode == code, result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert b"Traceback" not in result.stderr
    if json_output:
        data = json.loads(result.stdout.decode("utf-8"))
        assert data["schema_version"] == "1.0" and data["command"] == args[0]
        return data
    return result.stdout.decode("utf-8")


def test_transitive_usage_preserves_report_and_page_identity(project):
    q = query(project)
    result = q.usage(table="Sales", item="Amount")
    assert result["used"] and result["report_used"]
    assert result["counts"]["reports"] == 2 and result["counts"]["pages"] == 2
    assert {row["report_path"] for row in result["locations"]["items"]} == {"A/Same.Report", "B/Same.Report"}
    assert all([item["name"] for item in row["via"]] == ["Top", "Middle", "Base"] for row in result["locations"]["items"])
    assert all(row["kind"] == "indirect" for row in result["locations"]["items"])
    # Both Reports and two same-named pages within A remain distinct.
    visual(project[2][0], "P2", name="Top")
    result = query(project).usage(table="Sales", item="Amount")
    assert result["counts"]["pages"] == 3
    assert {r["page_id"] for r in result["locations"]["items"]} == {"P1", "P2"}


def test_whole_table_and_bare_table_dax_dependency(project):
    q = query(project)
    result = q.usage(table="Target")
    assert result["report_used"] and result["cleanup"] == "Blocked"
    assert result["counts"]["reports"] == result["counts"]["pages"] == 1
    assert result["locations"]["items"][0]["kind"] == "indirect"
    assert result["locations"]["items"][0]["item"]["table"] == "Other"
    assert q.usage(table="Sales")["counts"]["reports"] == 2


def test_summary_counts_unique_items_instead_of_references(project):
    result = query(project).summary()
    a, b = result["reports"]["items"]
    assert a["direct_model_items"] == 2 and a["indirect_model_items"] == 3
    assert b["direct_model_items"] == 1 and b["indirect_model_items"] == 3
    assert a["tables"] == 3 and b["tables"] == 1
    target = next(t for t in result["tables"]["items"] if t["name"] == "Target")
    assert target["reports"] == 1 and target["items_used_by_reports"] == 0
    assert a["model_items"] == a["direct_model_items"] + a["indirect_model_items"]


def test_stale_references_are_not_live_and_retained_dependencies_are_explained(project):
    q = query(project)
    result = q.usage(table="Sales", item="Spare")
    assert not result["used"] and not result["report_used"]
    assert result["counts"]["live_locations"] == 0 and result["counts"]["stale_locations"] == 2
    required = q.usage(table="Sales", item="Retained")
    assert required["used"] and not required["report_used"]
    assert required["cleanup"] == "Blocked"
    assert required["dependents"]["items"][0]["name"] == "IdleConsumer"


def test_structural_uses_and_sort_column_locations(project):
    visual(project[2][0], "P2", name="Label", kind="Column")
    q = query(project)
    key = q.usage(table="Sales", item="Key")
    assert key["used"] and key["model_uses"]["items"][0]["reason"] == "Key column"
    sort = q.usage(table="Sales", item="Sort")
    assert sort["report_used"] and sort["counts"]["reports"] == 1
    assert any("Sort column" in row["reason"] for row in sort["model_uses"]["items"])


def test_same_named_local_measures_do_not_leak_between_reports(project):
    for report, expr in zip(project[2], ("[Base]", "[Spare]")):
        write_json(report / "definition/reportExtensions.json", {"entities": [{"name": "Sales", "measures": [
            {"name": "Local", "expression": expr}]}]})
    visual(project[2][0], "P1", name="Local")
    visual(project[2][1], "P1", name="Top", table="Other")
    q = query(project)
    with pytest.raises(insights.QueryError, match="Ambiguous"):
        q.usage(table="Sales", item="Local", source="report")
    assert q.usage(table="Sales", item="Base")["counts"]["reports"] == 1
    assert not q.usage(table="Sales", item="Spare")["report_used"]
    owned = query(project, reports=["B/Same.Report"]).usage(table="Sales", item="Local", source="report")
    assert not owned["report_used"] and owned["item"]["report_path"] == "B/Same.Report"


def test_cycles_terminate_and_keep_shortest_evidence_path(project):
    source = project[1] / "definition/tables/Sales.tmdl"
    with source.open("a", encoding="utf-8") as out:
        out.write("\n\tmeasure CycleA = [CycleB]\n\tmeasure CycleB = [CycleA] + [Base]\n")
    visual(project[2][0], "P1", name="CycleA")
    result = query(project).usage(table="Sales", item="CycleB")
    assert result["report_used"] and result["locations"]["total"] == 1
    assert [row["name"] for row in result["locations"]["items"][0]["via"]] == ["CycleA"]


def test_no_usage_with_incomplete_coverage_or_scope_stays_review(project):
    write_json(project[2][0] / "definition/report.json", {})
    (project[2][0] / "definition/report.json").write_text("{invalid", encoding="utf-8")
    result = query(project).usage(table="Sales", item="Spare")
    assert not result["scope"]["scan_complete"] and result["cleanup"] == "Review"
    assert result["limitations"]["total"]
    write_json(project[2][0] / "definition/report.json", {})
    selected = query(project, reports=["A/Same.Report"]).usage(table="Sales", item="Spare")
    assert not selected["scope"]["selection_complete"] and selected["cleanup"] == "Review"
    (project[0] / "Unknown.Report").mkdir()
    unknown = query(project).usage(table="Sales", item="Spare")
    assert unknown["scope"]["unverified_reports"] == 1 and unknown["cleanup"] == "Review"


def test_explicit_model_only_does_not_claim_report_usage_or_safe_candidates(project):
    result = query(project, model_only=True).usage(table="Sales", item="Spare")
    assert result["report_used"] is None and result["cleanup"] == "Review"
    assert not result["scope"]["scan_complete"]
    assert query(project, model_only=True).summary()["model"]["cleanup_candidates"] == 0
    # Existing analyzer and check still require Reports by default.
    with pytest.raises(SystemExit):
        analyzer.analyze(project[0], model_paths=[project[1]], report_paths=[])
    assert ci.run_check(project[0], report_paths=[])[0] == 2
    result = run(["review", project[0], "--model-only", "--format", "json"])
    assert not result["scope"]["report_usage_checked"]
    assert any(group["rule"] == "SMC002" for group in result["groups"])


def test_read_queries_are_bounded_unicode_safe_and_do_not_write_inputs(project, tmp_path):
    root = project[0]
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = run(["items", root, "--limit", "2", "--format", "json"], cwd=tmp_path)
    second = run(["items", root, "--limit", "2", "--offset", "2", "--format", "json"])
    assert len(first["items"]["items"]) == 2 and first["items"]["has_more"]
    assert first["items"]["items"] != second["items"]["items"]
    names = run(["items", root, "--search", "Zażółć", "--format", "json"])
    assert names["items"]["items"][0]["name"] == "Zażółć 🚀"
    usage = run(["usage", root, "--table", "Sales", "--item", "Base", "--limit", "1", "--format", "json"])
    assert usage["counts"]["reports"] == 2 and usage["locations"]["has_more"]
    summary = run(["summary", root, "--limit", "1", "--format", "json"])
    assert summary["reports"]["total"] == 2 and len(summary["reports"]["items"]) == 1
    text = run(["usage", root, "--table", "Sales", "--item", "Base"], json_output=False)
    assert "Used in 2 Report(s)" in text and "via Sales[Top] -> Sales[Middle]" in text
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_review_preserves_check_decisions_and_fingerprints(project):
    code, full = ci.run_check(project[0], fail_on="warning")
    result = run(["review", project[0], "--fail-on", "warning", "--limit", "1", "--format", "json"], code=code)
    assert result["ok"] == full["ok"]
    assert result["summary"] == full["summary"]
    assert result["findings"]["total"] == len(full["findings"])
    assert result["findings"]["items"][0]["fingerprint"] in {row["fingerprint"] for row in full["findings"]}
    text = run(["review", project[0], "--fail-on", "warning", "--limit", "1"], code=code, json_output=False)
    assert "SMC004" in text and "showing 1 of" in text


@pytest.mark.parametrize("args", [
    ["usage"], ["usage", "--item", "Top"], ["usage", "--item", "Missing"],
    ["usage", "--table", "Sales", "--type", "column"],
    ["usage", "--item", "Top", "--report", "missing.Report"],
    ["items", "--limit", "0"], ["items", "--limit", "1001"], ["items", "--offset", "-1"],
    ["summary", "--limit", "abc"], ["summary", "--model", "missing.SemanticModel"],
    ["items", "--unknown"], ["items", "--model-only", "--report", "A/Same.Report"],
])
def test_usage_and_parser_errors_are_machine_readable(project, args):
    result = run([args[0], project[0], *args[1:], "--format", "json"], code=2)
    assert not result["ok"] and result["errors"]


def test_capabilities_help_and_empty_search():
    result = run(["capabilities"])
    assert result["query_commands_read_only"] and result["tool_version"]
    assert result["operations_schema_version"] == "1.0"
    assert {"actions", "rename", "move", "dax"} <= set(result["operations"])
    assert result["schema_command"] == "smc operations-schema"
    assert result["plan_workflow_mutations"] == ["apply", "restore", "recover-lock"]
    assert {row["name"] for row in result["commands"]} == {"items", "usage", "summary", "review", "capabilities"}
    text = run(["--help"], json_output=False)
    assert "smc usage" in text and "smc summary" in text
    for command in ("items", "usage", "summary", "review", "capabilities"):
        assert "--format" in run([command, "--help"], json_output=False)


def test_demo_field_parameter_usage_is_distinct_from_direct_usage(tmp_path):
    root = tmp_path / "demo"
    shutil.copytree(ROOT / "src/semantic_model_cleaner/demo_workspace", root)
    result = query((root,)).usage(table="Sales", item="Revenue")
    assert result["report_used"]
    assert result["locations"]["items"][0]["kind"] == "field_parameter"


def test_hierarchy_column_usage_keeps_original_report_location(project):
    source = project[1] / "definition/tables/Sales.tmdl"
    with source.open("a", encoding="utf-8") as out:
        out.write("\n\thierarchy Geography\n\t\tlevel Place\n\t\t\tcolumn: Label\n")
    write_json(project[2][0] / "definition/pages/P2/visuals/V/visual.json", {"visual": {"query": {
        "HierarchyLevel": {"Level": "Place", "Expression": {"Hierarchy": {
            "Hierarchy": "Geography", "Expression": {"SourceRef": {"Entity": "Sales"}}}}}}}})
    result = query(project).usage(table="Sales", item="Label")
    assert result["report_used"] and result["counts"]["reports"] == 1
    assert result["locations"]["items"][0]["kind"] == "hierarchy"
    assert result["locations"]["items"][0]["page_id"] == "P2"
    assert query(project).summary()["reports"]["items"][0]["indirect_model_items"] == 5


def test_expression_is_opt_in_and_empty_tables_are_discoverable(project):
    q = query(project)
    assert "expression" not in q.usage(table="Sales", item="Base")
    assert "SUM(Sales[Amount])" in q.usage(table="Sales", item="Base", include_expression=True)["expression"]
    (project[1] / "definition/tables/Empty.tmdl").write_text("table Empty\n", encoding="utf-8")
    q = query(project)
    assert "Empty" in {r["name"] for r in q.items(item_type="table")["items"]["items"]}
    assert q.usage(table="Empty")["cleanup"] == "Review"
    assert q.summary()["model"]["tables"] == 4
    source = project[1] / "definition/tables/Other.tmdl"
    source.write_text("table Other\n\tmeasure Top = COUNTROWS(Empty)\n", encoding="utf-8")
    usage = query(project).usage(table="Empty")
    assert usage["report_used"] and usage["cleanup"] == "Blocked"
    assert usage["locations"]["items"][0]["item"]["table"] == "Other"


def test_empty_search_is_success_and_paths_are_project_relative(project, tmp_path):
    result = run(["items", project[0], "--search", "missing", "--format", "json"])
    assert result["ok"] and result["items"]["total"] == 0
    result = run(["usage", project[0], "--model", "M.SemanticModel", "--report", "A/Same.Report",
                  "--table", "Sales", "--item", "Base", "--format", "json"], cwd=tmp_path)
    assert result["counts"]["reports"] == 1
    assert result["scope"]["reports"] == ["A/Same.Report"]


def test_model_only_is_required_when_no_reports_exist(tmp_path):
    model = tmp_path / "M.SemanticModel/definition/tables"
    model.mkdir(parents=True)
    (model / "Sales.tmdl").write_text("table Sales\n\tmeasure Spare = 1\n", encoding="utf-8")
    result = run(["summary", tmp_path, "--format", "json"], code=2)
    assert "--model-only" in result["error"]
    result = run(["summary", tmp_path, "--model-only", "--format", "json"])
    assert result["model"]["measures"] == 1 and result["model"]["cleanup_candidates"] == 0


def test_field_parameter_evidence_keeps_hidden_flags():
    origin = analyzer.UsageRef("Parameter", "Choice", "Column", page_hidden=True, visual_hidden=True)
    parameter = analyzer.FieldParameterInfo("Parameter", Path("Parameter.tmdl"), [("Sales", "Base")])
    target = analyzer.ModelItem("Measure", "Sales", "Base")
    usages, _ = analyzer.promote_field_parameter_usages([origin], [(parameter, [target])])
    assert usages[0].page_hidden and usages[0].visual_hidden


def test_report_inventory_lists_transitive_items_and_tables(project):
    result = run(["items", project[0], "--report", "B/Same.Report", "--used-in-reports", "--format", "json"])
    assert {r["name"] for r in result["items"]["items"]} == {"Top", "Middle", "Base", "Amount"}
    result = run(["items", project[0], "--report", "A/Same.Report", "--used-in-reports", "--type", "table", "--format", "json"])
    assert {r["name"] for r in result["items"]["items"]} == {"Sales", "Other", "Target"}
    run(["items", project[0], "--model-only", "--used-in-reports", "--format", "json"], code=2)
