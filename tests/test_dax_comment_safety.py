"""Literal comment markers must never hide dependencies from cleanup review."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


EXPRESSIONS = [
    '"https://example.test" & [Revenue]',
    '"//" & [Revenue] // [CommentOnly]',
    '"say ""// [Literal]""" & [Revenue] // [CommentOnly]',
    '"/*" & [Revenue] /* [CommentOnly] */',
    '"/* text */" & [Revenue]',
    '"/* [Literal] */" & [Revenue]',
    'VAR s = "https://example.test"\nRETURN [Revenue] // [CommentOnly]',
    'VAR x = 1 RETURN [Revenue]',
    '[Revenue] -- [CommentOnly]',
    '[Revenue] /* [CommentOnly] */ + 0',
    '"Sales[Literal]" & [Revenue]',
]


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_comment_and_string_tokens_preserve_only_real_dependencies(expression):
    target = analyzer.ModelItem(item_type="Measure", table="Sales", name="Revenue", dax_body="1")
    source = analyzer.ModelItem(item_type="Measure", table="Sales", name="Label", dax_body=expression)
    graph = analyzer.build_dax_dependency_graph([target, source])
    assert graph[source.key] == {target.key}
    assert analyzer._extract_dax_unqualified_refs(expression) == {"Revenue"}
    assert analyzer._extract_dax_qualified_refs(expression) == set()
    assert analyzer.find_broken_dax_references([target, source]) == {}
    comments = analyzer.extract_dax_commented_refs(expression)
    assert "[Literal]" not in comments
    if "[CommentOnly]" in expression:
        assert "[CommentOnly]" in comments


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_cleanup_and_reviewed_plan_protect_dependency_after_literal_comment_marker(tmp_path, expression):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    source = model / "definition/tables/Sales.tmdl"
    source.parent.mkdir(parents=True)
    formula_lines = expression.splitlines()
    source.write_text("table Sales\n\tmeasure Revenue = 1\n\tmeasure Label = " + formula_lines[0]
                      + "".join("\n\t\t\t" + line for line in formula_lines[1:]) + "\n")
    visual = report / "definition/pages/P/visuals/V/visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text(json.dumps({"visual": {"query": {"Measure": {
        "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Label"}}}}))
    (report / "definition/report.json").write_text("{}")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    actions = [{"action": "delete", "table": "Sales", "name": "Revenue", "item_type": "Measure"}]
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    policy = evaluate_deletion_policy(model, [report], actions)
    assert not policy["ok"], policy
    assert any(v["rule_id"] == "SMC-D006" and "Label" in v["message"] for v in policy["violations"])
    with pytest.raises(change_plan.PlanError, match="Sales\\[Revenue\\]"):
        change_plan.create_plan(model, [report], [{"kind": "actions", "actions": actions}])
    assert change_plan._inventory(roots) == before


@pytest.mark.parametrize("table,name", [("Sales//Archive", "Revenue"), ("Sales/*Archive", "Revenue"),
                                        ("Sales'//Archive", "Revenue]//value")])
def test_comment_markers_inside_escaped_identifiers_preserve_qualified_refs(table, name):
    expression = "'" + table.replace("'", "''") + "'[" + name.replace("]", "]]") + "] // [CommentOnly]"
    target = analyzer.ModelItem(item_type="Measure", table=table, name=name, dax_body="1")
    source = analyzer.ModelItem(item_type="Measure", table="Measures", name="Label", dax_body=expression)
    assert analyzer._extract_dax_qualified_refs(expression) == {(table, name)}
    assert analyzer.build_dax_dependency_graph([target, source])[source.key] == {target.key}
    assert analyzer.extract_dax_commented_refs(expression) == {"[CommentOnly]"}
