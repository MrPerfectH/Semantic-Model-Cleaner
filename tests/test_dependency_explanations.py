"""Declaration-based feature detection, dependency explanations and analysis limitations.

Covers GitHub issues #82 (detect features from TMDL declarations), #83 (explain
calculation-group and perspective dependencies) and #84 (separate analysis
limitations from Report Health). The synthetic fixture has a calculation group
with ten retained parent-table consumers, a table named `KPI Selector` that
declares no KPI, a genuine KPI, and perspective membership.
"""
import json
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, ci, webapp
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy
from semantic_model_cleaner.tmdl_declarations import (
    extract_feature_expressions,
    extract_perspective_members,
    scan_tmdl_declarations,
)

FIXTURE = Path(__file__).parent / "fixtures" / "calculation_group_dependencies"
MODEL = FIXTURE / "Models" / "Synthetic Dependencies.SemanticModel"
REPORT = FIXTURE / "Reports" / "Executive.Report"
CONSUMERS = [f"Sales[Revenue Ignoring TI {n:02d}]" for n in range(1, 11)]


@pytest.fixture(scope="module")
def results():
    return analyzer.analyze(FIXTURE, model_paths=[MODEL], report_paths=[REPORT])


@pytest.fixture(scope="module")
def payload(results):
    return webapp._serialize_results(results, model_paths=[str(MODEL)])


def row(results, table, name):
    return next(r for r in results["items"] if r["item"].table == table and r["item"].name == name)


def item(payload, table, name):
    return next(i for i in payload["items"] if i["table"] == table and i["name"] == name)


# ── #82: detection from declarations, not words ──────────────────────────────

@pytest.mark.parametrize("text", [
    "table 'KPI Selector'\n\tcolumn Name\n\t\tdataType: string\n",
    "table T\n\t/// kpi description\n\tmeasure M = 1\n\t\tdescription: targetExpression mentioned in prose\n",
    "table T\n\t// kpi comment\n\tmeasure M = \"kpi\"\n",
    "table T\n\tmeasure M =\n\t\t\tVAR kpi = 1\n\t\t\tRETURN kpi\n",
    "table T\n\tmeasure M = 1\n\t\tdisplayFolder: KPI\\calculationGroup\n",
    "table T\n\t/* kpi\n\tcalculationGroup */\n\tmeasure M = 1\n",
    "table T\n\tpartition P = m\n\t\tsource =\n\t\t\tlet kpi = 1, calculationItem = 2 in kpi\n",
])
def test_feature_words_outside_declarations_detect_nothing(text):
    features, tables = extract_feature_expressions(text)
    assert features == []
    assert tables == {}


def test_genuine_declarations_report_owner_and_location():
    text = (
        "table Targets\n\tmeasure Target = 1000\n\t\tkpi\n\t\t\ttargetExpression = 'Sales'[Goal]\n"
        "\t\t\tstatusExpression = ```\n\t\t\t\t\tVAR x = [Target]\n\t\t\t\t\tRETURN x\n\t\t\t\t```\n"
        "\t\tdetailRowsDefinition = SELECTCOLUMNS(Sales, \"x\", Sales[Amount])\n"
        "table 'Time Intelligence'\n\tcalculationGroup\n\t\tcalculationItem YTD = SELECTEDMEASURE()\n"
        "\t\t\tformatStringDefinition = SELECTEDMEASUREFORMATSTRING()\n"
    )
    features, tables = extract_feature_expressions(text)
    assert [(f.area, f.feature, f.owner, f.line) for f in features] == [
        ("KPI expressions", "KPI target expression", "measure 'Targets'[Target]", 4),
        ("KPI expressions", "KPI status expression", "measure 'Targets'[Target]", 5),
        ("Detail rows", "measure detail rows expression", "measure 'Targets'[Target]", 9),
        ("Calculation Groups", "calculation item expression", "calculation item 'YTD' in 'Time Intelligence'", 12),
        ("Format string definitions", "calculation item format-string expression",
         "calculation item 'YTD' in 'Time Intelligence'", 13),
    ]
    assert features[1].expression == "VAR x = [Target]\nRETURN x"
    assert tables == {"Time Intelligence": {"calculation_items": ["YTD"], "line": 11}}


