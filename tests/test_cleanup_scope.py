"""Scratch queries are outside cleanup scope; actual metadata remains guarded."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan as plans
from semantic_model_cleaner.report_dax import DaxCoverageError, expression_references
from test_report_measure_delete import project, extension, operation


def fixture(tmp_path, kind):
    model, reports = project(tmp_path)
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tmeasure Spare = 42\n", encoding="utf-8")
    op = operation(reports[0], "Unused") if kind == "report" else {
        "kind": "actions", "actions": [
            {"action": "delete", "table": "Sales", "name": "Spare", "item_type": "Measure"}]}
    return model, reports, op


def query(root, content=b"\xff\xfe invalid scratch [Spare] [Unused]\r\n"):
    path = root / "DAXQueries/scratch.DAX"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize("kind", ["model", "report"])
@pytest.mark.parametrize("owner", ["model", "report"])
@pytest.mark.parametrize("content", [
    b"EVALUATE {[Spare], [Unused]}",
    b"DEFINE MEASURE Sales[Local] = [Spare] EVALUATE Sales",
    b"EVALUATE {SELECTEDMEASURE(), UnknownFunction()}",
    b"EVALUATE { [Missing] /* unfinished",
    b"\xff\xfe\x00 invalid encoding",
])
def test_queries_do_not_change_usage_coverage_or_eligibility(tmp_path, kind, owner, content):
    model, reports, op = fixture(tmp_path, kind)
    def analysis():
        a = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports)
        return a["coverage"], a["report_issues"], [
            (r["item"].table, r["item"].name, r["usage_status"], r["removal_risk"],
             r.get("report_measure_delete")) for r in a["items"]]
    baseline = analysis()
    path = query(model if owner == "model" else reports[0], content)
    assert analysis() == baseline
    plan = plans.create_plan(model, reports, [op])
    assert plan["changes"]
    assert not any(k.lower().endswith(".dax") for k in plan["inputs"])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert path.read_bytes() == content
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert path.read_bytes() == content


@pytest.mark.parametrize("kind", ["model", "report"])
@pytest.mark.parametrize("owner", ["model", "report"])
@pytest.mark.parametrize("drift", ["edit", "add", "delete"])
@pytest.mark.parametrize("when", ["preview", "before_apply", "after_apply"])
def test_query_inventory_changes_coexist_with_lifecycle(tmp_path, monkeypatch, kind, owner, drift, when):
    model, reports, op = fixture(tmp_path, kind)
    path = query(model if owner == "model" else reports[0])
    if drift == "add":
        path.unlink()
    roots = plans._roots(model, reports)
    before = plans._inventory(roots)

    def mutate():
        if drift == "delete":
            path.unlink()
        else:
            path.write_bytes(b"new developer bytes [Spare] [Unused]\r\n\xff")

    original = plans._analyze
    changed = False
    def inspect(staged, cache=None):
        nonlocal changed
        if staged["model"] != model:
            assert not any(p.suffix.lower() == ".dax" for root in staged.values() for p in root.rglob("*"))
        result = original(staged, cache)
        if when == "preview" and not changed:
            mutate()
            changed = True
        return result
    monkeypatch.setattr(plans, "_analyze", inspect)
    plan = plans.create_plan(model, reports, [op])
    if when == "before_apply":
        mutate()
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    if when == "after_apply":
        mutate()
    expected = path.read_bytes() if path.exists() else None
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert (path.read_bytes() if path.exists() else None) == expected
    assert plans._inventory(roots) == before
    assert plans.verify_plan(plan)["state"] == "original"


@pytest.mark.parametrize("kind", ["model", "report"])
def test_real_metadata_drift_still_blocks(tmp_path, kind):
    model, reports, op = fixture(tmp_path, kind)
    query(reports[0])
    plan = plans.create_plan(model, reports, [op])
    (reports[0] / "definition/report.json").write_text('{"changed": true}')
    before = plans._inventory(plans._roots(model, reports))
    with pytest.raises(plans.PlanError, match="Stale plan"):
        plans.apply_plan(plan, tmp_path / "journal")
    assert plans._inventory(plans._roots(model, reports)) == before


def test_retained_model_and_extension_dependencies_still_block(tmp_path):
    model, reports, op = fixture(tmp_path, "model")
    query(reports[0])
    source = model / "definition/tables/Sales.tmdl"
    source.write_text(source.read_text() + "\tmeasure Consumer = [Spare]\n")
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [op])
    extension(reports[0], [("Sales", "Leaf", "1"), ("Sales", "Top", "[Leaf]")])
    with pytest.raises(plans.PlanError, match="retained"):
        plans.create_plan(model, reports, [operation(reports[0], "Leaf")])
    assert plans.create_plan(model, reports, [operation(reports[0], "Leaf", "Top")])["changes"]


@pytest.mark.parametrize("surface", ["visual", "filter", "bookmark"])
def test_actual_report_metadata_reference_still_blocks(tmp_path, surface):
    model, reports, op = fixture(tmp_path, "report")
    query(reports[0])
    path = reports[0] / {
        "visual": "definition/pages/P/visuals/V/visual.json",
        "filter": "definition/report.json",
        "bookmark": "definition/bookmarks/B.bookmark.json",
    }[surface]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"opaque": {"Measure": {
        "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Unused"}}}))
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, reports, [op])


def test_report_expression_scanner_retains_static_and_dynamic_guards():
    assert expression_references("IF([A] > 0 || [B] > 0, 1, 0)") == [(None, "A"), (None, "B")]
    for text in ("[A] | [B]", "UnknownFunction()", "SELECTEDMEASURE()", "[A] /*"):
        with pytest.raises(DaxCoverageError):
            expression_references(text)

