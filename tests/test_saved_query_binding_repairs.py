"""Public synthetic regressions for argument scope and generated format coverage."""
import pytest

from semantic_model_cleaner import analyzer, change_plan as plans
from semantic_model_cleaner.saved_dax import DaxBindingError, DaxCoverageError, query_references
from test_report_measure_coverage import query
from test_report_measure_delete import extension
from test_saved_query_safety import model_project


RANK = 'EVALUATE ROW("Rank", RANKX(VALUES(Sales[Amount]), Sales[Amount], [Amount]))'


def action(table, name):
    return {"kind": "actions", "actions": [
        {"action": "delete", "table": table, "name": name, "item_type": "Measure"}]}


@pytest.mark.parametrize("report_measure", [False, True])
@pytest.mark.parametrize("last", [False, True])
def test_rankx_value_collision_blocks_model_and_report_deletion(tmp_path, report_measure, last):
    model, reports = model_project(tmp_path)
    keep = model / "definition/tables/Keep.tmdl"
    keep.write_text("table Keep\n" + ("\tmeasure Keeper = 2\n" if report_measure or not last else "")
                    + ("" if report_measure else "\tmeasure Amount = 42\n"))
    if report_measure:
        extension(reports[0], [("Keep", "Amount", "42")] + ([] if last else [("Keep", "Spare", "3")]))
        op = {"kind": "delete_report_measures", "entries": [
            {"report_path": str(reports[0]), "table": "Keep", "name": "Amount"}]}
    else:
        op = action("Keep", "Amount")
    query(reports[0], RANK)
    roots = plans._roots(model, [reports[0]])
    before = plans._inventory(roots)
    a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    # A same-name external column/measure collision may fail closed; it must
    # never make a required item Safe or report-group eligible.
    row = next(r for r in a["items"] if r["item"].table == "Keep" and r["item"].name == "Amount")
    if report_measure:
        assert not row["report_measure_delete"]["groupEligible"]
    else:
        assert row["removal_risk"] != "Safe"
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [op])
    assert plans._inventory(roots) == before


@pytest.mark.parametrize("text", [
    RANK,
    'EVALUATE ROW("R", SUMX(VALUES(Sales[Amount]), [Amount]))',
])
def test_native_row_column_measure_collision_is_conservative(text):
    items = [analyzer.ModelItem("Column", "Sales", "Amount"),
             analyzer.ModelItem("Measure", "Keep", "Amount")]
    with pytest.raises(DaxCoverageError, match="Ambiguous"):
        query_references(text, items=items)


@pytest.mark.parametrize("text", [
    'EVALUATE ROW("R", RANKX(ROW("X", 1), [X], [X]))',
    'EVALUATE ROW("R", CONCATENATEX(ROW("X", 1), [X], [X]))',
    'EVALUATE TOPN(1, ROW("X", 1), [X], [X])',
    'EVALUATE ROW("R", MINX(ROW("X", 1), [X], [X]))',
    'EVALUATE ROW("R", MAXX(ROW("X", 1), [X], [X]))',
    'EVALUATE SUBSTITUTEWITHINDEX(ROW("X", 1), "I", ROW("X", 1), [X], [X])',
])
def test_non_iterated_arguments_do_not_inherit_function_row(text):
    assert (None, "X") in query_references(text)


def test_rankx_keeps_nested_caller_row_and_expression_row_separate():
    text = ('EVALUATE ADDCOLUMNS(ROW("Outer", 2), "R", '
            'RANKX(ROW("Inner", 1), [Inner], [Outer]))')
    assert query_references(text, items=[]) == []
    with pytest.raises(DaxBindingError):
        query_references(text.replace('[Outer]', '[Inner]'), items=[])