def test_scanner_keeps_expression_continuations_out_of_the_tree():
    declarations = scan_tmdl_declarations(
        "table T\n\tmeasure M =\n\t\t\tVAR kpi = 1\n\t\t\tRETURN kpi\n\t\tformatString: 0\n")
    assert [(d.keyword, d.depth) for d in declarations] == [("table", 0), ("measure", 1), ("formatString", 2)]
    assert declarations[1].expression == "VAR kpi = 1\nRETURN kpi"


def _parse_items(tmp_path, text):
    tables = tmp_path / "M.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "T.tmdl").write_text(text, encoding="utf-8")
    return {parsed.name: parsed for parsed in analyzer.parse_model_items(tmp_path / "M.SemanticModel")}


def test_kpi_child_object_is_not_folded_into_the_measure_dax_body():
    target = next(i for i in analyzer.parse_model_items(MODEL) if i.table == "Targets" and i.name == "Target")
    assert target.dax_body == "1000"


def test_item_dax_body_stops_at_nested_child_objects_but_keeps_continuations(tmp_path):
    items = _parse_items(tmp_path, (
        "table T\n"
        "\t/// Multi-line\n\t/// description\n"
        "\tmeasure Multi =\n\t\t\tVAR x = [A]\n\t\t\tRETURN x\n"
        "\t\tformatString: 0\n"
        "\t\tdisplayFolder: KPIs\n"
        "\t\tkpi\n\t\t\ttargetExpression = [Goal]\n\t\t\tstatusExpression =\n\t\t\t\t\t[Status]\n"
        "\t\tchangedProperty = Name\n"
        "\t\textendedProperty Ext =\n\t\t\t\t{ \"ref\": \"[Ext]\" }\n"
        "\t\tannotation Note = [Annotated]\n\n"
        "\tmeasure Fenced = ```\n\t\t\tVAR y = [B]\n\n\t\t\tRETURN y\n\t\t\t```\n"
        "\t\tkpi\n\t\t\ttrendExpression = [Trend]\n"
        "\t\tformatStringDefinition = [FormatRef]\n"
        "\t\tisHidden\n\n"
        "\tcolumn Calc = [C] + 1\n\t\tdataType: int64\n\t\tchangedProperty = DataType\n"
        "\t\tannotation Note =\n\t\t\t\t[ColumnAnnotation]\n"
        "\t\tisHidden\n\t\tisKey\n\t\tsortByColumn: 'Sort Key'\n\n"
        "\tcolumn Plain\n\t\tdataType: string\n\t\tsourceColumn: Plain\n\t\tisNameInferred\n"
    ))
    multi = items["Multi"]
    assert (multi.dax_body, multi.description, multi.format_string, multi.display_folder) == (
        "VAR x = [A]\nRETURN x", "Multi-line\ndescription", "0", "KPIs")
    fenced = items["Fenced"]
    assert (fenced.dax_body, fenced.is_hidden) == ("VAR y = [B]\nRETURN y\n[FormatRef]", True)
    calc = items["Calc"]
    assert (calc.item_type, calc.dax_body, calc.data_type, calc.is_hidden, calc.is_key, calc.sort_by_column) == (
        "Calculated Column", "[C] + 1", "int64", True, True, "Sort Key")
    plain = items["Plain"]
    assert (plain.item_type, plain.dax_body, plain.source_column, plain.is_inferred) == (
        "Column", "", "Plain", True)


def test_perspective_members_come_from_declarations_only():
    members = extract_perspective_members(
        "perspective Exec\n\t// perspectiveMeasure Ghost\n\tperspectiveTable Sales\n\t\tperspectiveMeasure Revenue\n")
    assert [(m.perspective, m.table, m.name, m.kind) for m in members] == [
        ("Exec", "Sales", "", "table"), ("Exec", "Sales", "Revenue", "measure")]


