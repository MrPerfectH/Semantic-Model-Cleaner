"""Synthetic saved-query scope and schema proofs (no private query content)."""
import pytest

from semantic_model_cleaner import analyzer, change_plan as plans
from semantic_model_cleaner.saved_dax import DaxCoverageError, query_references
from test_report_measure_coverage import query
from test_saved_query_safety import model_project, delete


@pytest.mark.parametrize("text,required", [
    ("EVALUATE Sales", {("Sales", None)}),
    ("EVALUATE 'Sales'", {("Sales", None)}),
    ("EVALUATE TOPN(10, 'Sales')", {("Sales", None)}),
    ("DEFINE VAR T = Sales VAR U = FILTER(T, Sales[Amount] > 0) EVALUATE U",
     {("Sales", None), ("Sales", "Amount")}),
    ("EVALUATE VAR T = Sales RETURN VAR U = T RETURN U", {("Sales", None)}),
    ("EVALUATE VAR T = Sales RETURN (VAR T = Keep RETURN T)",
     {("Sales", None), ("Keep", None)}),
    ("DEFINE MEASURE Sales[X] = (VAR A = [Revenue] RETURN VAR B = A RETURN B) "
     "VAR T = {1} EVALUATE T", {("Sales", None), (None, "Revenue")}),
    ('EVALUATE ROW("Result", SUMX(ADDCOLUMNS(Sales, "V", Sales[Amount]), [V]))',
     {("Sales", None), ("Sales", "Amount")}),
    ('DEFINE VAR T = SELECTCOLUMNS(Sales, "V", Sales[Amount]) VAR U = T '
     'EVALUATE FILTER(U, [V] > 0) ORDER BY [V]', {("Sales", None), ("Sales", "Amount")}),
    ('EVALUATE ADDCOLUMNS(ADDCOLUMNS(Sales, "V", Sales[Amount]), "W", [V]) ORDER BY [W]',
     {("Sales", None), ("Sales", "Amount")}),
    ('DEFINE VAR T = SUMMARIZECOLUMNS(Sales[Amount], "V", [Revenue]) '
     'VAR U = TOPN(2, T, [V]) EVALUATE U ORDER BY [V]',
     {("Sales", "Amount"), (None, "Revenue")}),
    ('DEFINE VAR T = SUMMARIZECOLUMNS(Sales[Amount], "V", [Revenue]) '
     'VAR K = SUMMARIZE(T, Sales[Amount]) '
     'VAR J = NATURALLEFTOUTERJOIN(K, SUBSTITUTEWITHINDEX(T, "I", K, Sales[Amount], ASC)) '
     'EVALUATE K ORDER BY Sales[Amount] EVALUATE J ORDER BY [I]',
     {("Sales", "Amount"), (None, "Revenue")}),
    ('DEFINE VAR T = SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Sales[Amount], "Total"), "V", [Revenue]) '
     'EVALUATE ADDMISSINGITEMS(Sales[Amount], T, ROLLUPISSUBTOTAL(Sales[Amount], [Total])) '
     'ORDER BY [Total]', {("Sales", "Amount"), (None, "Revenue")}),
    ('EVALUATE ROW("Sales [Absent] VAR X", 1) // EVALUATE Ghost\n/* [Unknown] */', set()),
])
def test_bounded_bindings(text, required):
    assert required <= set(query_references(text))


@pytest.mark.parametrize("text", [
    'EVALUATE VAR A = A RETURN A',
    'DEFINE VAR A = B VAR B = {1} EVALUATE A',
    'EVALUATE VAR A = 1',
    'EVALUATE VAR A = 1 VAR A = 2 RETURN A',
    'EVALUATE SUMX(ADDCOLUMNS(Sales, "V", 1, "V", 2), [V])',
    'EVALUATE FILTER(CROSSJOIN(ROW("V", 1), ROW("V", 2)), [V] > 0)',
    'EVALUATE SUMX(ArbitraryFunction(Sales), [V])',
    'EVALUATE {SELECTEDMEASURE()}',
    'DEFINE TABLE X = Sales EVALUATE X',
    'DEFINE MEASURE Sales[V] = 1 EVALUATE SUMX(ROW("V", 2), [V])',
    'EVALUATE SUMX(GENERATESERIES(1, 3), [Value])',
])
def test_unproven_binding_fails_closed(text):
    with pytest.raises(DaxCoverageError):
        query_references(text)