@pytest.mark.parametrize("report_measure", [False, True])
def test_qualified_rankx_value_retained_and_spare_staged_lifecycle(tmp_path, monkeypatch, report_measure):
    model, reports = model_project(tmp_path)
    (model / "definition/tables/Keep.tmdl").write_text(
        "table Keep\n\tmeasure Keeper = 2\n"
        + ("" if report_measure else "\tmeasure Spare = 3\n\tmeasure Amount = 42\n"))
    if report_measure:
        extension(reports[0], [("Keep", "Amount", "42"), ("Keep", "Spare", "3")])
    text = RANK.replace(', [Amount]', ', Keep[Amount]')
    path = query(reports[0], text)
    roots = plans._roots(model, [reports[0]])
    before = plans._inventory(roots)
    a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert a["coverage"]["complete"]
    def op(name):
        return ({"kind": "delete_report_measures", "entries": [
            {"report_path": str(reports[0]), "table": "Keep", "name": name}]}
            if report_measure else action("Keep", name))
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [op("Amount")])
    seen = []
    original = plans._analyze
    def staged(scope, cache=None):
        if scope["model"] != model:
            seen.append((scope["report-1"] / "DAXQueries/query.dax").read_bytes())
        return original(scope, cache)
    monkeypatch.setattr(plans, "_analyze", staged)
    plan = plans.create_plan(model, [reports[0]], [op("Spare")])
    assert seen and all(v == path.read_bytes() for v in seen)
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert plans._inventory(roots) == before


@pytest.mark.parametrize("qualified", [False, True])
def test_native_dynamic_format_helper_is_unsupported_not_missing(qualified):
    owner = analyzer.ModelItem("Measure", "Sales", "Revenue", format_string_expression='"0.00"')
    ref = ('Sales' if qualified else '') + '[_Revenue FormatString]'
    with pytest.raises(DaxCoverageError, match="Unsupported generated dynamic-format binding") as caught:
        query_references('EVALUATE {' + ref + '}', items=[owner])
    assert not isinstance(caught.value, DaxBindingError)
    assert "Unresolved object" not in str(caught.value)


@pytest.mark.parametrize("items,ref", [
    ([], 'Sales[_Revenue FormatString]'),
    ([analyzer.ModelItem("Measure", "Sales", "Revenue", format_string="0.00")], 'Sales[_Revenue FormatString]'),
    ([analyzer.ModelItem("Measure", "Sales", "Revenue", format_string_expression='"0"')], 'Keep[_Revenue FormatString]'),
    ([analyzer.ModelItem("Measure", "Sales", "Revenue", source_kind="report", format_string_expression='"0"')], 'Sales[_Revenue FormatString]'),
])
def test_suffix_without_exact_native_format_owner_remains_missing(items, ref):
    with pytest.raises(DaxBindingError, match="Unresolved object"):
        query_references('EVALUATE {' + ref + '}', items=items)


def test_persisted_helper_and_query_local_identity_are_not_generated():
    owner = analyzer.ModelItem("Measure", "Sales", "Revenue", format_string_expression='"0"')
    helper = analyzer.ModelItem("Measure", "Sales", "_Revenue FormatString")
    assert query_references('EVALUATE {Sales[_Revenue FormatString]}', items=[owner, helper]) == [
        ("Sales", "_Revenue FormatString")]
    assert (None, "_Revenue FormatString") not in query_references(
        'DEFINE MEASURE Sales[_Revenue FormatString] = 1 EVALUATE {[_Revenue FormatString]}', items=[owner])
    with pytest.raises(DaxBindingError, match="Ambiguous external"):
        query_references('EVALUATE {Sales[_Revenue FormatString]}', items=[
            owner, helper, analyzer.ModelItem("Measure", "Sales", "_Revenue FormatString", source_kind="report")])


def test_generated_helper_blocks_model_and_report_cleanup_with_accurate_issue(tmp_path):
    model, reports = model_project(tmp_path)
    p = model / "definition/tables/Sales.tmdl"
    p.write_text('table Sales\n\tcolumn Amount\n\tmeasure Revenue = 1\n'
                 '\t\tformatStringDefinition = "0.00"\n')
    query(reports[0], 'EVALUATE {Sales[_Revenue FormatString]}')
    a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    assert not a["coverage"]["complete"]
    issues = [i for i in a["report_issues"] if i["issueType"] == "unsupported_saved_dax_query"]
    assert issues and all(i["severity"] == "warning" for i in issues)
    assert all("Unsupported generated dynamic-format binding" in i["message"] for i in issues)
    for op in [action("Keep", "Keeper"), {"kind": "delete_report_measures", "entries": [
            {"report_path": str(reports[0]), "table": "Sales", "name": "Unused"}]}]:
        with pytest.raises(plans.PlanError):
            plans.create_plan(model, [reports[0]], [op])
    # An unselected report does not supply or block this selected report's bindings.
    query(reports[1], 'EVALUATE {1}')
    assert plans.create_plan(model, [reports[1]], [action("Keep", "Keeper")])