def test_kpi_selector_table_creates_no_kpi_limitation(results, payload):
    limitations = results["analysis_limitations"]
    assert not any("KPI Selector" in limitation["source_file"] for limitation in limitations)
    kpi_areas = [limitation for limitation in limitations if limitation["area"] == "KPI expressions"]
    assert {limitation["owner"] for limitation in kpi_areas} == {"measure 'Targets'[Target]"}
    assert {limitation["line"] for limitation in kpi_areas} == {4, 5, 9}
    for name in ("KPI Name", "KPI Flag", "KPI Label", "KPI Count"):
        triggers = row(results, "KPI Selector", name)["review_triggers"]
        assert not any("KPI" in trigger and "Referenced by" in trigger for trigger in triggers), triggers
        assert not any("Unsupported Metadata:" in trigger for trigger in triggers)
    browser_triggers = [trigger for i in payload["items"] for trigger in i["reviewTriggers"]]
    assert not any("KPI Selector.tmdl" in trigger for trigger in browser_triggers)


def test_genuine_kpi_reference_is_evidence_on_the_referenced_item(results, payload):
    goal = row(results, "Sales", "Revenue Goal")
    assert goal["status"] == "NOT USED"
    assert goal["removal_risk"] == "Review"
    # The KPI target is evidence, not a DAX dependency of the owning measure (#92):
    # the item stays Unused with exactly one targeted KPI trigger.
    kpi_triggers = [trigger for trigger in goal["review_triggers"] if "KPI" in trigger]
    assert len(kpi_triggers) == 1
    assert kpi_triggers[0].startswith("Referenced by the KPI target expression of measure 'Targets'[Target] "
                                      "(definition/tables/Targets.tmdl:4)")
    browser = item(payload, "Sales", "Revenue Goal")
    assert browser["usageState"] == "Unused"
    assert browser["deleteSafety"] == "Review"
    # Sales[Revenue] is used directly; the KPI reference must not downgrade it.
    assert row(results, "Sales", "Revenue")["status"] == "USED"


def test_unresolved_dynamic_coverage_still_prevents_safe(results):
    assert not results["coverage"]["complete"]
    shared = results["coverage"]["limitations"]
    assert {limitation["owner"] for limitation in shared} == {
        "calculation item 'Current' in 'Time Intelligence'",
        "calculation item 'YTD' in 'Time Intelligence'",
        "calculation item 'PY' in 'Time Intelligence'",
    }
    unused = [r for r in results["items"] if r["status"] == "NOT USED"]
    assert unused and all(r["removal_risk"] != "Safe" for r in unused)
    assert all(sum(t.startswith("No use found in the selected scope") for t in r["review_triggers"]) == 1
               for r in unused)


# ── #83: calculation-group and perspective dependencies ──────────────────────

def test_selector_shows_parent_table_consumers_separately(results, payload):
    selector = row(results, "Time Intelligence", "Name")
    assert selector["status"] == "NOT USED"
    assert selector["removal_risk"] == "Review"
    assert selector["model_role"] == "Calculation group selector"
    assert selector["table_kind"] == "Calculation group"
    assert selector["table_dependents"] == CONSUMERS
    triggers = selector["review_triggers"]
    assert any(t.startswith("Selector column of calculation group 'Time Intelligence' (3 calculation items: "
                            "Current, YTD, PY)") for t in triggers)
    parent = next(t for t in triggers if t.startswith("Parent table 'Time Intelligence' is required by 10 retained DAX consumers"))
    assert "parent-table references, not direct consumers of this item" in parent
    browser = item(payload, "Time Intelligence", "Name")
    assert browser["modelRole"] == "Calculation group selector"
    assert browser["tableDependentCount"] == 10
    assert browser["tableDependentItems"] == CONSUMERS
    assert browser["measureDependentCount"] == 0  # not pretended to be direct column consumers
    assert browser["usageCount"] == 0  # not pretended to be Report References
    assert browser["usageState"] == "Unused"
    assert browser["deleteSafety"] == "Review"


