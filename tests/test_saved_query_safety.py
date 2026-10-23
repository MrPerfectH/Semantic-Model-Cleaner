"""Round-three safety regressions; only synthetic DAX and metadata."""
import pytest

from semantic_model_cleaner import analyzer, change_plan as plans
from semantic_model_cleaner.saved_dax import query_references, DaxCoverageError
from test_report_measure_delete import project, extension, operation
from test_report_measure_coverage import query


def model_project(tmp_path, *, columns=True):
    model, reports = project(tmp_path)
    (model / "definition/tables/Sales.tmdl").write_text(
        "table Sales\n" + ("\tcolumn Amount\n" if columns else "")
        + "\tmeasure Revenue = 1\n", encoding="utf-8")
    (model / "definition/tables/Keep.tmdl").write_text("table Keep\n\tmeasure Keeper = 2\n", encoding="utf-8")
    for report in reports:
        extension(report, [("Sales", "Unused", "1")])
    return model, reports


def delete(name="Revenue", item_type="Measure"):
    return {"kind": "actions", "actions": [
        {"action": "delete", "table": "Sales", "name": name, "item_type": item_type}]}


@pytest.mark.parametrize("drift", ["modify", "add", "delete"])
def test_model_delete_saved_query_drift_blocks_before_write(tmp_path, drift):
    model, reports = model_project(tmp_path)
    path = query(reports[0], "EVALUATE {1}")
    if drift == "add":
        path.unlink()
    plan = plans.create_plan(model, [reports[0]], [delete()])
    if drift == "delete":
        path.unlink()
    else:
        query(reports[0], "EVALUATE {[Revenue]}")
    before = plans._inventory(plans._roots(model, [reports[0]]))
    with pytest.raises(plans.PlanError, match="Stale plan"):
        plans.apply_plan(plan, tmp_path / "journal")
    assert plans._inventory(plans._roots(model, [reports[0]])) == before
    assert not list((tmp_path / "journal").glob("*.json"))


def test_unchanged_query_staged_and_exact_lifecycle(tmp_path, monkeypatch):
    model, reports = model_project(tmp_path)
    path = query(reports[0], "EVALUATE {1}")
    roots = plans._roots(model, [reports[0]])
    before = plans._inventory(roots)
    original_analyze = plans._analyze
    staged_seen = []
    def inspect(staged):
        if staged["model"] != model:
            staged_seen.append((staged["report-1"] / "DAXQueries/query.dax").read_bytes())
        return original_analyze(staged)
    monkeypatch.setattr(plans, "_analyze", inspect)
    plan = plans.create_plan(model, [reports[0]], [delete()])
    assert staged_seen == [path.read_bytes()]
    assert "report-1/DAXQueries/query.dax" in plan["inputs"]
    assert all(not c["path"].endswith(".dax") for c in plan["changes"])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert plans._inventory(roots) == before
    assert path.read_text() == "EVALUATE {1}"


def test_unselected_query_does_not_drift_or_block_model_plan(tmp_path):
    model, reports = model_project(tmp_path)
    query(reports[1], "EVALUATE Sales")
    plan = plans.create_plan(model, [reports[0]], [delete()])
    query(reports[1], "EVALUATE {[Revenue]}")
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]


TABLE_QUERIES = [
    "EVALUATE Sales", "EVALUATE 'Sales'",
    "EVALUATE FILTER(Sales, Sales[Amount] > 0)",
    "EVALUATE FILTER('Sales', 'Sales'[Amount] > 0)",
    "EVALUATE ALL(Sales)", "EVALUATE VALUES('Sales')",
    "DEFINE VAR X = Sales EVALUATE X",
    "DEFINE VAR X = FILTER('Sales', [Revenue] > 0) VAR Y = X EVALUATE Y",
    "DEFINE VAR Sales = 'Sales' EVALUATE Sales",
    "EVALUATE VAR X = Sales RETURN X",
    "EVALUATE UnknownBinding", "EVALUATE { UnrecognizedSyntax }",
]


@pytest.mark.parametrize("text", TABLE_QUERIES)
def test_unresolved_table_binding_is_explicit_incomplete_coverage(text):
    with pytest.raises(DaxCoverageError, match="binding"):
        query_references(text)


