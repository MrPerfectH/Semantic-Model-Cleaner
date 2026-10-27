"""Field parameters and calculation groups are retained or removed as whole units."""
import json

import pytest

from semantic_model_cleaner import analyzer, change_plan, webapp
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy

PICK_COLUMNS = ("Pick", "Pick Fields", "Pick Order", "Pick Name")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def project(tmp_path, *, sales_measures="", visuals=(), calc_item="SELECTEDMEASURE()", ordinal_sort=True):
    """A field parameter shaped like Power BI Desktop output, named without 'Parameter'."""
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tcolumn Amount\n\t\tdataType: int64\n"
        "\tmeasure A = SUM(Sales[Amount])\n\tmeasure B = 2\n\tmeasure Unrelated = 3\n"
        + sales_measures, encoding="utf-8")
    (tables / "Pick.tmdl").write_text(
        "table Pick\n"
        "\tmeasure 'Host Measure' = 1\n"
        "\tcolumn Pick\n\t\tsourceColumn: [Value1]\n\t\tsortByColumn: 'Pick Order'\n\n"
        "\t\trelatedColumnDetails\n\t\t\tgroupByColumn: 'Pick Fields'\n\n"
        "\tcolumn 'Pick Fields'\n\t\tisHidden\n\t\tsourceColumn: [Value2]\n\t\tsortByColumn: 'Pick Order'\n\n"
        "\t\textendedProperty ParameterMetadata =\n\t\t\t\t{\n\t\t\t\t  \"kind\": 2,\n\t\t\t\t  \"version\": 3\n\t\t\t\t}\n\n"
        "\tcolumn 'Pick Order'\n\t\tisHidden\n\t\tsourceColumn: [Value3]\n\n"
        "\tcolumn 'Pick Name'\n\t\tisHidden\n\t\tsourceColumn: [Value4]\n\n"
        "\tpartition Pick = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{\n"
        "\t\t\t\t    (\"A\", NAMEOF('Sales'[A]), 0, \"a\"),\n"
        "\t\t\t\t    (\"B\", NAMEOF('Sales'[B]), 1, \"b\")\n"
        "\t\t\t\t}\n", encoding="utf-8")
    (tables / "Time.tmdl").write_text(
        "table Time\n\tcalculationGroup\n\n"
        f"\t\tcalculationItem Current = {calc_item}\n\n"
        "\tcolumn Name\n\t\tdataType: string\n\t\tsourceColumn: Name\n"
        + ("\t\tsortByColumn: Ordinal\n" if ordinal_sort else "")
        + "\n\tcolumn Ordinal\n\t\tdataType: int64\n\t\tisHidden\n\t\tsourceColumn: Ordinal\n", encoding="utf-8")
    report = tmp_path / "R.Report"
    write_json(report / "definition.pbir", {"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}})
    write_json(report / "definition/report.json", {})
    for index, (table, name, kind) in enumerate(visuals):
        write_json(report / f"definition/pages/P/visuals/V{index}/visual.json", {"visual": {
            "visualType": "card", "query": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}}})
    if visuals:
        write_json(report / "definition/pages/P/page.json", {"name": "P", "displayName": "Page"})
    return model, report


def analyze(tmp_path, model, report):
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    return analysis, {row["item"].key: row for row in analysis["items"] if row["item"].source_kind == "model"}


def delete(table, name, item_type="Column"):
    return {"action": "delete", "table": table, "name": name, "item_type": item_type}


def assert_retained(rows, table, names):
    for name in names:
        row = rows[(table, name)]
        assert analyzer.is_used_status(row["usage_status"]), (name, row["usage_status"])
        assert row["removal_risk"] == "", (name, row["review_triggers"])


def test_report_use_of_display_column_retains_every_field_parameter_column(tmp_path):
    model, report = project(tmp_path, visuals=[("Pick", "Pick", "Column")])
    analysis, rows = analyze(tmp_path, model, report)
    assert rows[("Pick", "Pick")]["usage_status"] == "USED"
    assert_retained(rows, "Pick", PICK_COLUMNS)
    for name in ("Pick Fields", "Pick Name"):
        assert rows[("Pick", name)]["usage_status"] == "USED (Member of field parameter: Pick)"
        assert "Item is hidden" not in rows[("Pick", name)]["review_triggers"]
    # The NAMEOF targets keep their own field-parameter label.
    assert rows[("Sales", "A")]["usage_status"].startswith("USED (Field Parameter: Pick")
    # Ordinary measures are not members: neither the host measure nor unrelated ones.
    assert rows[("Pick", "Host Measure")]["usage_status"] == "NOT USED"
    assert rows[("Sales", "Unrelated")]["usage_status"] == "NOT USED"
    api = {(i["table"], i["name"]): i for i in webapp._serialize_results(analysis, model_paths=[model])["items"]}
    fields = api[("Pick", "Pick Fields")]
    assert fields["usageState"] == "Indirect" and fields["deleteSafety"] == "Blocked"
    assert "Field param member" in fields["otherModelUses"]
    assert api[("Pick", "Host Measure")]["deleteSafety"] == "Safe"


def test_report_use_of_hidden_helper_column_retains_display_column(tmp_path):
    model, report = project(tmp_path, visuals=[("Pick", "Pick Fields", "Column")])
    _, rows = analyze(tmp_path, model, report)
    assert_retained(rows, "Pick", PICK_COLUMNS)
    assert rows[("Pick", "Pick")]["usage_status"] == "USED (Member of field parameter: Pick)"


def test_model_evidence_retains_the_whole_field_parameter(tmp_path):
    model, report = project(tmp_path, sales_measures="\tmeasure Picked = SELECTEDVALUE(Pick[Pick Order])\n",
                            visuals=[("Sales", "Picked", "Measure")])
    _, rows = analyze(tmp_path, model, report)
    assert rows[("Pick", "Pick Order")]["usage_status"].startswith("INDIRECT (via: Sales[Picked]")
    assert_retained(rows, "Pick", PICK_COLUMNS)
    assert rows[("Pick", "Host Measure")]["usage_status"] == "NOT USED"


def test_parent_table_reference_blocks_the_unit_without_claiming_column_use(tmp_path):
    # A bare table reference needs the table, not a particular column (#83): the
    # columns stay unused, each is Review, and neither part nor whole can be deleted.
    model, report = project(tmp_path, sales_measures="\tmeasure Picked = COUNTROWS(Pick)\n",
                            visuals=[("Sales", "Picked", "Measure")])
    _, rows = analyze(tmp_path, model, report)
    for name in PICK_COLUMNS:
        row = rows[("Pick", name)]
        assert row["usage_status"] == "NOT USED" and row["removal_risk"] == "Review"
        assert any(t.startswith("Parent table 'Pick' is required by 1 retained DAX consumer")
                   for t in row["review_triggers"])
    assert not evaluate_deletion_policy(model, [report], [delete("Pick", "Pick")])["ok"]
    whole = evaluate_deletion_policy(model, [report], [delete("Pick", "", "Table")])
    assert any(v["rule_id"] == "SMC-D006" and "Table Pick is required by retained Sales[Picked]" in v["message"]
               for v in whole["violations"])


def test_report_use_of_one_calculation_group_column_retains_the_group(tmp_path):
    model, report = project(tmp_path, visuals=[("Time", "Name", "Column")], ordinal_sort=False)
    analysis, rows = analyze(tmp_path, model, report)
    assert_retained(rows, "Time", ("Name", "Ordinal"))
    assert rows[("Time", "Ordinal")]["usage_status"] == "USED (Member of calculation group: Time)"
    api = {(i["table"], i["name"]): i for i in webapp._serialize_results(analysis, model_paths=[model])["items"]}
    assert "Calc group member" in api[("Time", "Ordinal")]["otherModelUses"]
    assert api[("Time", "Ordinal")]["deleteSafety"] == "Blocked"


def test_model_reference_retains_the_calculation_group(tmp_path):
    model, report = project(tmp_path, sales_measures="\tmeasure Mode = SELECTEDVALUE(Time[Ordinal])\n",
                            visuals=[("Sales", "Mode", "Measure")])
    _, rows = analyze(tmp_path, model, report)
    assert_retained(rows, "Time", ("Name", "Ordinal"))
    assert rows[("Time", "Name")]["usage_status"] == "USED (Member of calculation group: Time)"


def test_wholly_unused_units_are_assessed_as_units_despite_internal_self_use(tmp_path):
    # Internal sort-by, groupBy and a calculation item naming its own column are not use.
    model, report = project(tmp_path, calc_item="IF(SELECTEDVALUE(Time[Name]) = \"x\", 1, SELECTEDMEASURE())")
    analysis, rows = analyze(tmp_path, model, report)
    for table, names in (("Pick", PICK_COLUMNS), ("Time", ("Name", "Ordinal"))):
        for name in names:
            row = rows[(table, name)]
            assert row["usage_status"] == "NOT USED"
            assert row["removal_risk"] == "Review" and row["review_basis"] == "entity_type", (name, row)
    # The visible display column is never individually Safe.
    assert rows[("Pick", "Pick")]["standalone_removal_risk"] == "Review"
    tables = {t["name"]: t for t in analysis["table_summaries"]}
    assert tables["Pick"]["cleanup_recommendation"] == "Review"
    assert tables["Pick"]["review_basis"] == "entity_type"


def test_unit_member_trigger_blocks_individual_safe_even_when_unit_not_wholly_unused(tmp_path):
    # An unused measure outside the unit still references a member, so the unit
    # is not wholly unused; its visible column must still not be Safe alone.
    model, report = project(tmp_path, sales_measures="\tmeasure Idle = SELECTEDVALUE(Pick[Pick Order])\n")
    _, rows = analyze(tmp_path, model, report)
    display = rows[("Pick", "Pick")]
    assert display["removal_risk"] == "Review"
    assert any(t.startswith("Column of field parameter 'Pick'") for t in display["review_triggers"])


@pytest.mark.parametrize("visuals", [(), [("Pick", "Pick", "Column")]])
@pytest.mark.parametrize("column", PICK_COLUMNS)
def test_deletion_plan_rejects_one_field_parameter_column(tmp_path, visuals, column):
    model, report = project(tmp_path, visuals=visuals)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    policy = evaluate_deletion_policy(model, [report], [delete("Pick", column)])
    assert not policy["ok"]
    assert any(v["rule_id"] == "SMC-D006" and "column of field parameter 'Pick'" in v["message"]
               for v in policy["violations"]), policy["violations"]
    with pytest.raises(change_plan.PlanError):
        change_plan.create_plan(model, [report], [{"kind": "actions", "actions": [delete("Pick", column)]}])
    assert change_plan._inventory(roots) == before


def test_deletion_plan_rejects_partial_calculation_group(tmp_path):
    model, report = project(tmp_path)
    policy = evaluate_deletion_policy(model, [report], [delete("Time", "Ordinal")])
    assert not policy["ok"]
    assert any(v["rule_id"] == "SMC-D006" and "column of calculation group 'Time'" in v["message"]
               for v in policy["violations"])


def test_all_columns_without_hosted_measure_is_still_partial(tmp_path):
    model, report = project(tmp_path)
    policy = evaluate_deletion_policy(model, [report], [delete("Pick", name) for name in PICK_COLUMNS])
    assert not policy["ok"]
    assert any(v["rule_id"] == "SMC-D006" and "deleted only as a whole table" in v["message"]
               for v in policy["violations"])


def test_wholly_unused_unit_deletes_as_a_whole_with_confirmation(tmp_path):
    model, report = project(tmp_path)
    policy = evaluate_deletion_policy(model, [report], [delete("Pick", "", "Table")])
    assert policy["ok"], policy["violations"]
    assert [c["table"] for c in policy["confirmations"]] == ["Pick"]
    assert evaluate_deletion_policy(model, [report], [delete("Time", "", "Table")])["ok"]


def test_used_unit_cannot_be_deleted_as_a_whole(tmp_path):
    model, report = project(tmp_path, visuals=[("Pick", "Pick", "Column")])
    policy = evaluate_deletion_policy(model, [report], [delete("Pick", "", "Table")])
    assert not policy["ok"]
    assert any(v["rule_id"] == "SMC-D004" and v["name"] == "Pick Fields" for v in policy["violations"])


def test_detection_uses_metadata_not_names(tmp_path):
    model, report = project(tmp_path)
    (model / "definition/tables/Parameter.tmdl").write_text(
        "table Parameter\n\tcolumn Parameter\n\tcolumn 'Parameter Fields'\n\t\tisHidden\n"
        "\tcolumn 'Parameter Order'\n", encoding="utf-8")
    _, rows = analyze(tmp_path, model, report)
    assert rows[("Parameter", "Parameter")]["removal_risk"] == "Safe"
    assert rows[("Parameter", "Parameter")]["structural_unit"] == ""
    assert rows[("Pick", "Pick")]["structural_unit"] == "field parameter"
    assert evaluate_deletion_policy(model, [report], [delete("Parameter", "Parameter Order")])["ok"]


# ── Engine-inferred member columns (isNameInferred) ──
# A custom field parameter shaped like PMRA 'FP Column Selection MP Errors': five
# columns, the fifth named by the engine (isNameInferred) and used as Group's sort
# column. The inferred flag is metadata, not usage, so the unit rules decide.
MP = "FP MP"
MP_COLUMNS = ("Pick", "Pick Fields", "Pick Order", "Group", "Value5")


def inferred_project(tmp_path, *, sales_measures="", visuals=(), ordinary_inferred=False):
    model, report = project(tmp_path, sales_measures=sales_measures, visuals=visuals)
    tables = model / "definition/tables"
    (tables / f"{MP}.tmdl").write_text(
        f"table '{MP}'\n"
        "\tcolumn Pick\n\t\tdataType: string\n\t\tsourceColumn: [Value1]\n\t\tsortByColumn: 'Pick Order'\n\n"
        "\t\trelatedColumnDetails\n\t\t\tgroupByColumn: 'Pick Fields'\n\n"
        "\tcolumn 'Pick Fields'\n\t\tdataType: string\n\t\tisHidden\n\t\tsourceColumn: [Value2]\n"
        "\t\tsortByColumn: 'Pick Order'\n\n"
        "\t\textendedProperty ParameterMetadata =\n\t\t\t\t{\n\t\t\t\t  \"kind\": 2,\n\t\t\t\t  \"version\": 3\n\t\t\t\t}\n\n"
        "\tcolumn 'Pick Order'\n\t\tdataType: int64\n\t\tisHidden\n\t\tsourceColumn: [Value3]\n\n"
        "\tcolumn Group\n\t\tdataType: string\n\t\tsourceColumn: [Value4]\n\t\tsortByColumn: Value5\n\n"
        "\tcolumn Value5\n\t\tdataType: int64\n\t\tisHidden\n\t\tisNameInferred\n\t\tsourceColumn: [Value5]\n\n"
        f"\tpartition '{MP} Raw' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{\n"
        "\t\t\t\t    (\"A\", NAMEOF('Sales'[A]), 1, \"Compact View\", 1),\n"
        "\t\t\t\t    (\"B\", NAMEOF('Sales'[B]), 1, \"Additional View\", 2)\n"
        "\t\t\t\t}\n", encoding="utf-8")
    if ordinary_inferred:
        (tables / "Plain.tmdl").write_text(
            "table Plain\n"
            "\tcolumn Value1\n\t\tdataType: int64\n\t\tisNameInferred\n\t\tsourceColumn: [Value1]\n\n"
            "\tpartition Plain = calculated\n\t\tmode: import\n\t\tsource = {1, 2}\n", encoding="utf-8")
    return model, report


def api_items(analysis, model):
    return {(i["table"], i["name"]): i for i in webapp._serialize_results(analysis, model_paths=[model])["items"]}


def test_inferred_member_does_not_stop_wholly_unused_unit_assessment(tmp_path):
    model, report = inferred_project(tmp_path)
    analysis, rows = analyze(tmp_path, model, report)
    for name in MP_COLUMNS:
        row = rows[(MP, name)]
        assert row["usage_status"] == "NOT USED", name
        assert row["removal_risk"] == "Review" and row["review_basis"] == "entity_type", (name, row["review_triggers"])
    assert rows[(MP, "Value5")]["item"].is_inferred
    tables = {t["name"]: t for t in analysis["table_summaries"]}
    assert tables[MP]["cleanup_recommendation"] == "Review" and tables[MP]["review_basis"] == "entity_type"
    api = api_items(analysis, model)
    assert api[(MP, "Value5")]["deleteSafety"] == "Review" and api[(MP, "Value5")]["isInferred"]


def test_inferred_member_unit_can_be_planned_only_as_a_whole_table(tmp_path):
    model, report = inferred_project(tmp_path)
    # The table hosts no measure, so deleting its five columns is the whole table.
    for whole in ([delete(MP, "", "Table")], [delete(MP, name) for name in MP_COLUMNS]):
        policy = evaluate_deletion_policy(model, [report], whole)
        assert policy["ok"], policy["violations"]
        assert [c["table"] for c in policy["confirmations"]] == [MP]
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    plan = change_plan.create_plan(model, [report], [{"kind": "actions", "actions": whole}])
    assert plan and change_plan._inventory(roots) == before
    for partial in ([delete(MP, "Value5")], [delete(MP, "Group")], [delete(MP, name) for name in MP_COLUMNS[:4]]):
        policy = evaluate_deletion_policy(model, [report], partial)
        assert not policy["ok"]
        assert any(v["rule_id"] == "SMC-D006" and f"column of field parameter '{MP}'" in v["message"]
                   for v in policy["violations"]), (partial, policy["violations"])


def test_used_sibling_retains_the_inferred_member(tmp_path):
    model, report = inferred_project(tmp_path, visuals=[(MP, "Pick", "Column")])
    analysis, rows = analyze(tmp_path, model, report)
    assert_retained(rows, MP, MP_COLUMNS)
    assert rows[(MP, "Value5")]["usage_status"] == f"USED (Member of field parameter: {MP})"
    api = api_items(analysis, model)
    assert api[(MP, "Value5")]["deleteSafety"] == "Blocked"
    policy = evaluate_deletion_policy(model, [report], [delete(MP, "", "Table")])
    assert not policy["ok"]
    assert any(v["rule_id"] == "SMC-D004" and v["name"] == "Value5" for v in policy["violations"])
    tables = {t["name"]: t for t in analysis["table_summaries"]}
    assert tables[MP]["cleanup_recommendation"] == "Blocked"


def test_ordinary_inferred_column_requires_whole_calculated_table_removal(tmp_path):
    model, report = inferred_project(tmp_path, ordinary_inferred=True)
    analysis, rows = analyze(tmp_path, model, report)
    row = rows[("Plain", "Value1")]
    assert row["structural_unit"] == "" and row["usage_status"] == "NOT USED"
    assert row["removal_risk"] == "Do not remove"
    assert api_items(analysis, model)[("Plain", "Value1")]["deleteSafety"] == "Keep"
    tables = {t["name"]: t for t in analysis["table_summaries"]}
    assert tables["Plain"]["cleanup_recommendation"] == "Blocked"
    single = evaluate_deletion_policy(model, [report], [delete("Plain", "Value1", "Column")])
    assert any(v["rule_id"] == "SMC-D004" and v["name"] == "Value1" for v in single["violations"])
    whole = evaluate_deletion_policy(model, [report], [delete("Plain", "", "Table")])
    assert whole['ok']


def test_genuine_limitation_on_inferred_member_still_blocks_the_unit(tmp_path):
    # An unresolved detail-rows expression outside the unit names Value5. That
    # coverage gap, not the inferred flag, keeps the unit out of a clean plan.
    model, report = inferred_project(tmp_path, sales_measures=(
        "\tmeasure Carrier = 1\n"
        f"\t\tdetailRowsDefinition = SELECTCOLUMNS(Sales, \"x\", '{MP}'[Value5], \"n\", SELECTEDMEASURENAME())\n"))
    _, rows = analyze(tmp_path, model, report)
    value5 = rows[(MP, "Value5")]
    assert value5["removal_risk"] == "Review" and value5["review_basis"] == "evidence"
    assert any(t.startswith("Referenced by the ") for t in value5["review_triggers"])
    policy = evaluate_deletion_policy(model, [report], [delete(MP, "", "Table")])
    assert not policy["ok"]
    assert not any(v["rule_id"] == "SMC-D004" for v in policy["violations"])


def test_idle_external_metadata_consumer_keeps_unit_out_of_entity_type_review(tmp_path):
    # A resolved detail-rows expression of an unused measure outside the unit is
    # a consumer: the unit is not wholly unused, and the plan keeps it.
    model, report = inferred_project(tmp_path, sales_measures=(
        "\tmeasure Carrier = 1\n"
        f"\t\tdetailRowsDefinition = SELECTCOLUMNS(Sales, \"x\", '{MP}'[Value5])\n"))
    _, rows = analyze(tmp_path, model, report)
    for name in MP_COLUMNS:
        assert rows[(MP, name)]["review_basis"] == "evidence", name
    assert any(t.startswith("Required by retained measure detail rows expression")
               for t in rows[(MP, "Value5")]["review_triggers"])
    policy = evaluate_deletion_policy(model, [report], [delete(MP, "", "Table")])
    assert any(v["rule_id"] == "SMC-D006" and "Sales'[Carrier]" in v["message"] for v in policy["violations"])
    together = evaluate_deletion_policy(model, [report], [delete(MP, "", "Table"), delete("Sales", "Carrier", "Measure")])
    assert together["ok"], together["violations"]