def test_calculation_group_table_is_identified_and_blocked(results, payload):
    summary = next(t for t in results["table_summaries"] if t["name"] == "Time Intelligence")
    assert summary["table_kind"] == "Calculation group"
    assert summary["role_label"] == "calculation-group"
    assert "No relationships" not in summary["role_reason"]
    assert summary["calculation_items"] == ["Current", "YTD", "PY"]
    assert summary["external_dax_dependents"] == CONSUMERS
    assert summary["cleanup_recommendation"] == "Blocked"
    assert "10 retained DAX consumers" in summary["cleanup_reason"]
    assert "Sales[Revenue Ignoring TI 01]" in summary["cleanup_reason"]
    assert summary["perspectives"] == ["Executive"]
    table = next(t for t in payload["tables"] if t["name"] == "Time Intelligence")
    assert table["tableKind"] == "Calculation group"
    assert table["cleanupRecommendation"] == "Blocked"
    assert table["usageState"] == "Indirect"
    assert table["usageStatus"].startswith("INDIRECT (via: ")
    assert "10 DAX consumers outside this table" in table["usageStatus"]
    assert table["relationshipCount"] == 0
    assert table["externalDaxDependents"] == CONSUMERS


def test_perspective_membership_is_concrete_evidence_not_runtime_use(results, payload):
    goal = row(results, "Sales", "Revenue Goal")
    assert goal["perspectives"] == [
        {"perspective": "Executive", "source_file": "definition/perspectives/Executive.tmdl", "line": 4}]
    assert any(t == ("Member of perspective Executive (definition/perspectives/Executive.tmdl). Removing the "
                     "item also removes this perspective member; membership alone does not prove a report "
                     "executes it.") for t in goal["review_triggers"])
    assert goal["status"] == "NOT USED"
    assert not any(limitation["area"] == "Perspectives" for limitation in results["analysis_limitations"])
    browser = item(payload, "Sales", "Revenue Goal")
    assert browser["perspectiveMemberships"] == [
        {"perspective": "Executive", "sourceFile": "definition/perspectives/Executive.tmdl"}]
    assert browser["usageCount"] == 0  # membership never counts as a Report Reference
    assert browser["usageState"] == "Unused"
    assert browser["deleteSafety"] == "Review"


def test_deletion_guards_block_whole_group_and_allow_coordinated_final_state(tmp_path):
    policy = evaluate_deletion_policy(MODEL, [REPORT], [
        {"action": "delete", "table": "Time Intelligence", "name": "", "item_type": "table"}])
    assert not policy["ok"]
    table_guards = [v for v in policy["violations"] if v["rule_id"] == "SMC-D006"]
    assert len(table_guards) == 10
    assert {v["message"] for v in table_guards} == {
        f"Table Time Intelligence is required by retained {consumer}." for consumer in CONSUMERS}
    assert any(v["rule_id"] == "SMC-D002" for v in policy["violations"])  # dynamic coverage stays conservative
    snapshot = {p: p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()}
    assert {p: p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()} == snapshot

    # Without dynamic limitations, the same parent-table guard is evaluated against
    # the proposed final state: removing the consumers together is allowed.
    model = tmp_path / "Plain.SemanticModel"
    report = tmp_path / "Exec.Report"
    (model / "definition" / "tables").mkdir(parents=True)
    (report / "definition").mkdir(parents=True)
    (model / "definition/tables/Dim.tmdl").write_text("table Dim\n\tcolumn Key\n\t\tdataType: string\n", encoding="utf-8")
    (model / "definition/tables/Sales.tmdl").write_text(
        "table Sales\n\tmeasure Rows = COUNTROWS(Sales)\n\tmeasure Outside = CALCULATE([Rows], ALL('Dim'))\n",
        encoding="utf-8")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../Plain.SemanticModel"}}}), encoding="utf-8")
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    whole_table = [{"action": "delete", "table": "Dim", "name": "", "item_type": "table"}]
    blocked = evaluate_deletion_policy(model, [report], whole_table)
    assert [v["message"] for v in blocked["violations"]] == ["Table Dim is required by retained Sales[Outside]."]
    coordinated = whole_table + [{"action": "delete", "table": "Sales", "name": "Outside", "item_type": "Measure"}]
    assert evaluate_deletion_policy(model, [report], coordinated)["ok"]


# ── #84: analysis limitations are a separate surface ─────────────────────────