@pytest.mark.parametrize("text", TABLE_QUERIES[:9])
@pytest.mark.parametrize("target", ["column", "last_item_table"])
def test_table_query_blocks_model_column_and_table_delete_plan(tmp_path, text, target):
    model, reports = model_project(tmp_path)
    if target == "last_item_table":
        (model / "definition/tables/Sales.tmdl").write_text("table Sales\n\tcolumn Amount\n")
        for report in reports:
            (report / "definition/reportExtensions.json").unlink()
    query(reports[0], text)
    before = plans._inventory(plans._roots(model, [reports[0]]))
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert not result["coverage"]["complete"]
    amount = next(r for r in result["items"] if r["item"].source_kind == "model" and r["item"].name == "Amount")
    assert amount["removal_risk"] != "Safe"
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [delete("Amount", "Column")])
    assert plans._inventory(plans._roots(model, [reports[0]])) == before


@pytest.mark.parametrize("text,expected", [
    ('DEFINE VAR Sales = {1} EVALUATE Sales', []),
    ('DEFINE VAR X = [Revenue] VAR Y = X EVALUATE ROW("v", Y)', [(None, "Revenue")]),
    ('DEFINE VAR X = [Revenue] MEASURE Sales[Local] = X EVALUATE {[Local]}', [(None, "Revenue")]),
    ('EVALUATE ROW("Sales FILTER(Sales) [Revenue]", 1) // Sales\n/* Sales */', []),
    ("EVALUATE {SUM('Sales'[Amount])}", [("Sales", "Amount")]),
])
def test_scalar_shadowing_and_external_bodies_remain_covered(text, expected):
    assert query_references(text) == expected


def test_table_binding_blocks_only_affected_report_extension(tmp_path):
    model, reports = model_project(tmp_path)
    query(reports[0], "EVALUATE Sales")
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [operation(reports[0], "Unused")])
    plan = plans.create_plan(model, reports, [operation(reports[1], "Unused")])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]



@pytest.mark.parametrize("drift", ["modify", "add", "delete"])
def test_saved_query_drift_during_prepare_blocks_plan(tmp_path, monkeypatch, drift):
    model, reports = model_project(tmp_path)
    path = query(reports[0], "EVALUATE {1}")
    if drift == "add":
        path.unlink()
    original_analyze = plans._analyze
    changed = False
    def race(roots):
        nonlocal changed
        result = original_analyze(roots)
        if not changed:
            changed = True
            if drift == "delete":
                path.unlink()
            else:
                query(reports[0], "EVALUATE {[Revenue]}")
        return result
    monkeypatch.setattr(plans, "_analyze", race)
    before = plans._inventory(plans._roots(model, [reports[0]]))
    with pytest.raises(plans.PlanError, match="Input changed"):
        plans.create_plan(model, [reports[0]], [delete()])
    assert plans._inventory(plans._roots(model, [reports[0]])) == before




@pytest.mark.parametrize("target", ["column", "last_item_table"])
def test_table_only_query_directly_rejects_delete_plan(tmp_path, target):
    model, reports = model_project(tmp_path)
    if target == "last_item_table":
        (model / "definition/tables/Sales.tmdl").write_text("table Sales\n\tcolumn Amount\n")
        for report in reports:
            (report / "definition/reportExtensions.json").unlink()
    query(reports[0], "EVALUATE Sales")
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [delete("Amount", "Column")])

@pytest.mark.parametrize("text", [
    "DEFINE MEASURE Sales[Local] = VAR Sales = {1} RETURN 1 EVALUATE Sales",
    "DEFINE MEASURE Sales[Local] = 1 VAR Sales = {1} EVALUATE Sales",
    "DEFINE VAR X = Sales VAR Sales = {1} EVALUATE X",
    "DEFINE VAR Sales = Sales EVALUATE Sales",
])
def test_ambiguous_or_forward_var_binding_fails_closed(text):
    with pytest.raises(DaxCoverageError, match="binding"):
        query_references(text)


def test_measure_local_var_cannot_shadow_model_table_at_evaluate(tmp_path):
    model, reports = model_project(tmp_path)
    query(reports[0], "DEFINE MEASURE Sales[Local] = VAR Sales = {1} RETURN 1 EVALUATE Sales")
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [delete("Amount", "Column")])

@pytest.mark.parametrize("text", [
    "DEFINE VAR X = VAR Sales = {1} RETURN 1 EVALUATE Sales",
    "DEFINE VAR X = 1 + VAR Sales = {1} RETURN 1 EVALUATE Sales",
])
def test_nested_var_body_does_not_export_table_shadow(text):
    with pytest.raises(DaxCoverageError, match="binding"):
        query_references(text)
