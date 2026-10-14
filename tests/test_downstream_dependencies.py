"""Downstream closure uses scoped references, never mere ownership."""
from semantic_model_cleaner.analyzer import ModelItem, item_identity, scoped_dependency_graphs
from semantic_model_cleaner.dependency_view import DependencyView


def view(items, graphs=None):
    return DependencyView(items, graphs or scoped_dependency_graphs(items), item_identity)


def pairs(result):
    return {(r["name"], r["relationship"]) for r in result["measures"]}


def test_branch_chain_calculated_column_and_direct_wins():
    a = ModelItem("Column", "T", "A")
    items = [a, ModelItem("Calculated Column", "T", "X", dax_body="T[A]"),
             ModelItem("Measure", "M", "B", dax_body="SUM(T[A])"),
             ModelItem("Measure", "M", "C", dax_body="[B]"),
             ModelItem("Measure", "M", "D", dax_body="[C]"),
             ModelItem("Measure", "M", "E", dax_body="SUM(T[X])"),
             ModelItem("Measure", "M", "Both", dax_body="[D] + SUM(T[A])")]
    assert pairs(view(items).for_item(item_identity(a))) == {
        ("B", "Direct"), ("C", "Indirect"), ("D", "Indirect"),
        ("E", "Indirect"), ("Both", "Direct")}


def test_long_chain_and_cycle_are_complete_without_self():
    items = [ModelItem("Measure", "T", f"M{i}", dax_body=f"[M{i-1}]" if i else "[M150]") for i in range(151)]
    result = view(items).for_item(item_identity(items[0]))
    assert result["totalCount"] == 150
    assert ("M1", "Direct") in pairs(result)
    assert ("M150", "Indirect") in pairs(result)
    assert not any(r["name"] == "M0" for r in result["measures"])


def test_table_ownership_is_not_dependency_and_columns_are_seeds():
    items = [ModelItem("Column", "T", "A"),
             ModelItem("Measure", "T", "OwnedOnly", dax_body="1"),
             ModelItem("Measure", "Elsewhere", "TableRef", dax_body="COUNTROWS(T)"),
             ModelItem("Measure", "Elsewhere", "ColumnRef", dax_body="SUM(T[A])"),
             ModelItem("Measure", "Elsewhere", "Next", dax_body="[TableRef] + [ColumnRef]")]
    assert pairs(view(items).for_table("t")) == {
        ("TableRef", "Direct"), ("ColumnRef", "Direct"), ("Next", "Indirect")}


def test_report_scopes_are_deduplicated_by_identity_not_label():
    a = ModelItem("Column", "T", "A")
    items = [a] + [ModelItem("Measure", "T", "Local", dax_body="SUM(T[A])",
                           source_kind="report", source_file=path)
                   for path in ("one/reportExtensions.json", "two/reportExtensions.json")]
    result = view(items).for_item(item_identity(a))
    assert result["totalCount"] == 2
    assert len({r["sourceFile"] for r in result["measures"]}) == 2


def test_resolved_intermediate_metadata_edges_and_coverage_are_honest():
    items = [ModelItem("Column", "T", "A"), ModelItem("Measure", "T", "KPI"),
             ModelItem("Measure", "T", "Next", dax_body="[KPI]")]
    graphs = scoped_dependency_graphs(items)
    graphs["metadata"] = {item_identity(items[1]): {item_identity(items[0])}}
    graphs["broken"] = {item_identity(items[2]): ["Missing"]}
    d = DependencyView(items, graphs, item_identity, [{"unsupported": True}])
    result = d.for_item(item_identity(items[0]))
    assert pairs(result) == {("KPI", "Direct"), ("Next", "Indirect")}
    assert result["coverage"]["status"] == "supported-references"
    assert result["coverage"]["unresolvedCount"] == 1
    assert result["coverage"]["limitationCount"] == 1


def test_api_serializes_closure_without_changing_recommendations():
    from pathlib import Path
    from semantic_model_cleaner import analyzer, webapp
    workspace = Path(__file__).parents[1] / "src/semantic_model_cleaner/demo_workspace"
    result = analyzer.analyze(workspace)
    before = [(r["status"], r.get("removal_risk")) for r in result["items"]]
    payload = webapp._serialize_results(result)
    assert all("downstreamDependencies" in row for row in payload["items"])
    assert all("downstreamDependencies" in row for row in payload["tables"])
    assert before == [(r["status"], r.get("removal_risk")) for r in result["items"]]