def test_limitation_counts_use_distinct_units(results, payload):
    summary = results["analysis_limitation_summary"]
    limitations = payload["analysisLimitations"]
    # 3 calculation items + 1 calculation-item format string (shared, dynamic);
    # KPI target, status and trend expressions (targeted).
    assert summary["distinct_count"] == limitations["distinctCount"] == 7
    assert summary["shared_count"] == limitations["sharedCount"] == 4
    assert summary["targeted_count"] == limitations["targetedCount"] == 3
    unused = [r for r in results["items"] if r["status"] == "NOT USED"]
    assert summary["affected_item_count"] == limitations["affectedItemCount"] == len(unused)
    # Repeating a shared reason on every item must not inflate the distinct count.
    assert sum(len(r["analysis_limitation_ids"]) for r in results["items"]) > summary["distinct_count"]
    assert limitations["coverageComplete"] is False


def test_each_limitation_explains_feature_location_and_effect(payload):
    by_owner = {(l["area"], l["owner"], l["line"]): l for l in payload["analysisLimitations"]["limitations"]}
    format_string = by_owner[("Format string definitions", "calculation item 'YTD' in 'Time Intelligence'", 8)]
    assert format_string["feature"] == "calculation item format-string expression"
    assert format_string["message"] == (
        "Dependency checking is incomplete for the calculation item format-string expression of "
        "calculation item 'YTD' in 'Time Intelligence' (definition/tables/Time Intelligence.tmdl:8).")
    assert "invalid" not in format_string["message"].lower()
    assert format_string["scope"] == "shared"
    assert format_string["checked"] and format_string["unchecked"] and format_string["effect"]
    kpi = by_owner[("KPI expressions", "measure 'Targets'[Target]", 4)]
    assert kpi["scope"] == "targeted"
    assert kpi["targets"] == ["Sales[Revenue Goal]"]
    assert kpi["affectedItems"] == [{"type": "Measure", "table": "Sales", "name": "Revenue Goal"}]
    assert kpi["effect"] == "Only the referenced items are affected; they stay at Review."
    trend = by_owner[("KPI expressions", "measure 'Targets'[Target]", 9)]
    assert trend["scope"] == "targeted" and trend["targets"] == [] and trend["affectedItemCount"] == 0


def test_report_health_excludes_model_limitations(payload):
    keys = {group["key"] for group in payload["reportHealth"]["groups"]}
    assert "unsupported_metadata" not in keys
    assert payload["reportHealth"]["totalIssueCount"] == 0
    assert payload["reportHealth"]["signalCounts"] == {"staleReferences": 0, "brokenModelReferences": 0}


def test_item_summaries_lead_with_concrete_reason_and_collapse_shared_gaps(results):
    selector = row(results, "Time Intelligence", "Name")
    triggers = selector["review_triggers"]
    assert triggers[0].startswith("Selector column of calculation group")
    assert triggers[-1].startswith("No use found in the selected scope, but 4 analysis limitations (")
    assert "+2 more" in triggers[-1]
    assert selector["analysis_limitation_ids"] == [l["id"] for l in results["coverage"]["limitations"]]


def test_exports_and_ci_agree_with_browser_counts(results, payload, tmp_path):
    exported = json.loads(analyzer.format_json_output(results))
    assert exported["analysisLimitationSummary"]["distinct_count"] == payload["analysisLimitations"]["distinctCount"]
    assert [l["id"] for l in exported["analysisLimitations"]] == [l["id"] for l in payload["analysisLimitations"]["limitations"]]
    selector = next(i for i in exported["items"] if i["table"] == "Time Intelligence" and i["name"] == "Name")
    assert selector["modelRole"] == "Calculation group selector"
    assert selector["tableDependents"] == CONSUMERS
    assert selector["analysisLimitationIds"]
    markdown = analyzer.format_full(results)
    assert "## Analysis Limitations" in markdown
    assert "7 distinct limitations" in markdown
    assert "KPI Selector" not in markdown.split("## Summary")[0]
    code, check = ci.run_check(FIXTURE, model_path=MODEL, report_paths=[REPORT])
    assert code == 1
    smc003 = [f for f in check["findings"] if f["rule_id"] == "SMC003"]
    assert len(smc003) == 7
    assert not any("KPI Selector" in f["path"] for f in smc003)
    assert any(f["message"].startswith("Analysis limitation (KPI expressions): dependency checking is incomplete for the "
                                       "KPI target expression of measure 'Targets'[Target]") for f in smc003)