@pytest.mark.parametrize("text", [
    "EVALUATE UnknownBinding",
    "EVALUATE {[Unknown]}",
    "EVALUATE {Missing[Amount]}",
    'EVALUATE SUMX(ROW("V", 1), [Missing])',
    'DEFINE VAR T = ROW("V", 1) EVALUATE ROW("W", [V])',
    'EVALUATE ROW("V", 1) EVALUATE {1} ORDER BY [V]',
    'EVALUATE SUMX(ADDCOLUMNS(Sales, "V", 1, "W", [V]), [W])',
    'DEFINE VAR T = Sales EVALUATE T[Amount]',
    'EVALUATE SUMX(ROW("Revenue", 1), [Revenue])',
])
def test_unknown_and_scope_leak_block_model_cleanup(tmp_path, text):
    model, reports = model_project(tmp_path)
    query(reports[0], text)
    a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert not a["coverage"]["complete"]
    assert any(v["kind"] == "unsupported_saved_dax_query" for v in a["coverage"]["limitations"])
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [delete()])


@pytest.mark.parametrize("text", [
    "EVALUATE Sales",
    "EVALUATE 'Sales'",
    "EVALUATE VAR T = Sales RETURN T",
    "DEFINE VAR T = Sales VAR U = T EVALUATE U",
    'EVALUATE ROW("Result", SUMX(ADDCOLUMNS(Sales, "V", 1), [V]))',
])
def test_whole_table_last_measure_negative_and_independent_positive(tmp_path, text):
    model, reports = model_project(tmp_path, columns=False)
    query(reports[0], text)
    a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert a["coverage"]["complete"]
    sales = next(r for r in a["items"] if r["item"].source_kind == "model" and r["item"].table == "Sales")
    assert sales["removal_risk"] != "Safe"
    before = plans._inventory(plans._roots(model, reports))
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [delete()])
    assert plans._inventory(plans._roots(model, reports)) == before


def test_supported_virtual_query_exact_lifecycle_and_scope(tmp_path):
    model, reports = model_project(tmp_path)
    (model / "definition/tables/Keep.tmdl").write_text("table Keep\n\tmeasure Keeper = 2\n\tmeasure Spare = 3\n")
    query(reports[0], 'DEFINE VAR T = SELECTCOLUMNS(Sales, "V", Sales[Amount]) '
          'VAR U = TOPN(2, T, [V]) EVALUATE U ORDER BY [V]')
    before = plans._inventory(plans._roots(model, reports))
    op = {"kind": "actions", "actions": [{"action": "delete", "table": "Keep", "name": "Spare", "item_type": "Measure"}]}
    plan = plans.create_plan(model, reports, [op])
    assert any(k.lower().endswith(".dax") for k in plan["inputs"])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert plans._inventory(plans._roots(model, reports)) == before


def test_ambiguous_external_column_fails_closed(tmp_path):
    model, reports = model_project(tmp_path)
    (model / "definition/tables/Keep.tmdl").write_text("table Keep\n\tcolumn Amount\n\tmeasure Keeper = 2\n")
    query(reports[0], "EVALUATE {[Amount]}")
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert not result["coverage"]["complete"]
    assert any("Ambiguous external object binding" in x["message"] for x in result["coverage"]["limitations"])


def test_deep_binding_is_explicit_limitation():
    with pytest.raises(DaxCoverageError, match="nesting"):
        query_references("EVALUATE " + "(" * 1500 + "{1}" + ")" * 1500)


def test_unknown_output_schema_cannot_resolve_order_alias_as_model():
    with pytest.raises(DaxCoverageError, match="output schema"):
        query_references("EVALUATE GENERATESERIES(1, 2) ORDER BY [Value]")


def test_unmodeled_tuple_schema_fails_closed():
    with pytest.raises(DaxCoverageError, match="tuple binding"):
        query_references('EVALUATE {(1, 2)} ORDER BY [Value]')


def test_existing_missing_define_owner_cannot_mask_new_missing_owner(tmp_path):
    model, reports = model_project(tmp_path)
    query(reports[0], "DEFINE MEASURE Missing[A] = 1 MEASURE Sales[B] = 2 EVALUATE {1}")
    with pytest.raises(plans.PlanError, match="complete supported scan coverage"):
        plans.create_plan(model, [reports[0]], [{"kind": "rename", "table_renames": [
            {"table": "Sales", "target_table": "Renamed"}]}])


def test_uppercase_saved_query_keeps_whole_table(tmp_path):
    model, reports = model_project(tmp_path)
    path = query(reports[0], "EVALUATE Sales")
    path.rename(path.with_suffix(".DAX"))
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert result["coverage"]["complete"]
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [delete("Amount", "Column")])
