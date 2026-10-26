"""Desktop Top-N filters use a subquery alias as a table source; refactors resolve it."""
import json

import pytest

from semantic_model_cleaner import change_plan


def column(alias, name):
    return {"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": name}}


def top_n_filter(order_by_measure):
    """The exact shape Power BI Desktop writes for a Top 1 filter on Product[Name]."""
    inner_from = [{"Name": "p", "Entity": "Product", "Type": 0}]
    order = {"Aggregation": {"Expression": column("p", "Name"), "Function": 3}}
    if order_by_measure:
        inner_from.append({"Name": "s", "Entity": "Sales", "Type": 0})
        order = {"Measure": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": "Revenue"}}
    return {
        "name": "topn", "type": "TopN",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Product"}}, "Property": "Name"}},
        "filter": {"Version": 2, "From": [
            {"Name": "subquery", "Type": 2, "Expression": {"Subquery": {"Query": {
                "Version": 2, "From": inner_from,
                "Select": [{**column("p", "Name"), "Name": "field"}],
                "OrderBy": [{"Direction": 2, "Expression": order}], "Top": 1}}}},
            {"Name": "p", "Entity": "Product", "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [column("p", "Name")],
                                             "Table": {"SourceRef": {"Source": "subquery"}}}}}]},
    }


def project(tmp_path, order_by_measure):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text("table Sales\n\tcolumn Amount\n\tmeasure Revenue = SUM(Sales[Amount])\n"
                                       "\tmeasure Spare = 1\n", encoding="utf-8")
    (tables / "Product.tmdl").write_text("table Product\n\tcolumn Name\n", encoding="utf-8")
    (tables / "Measures.tmdl").write_text("table Measures\n\tmeasure Constant = 1\n", encoding="utf-8")
    visual = report / "definition/pages/P/visuals/V/visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({"visual": {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": [
        {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Product"}}, "Property": "Name"}}},
        {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Revenue"}}},
    ]}}}}, "filterConfig": {"filters": [top_n_filter(order_by_measure)]}}), encoding="utf-8")
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}),
                                            encoding="utf-8")
    return model, report, visual


def planned_filter(plan, visual_key="report-1/definition/pages/P/visuals/V/visual.json"):
    change = next(c for c in plan["changes"] if c["path"] == visual_key)
    return json.loads(change_plan._decoded(change["after"]))["filterConfig"]["filters"][0]


OPERATIONS = {
    "move": {"kind": "move", "moves": [{"table": "Sales", "name": "Revenue", "target_table": "Measures"}]},
    "rename_measure": {"kind": "rename", "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}]},
    "rename_table": {"kind": "rename", "table_renames": [{"table": "Product", "target_table": "Products"}]},
    "rename_column": {"kind": "rename", "column_renames": [{"table": "Product", "name": "Name", "target_name": "Product Name"}]},
}


@pytest.mark.parametrize("kind", ["move", "rename_measure"])
def test_refactor_of_an_unrelated_item_leaves_the_subquery_filter_untouched(tmp_path, kind):
    model, report, visual = project(tmp_path, order_by_measure=False)
    before = top_n_filter(order_by_measure=False)
    plan = change_plan.create_plan(model, [report], [OPERATIONS[kind]])
    assert planned_filter(plan) == before
    assert change_plan.apply_plan(plan, tmp_path / "journal")["ok"]


@pytest.mark.parametrize("kind", ["move", "rename_measure"])
def test_refactor_rewrites_the_item_ordered_inside_the_subquery(tmp_path, kind):
    model, report, visual = project(tmp_path, order_by_measure=True)
    plan = change_plan.create_plan(model, [report], [OPERATIONS[kind]])
    query = planned_filter(plan)["filter"]["From"][0]["Expression"]["Subquery"]["Query"]
    measure = query["OrderBy"][0]["Expression"]["Measure"]
    sources = {source["Name"]: source["Entity"] for source in query["From"]}
    if kind == "move":
        assert sources == {"p": "Product", "s": "Measures"} and measure["Property"] == "Revenue"
    else:
        assert sources == {"p": "Product", "s": "Sales"} and measure["Property"] == "Net Revenue"
    assert planned_filter(plan)["filter"]["Where"][0]["Condition"]["In"]["Table"] == {"SourceRef": {"Source": "subquery"}}


@pytest.mark.parametrize("order_by_measure", [False, True])
def test_renaming_the_filtered_entity_rewrites_inside_and_outside_the_subquery(tmp_path, order_by_measure):
    model, report, visual = project(tmp_path, order_by_measure)
    plan = change_plan.create_plan(model, [report], [OPERATIONS["rename_table"]])
    rewritten = planned_filter(plan)
    outer = rewritten["filter"]
    inner = outer["From"][0]["Expression"]["Subquery"]["Query"]
    assert outer["From"][1]["Entity"] == "Products" and inner["From"][0]["Entity"] == "Products"
    assert rewritten["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Products"
    assert outer["Where"][0]["Condition"]["In"]["Table"] == {"SourceRef": {"Source": "subquery"}}
    assert change_plan.apply_plan(plan, tmp_path / "journal")["ok"]


def test_renaming_the_filtered_column_rewrites_every_subquery_reference(tmp_path):
    model, report, visual = project(tmp_path, order_by_measure=False)
    plan = change_plan.create_plan(model, [report], [OPERATIONS["rename_column"]])
    outer = planned_filter(plan)["filter"]
    inner = outer["From"][0]["Expression"]["Subquery"]["Query"]
    assert inner["Select"][0]["Column"]["Property"] == "Product Name"
    assert inner["Select"][0]["Name"] == "field"
    assert inner["OrderBy"][0]["Expression"]["Aggregation"]["Expression"]["Column"]["Property"] == "Product Name"
    assert outer["Where"][0]["Condition"]["In"]["Expressions"][0]["Column"]["Property"] == "Product Name"


def test_a_source_without_entity_or_subquery_still_refuses_a_rewrite_it_would_need(tmp_path):
    model, report, visual = project(tmp_path, order_by_measure=True)
    payload = json.loads(visual.read_text(encoding="utf-8"))
    query = payload["filterConfig"]["filters"][0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]
    query["From"][1] = {"Name": "s", "Expression": {"Unknown": {}}, "Type": 0}
    visual.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(change_plan.PlanError, match="Cannot resolve query alias 's'"):
        change_plan.create_plan(model, [report], [OPERATIONS["move"]])
