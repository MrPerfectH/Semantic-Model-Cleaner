"""Unfiltered visual filter cards are not Stale Report References.

Synthetic fixture only. A filter card without a saved condition ("All") says
nothing about whether its field is obsolete, so it must not produce stale
warnings or cleanup candidates. Classification, banner counts, the browser
candidate builder, the preview API, and the CLI must agree on what is eligible.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, cli, report_writer, webapp

ROOT = Path(__file__).parents[1]
TEMPLATES = ("index.html", "index_v2.html")


def _col(table, prop):
    return {"Column": {"Property": prop, "Expression": {"SourceRef": {"Entity": table}}}}


def _measure(table, prop):
    return {"Measure": {"Property": prop, "Expression": {"SourceRef": {"Entity": table}}}}


def _projection(field, query_ref, **extra):
    return {"field": field, "queryRef": query_ref, **extra}


def _card(field, name):
    # No "filter" key: an unfiltered (All) card.
    return {"name": name, "field": field, "type": "Categorical"}


def _write_visual(report, visual_id, visual):
    folder = report / "definition" / "pages" / "Page1" / "visuals" / visual_id
    folder.mkdir(parents=True)
    (folder / "visual.json").write_text(json.dumps({"name": visual_id, "visual": visual}, indent=2), encoding="utf-8")


def _build_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Region\n\tcolumn Country\n\tcolumn City\n\tcolumn Segment\n\tcolumn Amount\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\tmeasure 'Legacy Margin' = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (tables / "Metric Parameter.tmdl").write_text(
        "table 'Metric Parameter'\n"
        "\tcolumn Metric\n\tcolumn 'Metric Fields'\n"
        "\tpartition 'Metric Parameter' = calculated\n"
        "\t\tsource =\n\t\t\t{\n\t\t\t\t(\"Revenue\", NAMEOF('Sales'[Revenue]), 0)\n\t\t\t}\n",
        encoding="utf-8",
    )
    (report / "definition" / "pages" / "Page1").mkdir(parents=True)
    (report / "definition" / "pages" / "Page1" / "page.json").write_text(json.dumps({"displayName": "Overview"}), encoding="utf-8")
    (report / "definition.pbir").write_text(
        json.dumps({"version": "1.0", "datasetReference": {"byPath": {"path": "../../Models/Sales.SemanticModel"}}}),
        encoding="utf-8",
    )

    # Working Region slicer: active Region projection + unfiltered Region card.
    _write_visual(report, "RegionSlicer", {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [_projection(_col("Sales", "Region"), "Sales.Region", active=True)]}}},
        "filterConfig": {"filters": [_card(_col("Sales", "Region"), "regionCard")]},
    })
    # Measure projection with the active flag omitted, a configured drill level with active=false.
    _write_visual(report, "DrillTable", {
        "visualType": "tableEx",
        "query": {"queryState": {
            "Values": {"projections": [_projection(_measure("Sales", "Revenue"), "Sales.Revenue")]},
            "Rows": {"projections": [
                _projection(_col("Sales", "Country"), "Sales.Country"),
                _projection(_col("Sales", "City"), "Sales.City", active=False),
            ]},
        }},
        "filterConfig": {"filters": [
            _card(_measure("Sales", "Revenue"), "revenueCard"),
            _card(_col("Sales", "Country"), "countryCard"),
            _card(_col("Sales", "City"), "cityCard"),
        ]},
    })
    # Field-parameter binding in the same visual as its unfiltered card.
    _write_visual(report, "MetricSlicer", {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {
            "projections": [_projection(_col("Metric Parameter", "Metric Fields"), "Metric Parameter.Metric Fields")],
            "fieldParameters": [{"parameterExpr": _col("Metric Parameter", "Metric Fields")}],
        }}},
        "filterConfig": {"filters": [_card(_col("Metric Parameter", "Metric Fields"), "metricCard")]},
    })
    # Intentional filter-only control: Segment is absent from the query.
    _write_visual(report, "FilterOnly", {
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [_projection(_measure("Sales", "Revenue"), "Sales.Revenue")]}}},
        "filterConfig": {"filters": [_card(_col("Sales", "Segment"), "segmentCard")]},
    })
    # Genuine stale formatting selector: nothing in the query matches it.
    _write_visual(report, "StaleFormat", {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": [_projection(_measure("Sales", "Revenue"), "Sales.Revenue")]}}},
        "objects": {"dataPoint": [{
            "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#228B22'"}}}}}},
            "selector": {"metadata": "Sales.Legacy Margin"},
        }]},
    })
    return workspace


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def workspace(tmp_path):
    return _build_workspace(tmp_path)


@pytest.fixture()
def analysis(workspace):
    results = analyzer.analyze(workspace.resolve())
    return results, webapp._serialize_results(results)


def _item(payload, table, name):
    return next(i for i in payload["items"] if i["table"] == table and i["name"] == name)


def test_unfiltered_cards_do_not_create_stale_findings(analysis):
    results, payload = analysis
    cards = {(i["table"], i["name"]) for i in results["report_issues"] if i["issueType"] in ("inactive_visual_filter_reference", "stale_visual_selector")}
    assert cards == {("Sales", "Legacy Margin")}  # only the genuine stale selector

    for table, name in [("Sales", "Region"), ("Sales", "Country"), ("Sales", "City"), ("Sales", "Revenue"),
                        ("Metric Parameter", "Metric Fields")]:
        item = _item(payload, table, name)
        assert item["staleUsageCount"] == 0, (table, name)
        assert "Stale" not in item["issueState"], (table, name)
        assert item["usageState"] != "Stale only", (table, name)


def test_filter_only_field_is_retained_as_a_used_filter_control(analysis):
    _, payload = analysis
    segment = _item(payload, "Sales", "Segment")
    assert segment["staleUsageCount"] == 0
    assert segment["usageCount"] >= 1
    assert segment["usageState"] == "Used"
    assert segment["deleteSafety"] != "Safe"
    assert any(row["context"] == "Filters pane (visual)" for row in segment["usageDetails"])


def test_genuine_stale_formatting_selector_stays_detectable(analysis):
    _, payload = analysis
    legacy = _item(payload, "Sales", "Legacy Margin")
    assert legacy["usageState"] == "Stale only"
    assert [row["staleKind"] for row in legacy["staleUsageDetails"]] == [""]
    assert all(row["cleanupEligible"] is True for row in legacy["staleUsageDetails"])


def test_banner_separates_findings_from_eligible_cleanup_entries(analysis):
    _, payload = analysis
    group = next(g for g in payload["reportHealth"]["groups"] if g["key"] == "stale_report_references")
    assert group["count"] == 1
    assert group["action"]["entryCount"] == 1
    assert group["action"]["entryCount"] <= group["count"]


def _ineligible_item(**overrides):
    detail = {"report": "Executive", "reportPath": "/r/Executive.Report", "artifactPath": "definition/pages/P/visuals/V/visual.json",
              "sourcePath": "visual.filterConfig.filters.[0].field.Column", "selectorValue": "Sales[Region]",
              "staleKind": "inactive_visual_filter_reference", "cleanupEligible": False}
    detail.update(overrides)
    return {"type": "Column", "table": "Sales", "name": "Region", "staleUsageCount": 1,
            "staleUsageDetails": [detail]}


def test_ineligible_only_findings_offer_no_cleanup_action():
    health = webapp._build_report_health([], [_ineligible_item()])
    group = next(g for g in health["groups"] if g["key"] == "stale_report_references")
    assert group["count"] == 1
    assert group["action"] is None
    assert "no supported cleanup" in group["description"].lower()


def test_mixed_kinds_only_count_eligible_entries_in_the_action():
    eligible = {"report": "Executive", "reportPath": "/r/Executive.Report", "artifactPath": "a.json", "sourcePath": "s",
                "selectorValue": "Sales.X", "staleKind": "", "cleanupEligible": True}
    mixed = _ineligible_item()
    mixed["staleUsageCount"] = 2
    mixed["staleUsageDetails"].append(eligible)
    group = next(g for g in webapp._build_report_health([], [mixed])["groups"] if g["key"] == "stale_report_references")
    assert group["count"] == 2
    assert group["action"]["entryCount"] == 1


def test_writer_rejects_unsupported_stale_kind_instead_of_reporting_zero_removals(workspace):
    report = workspace / "Reports" / "Executive.Report"
    visual = "definition/pages/Page1/visuals/RegionSlicer/visual.json"
    before = _snapshot(workspace)
    result = report_writer.cleanup_stale_metadata_selectors(dry_run=True, entries=[{
        "report_path": str(report), "artifact_path": visual, "selector_value": "Sales[Region]",
        "source_path": "visual.filterConfig.filters.[0].field.Column", "stale_kind": "inactive_visual_filter_reference",
    }])
    assert result["ok"] is False
    assert "inactive_visual_filter_reference" in result["error"]
    assert _snapshot(workspace) == before


def test_preview_api_rejects_ineligible_entries_and_previews_real_stale_selector(workspace):
    report = workspace / "Reports" / "Executive.Report"
    client = webapp.app.test_client()
    before = _snapshot(workspace)

    bad = client.post("/api/report/cleanup-stale", json={"dry_run": True, "entries": [{
        "report_path": str(report), "artifact_path": "definition/pages/Page1/visuals/RegionSlicer/visual.json",
        "selector_value": "Sales[Region]", "source_path": "visual.filterConfig.filters.[0].field.Column",
        "stale_kind": "inactive_visual_filter_reference"}]})
    assert bad.status_code == 400

    good = client.post("/api/report/cleanup-stale", json={"dry_run": True, "entries": [{
        "report_path": str(report), "artifact_path": "definition/pages/Page1/visuals/StaleFormat/visual.json",
        "selector_value": "Sales.Legacy Margin", "source_path": "visual.objects.dataPoint.[0].selector.metadata",
        "stale_kind": ""}]})
    assert good.status_code == 200
    assert good.get_json()["removed_count"] == 1
    assert _snapshot(workspace) == before  # dry run is byte-identical


def _run_builder(template: str, items: list[dict], reports: list[dict]) -> list[dict]:
    html = (ROOT / "src/semantic_model_cleaner/templates" / template).read_text()
    functions = []
    for name in ("getReportPathByName", "getReportPathForReference", "cleanupEligibleStaleUsages",
                 "staleCleanupEntriesForItem", "staleCleanupEntriesForItems"):
        match = re.search(r"function " + name + r"\([^)]*\) \{.*?\n\}", html, re.S)
        assert match, (template, name)
        functions.append(match.group())
    script = (
        "var chosenReports=" + json.dumps(reports) + ";\n" + "\n".join(functions) + "\n"
        "process.stdout.write(JSON.stringify(staleCleanupEntriesForItems(" + json.dumps(items) + ")));\n"
    )
    result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _entry_key(entry):
    return tuple(entry[k] for k in ("report_path", "artifact_path", "selector_value", "source_path", "stale_kind"))


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js unavailable")
@pytest.mark.parametrize("template", TEMPLATES)
def test_browser_candidate_builder_agrees_with_cli_and_ignores_ineligible_kinds(workspace, analysis, template):
    results, payload = analysis
    report = workspace / "Reports" / "Executive.Report"
    reports = [{"name": "Executive", "path": str(report)}]

    ui_entries = _run_builder(template, payload["items"], reports)
    cli_entries = analyzer.build_stale_cleanup_entries(results, [report])
    assert len(ui_entries) == len(cli_entries) == 1
    assert {_entry_key(e) for e in ui_entries} == {_entry_key(e) for e in cli_entries}

    # Ineligible-only: legacy/hand-built payloads must not become candidates.
    assert _run_builder(template, [_ineligible_item(reportPath=str(report))], reports) == []
    legacy = _ineligible_item(reportPath=str(report))
    del legacy["staleUsageDetails"][0]["cleanupEligible"]
    assert _run_builder(template, [legacy], reports) == []

    # Mixed: only the eligible detail survives.
    mixed = next(i for i in payload["items"] if i["name"] == "Legacy Margin")
    mixed = {**mixed, "staleUsageDetails": mixed["staleUsageDetails"] + _ineligible_item(reportPath=str(report))["staleUsageDetails"]}
    assert [_entry_key(e) for e in _run_builder(template, [mixed], reports)] == [_entry_key(e) for e in cli_entries]


def test_cli_dry_run_reports_only_the_genuine_stale_selector(workspace, capsys):
    before = _snapshot(workspace)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["clean-stale", str(workspace), "--format", "json"])
    assert exit_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 1
    assert [c["selectorValue"] for c in payload["candidates"]] == ["Sales.Legacy Margin"]
    assert _snapshot(workspace) == before


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js unavailable")
@pytest.mark.parametrize("template", TEMPLATES)
def test_bulk_stale_cleanup_excludes_inactive_cards_and_orphan_bookmarks(template):
    html = (ROOT / "src/semantic_model_cleaner/templates" / template).read_text()
    functions = []
    for name in ("getReportPathByName", "getReportPathForReference", "isReportIssueStale",
                 "isReportIssueCleanup", "reportIssueCleanupEntry", "reportIssueActionEntry",
                 "reportCleanupEntriesForIssues"):
        match = re.search(r"function " + name + r"\([^)]*\) \{.*?\n\}", html, re.S)
        assert match, (template, name)
        functions.append(match.group())
    issues = [{"reportPath": "/demo.Report", "artifactPath": "visual.json",
               "sourcePath": f"visual.objects.[{i}]", "issueType": kind,
               "selectorValue": "Sales.Old"}
              for i, kind in enumerate(("stale_visual_selector", "inactive_visual_filter_reference",
                                        "orphan_bookmark_visual_state"))]
    script = ("var chosenReports=[{name:'Demo',path:'/demo.Report'}];\n"
              + "\n".join(functions) + "\nvar issues=" + json.dumps(issues) + ";\n"
              + "process.stdout.write(JSON.stringify({selected:reportCleanupEntriesForIssues(issues),"
              + "all:reportCleanupEntriesForIssues(issues.filter(isReportIssueCleanup)),"
              + "explicit:reportIssueActionEntry(issues[1],'remove')}));")
    result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for scope in ("selected", "all"):
        assert len(payload[scope]["stale"]) == 1
        assert payload[scope]["stale"][0]["source_path"] == "visual.objects.[0]"
        assert payload[scope]["remove"] == []
    assert payload["explicit"]["action"] == "remove"
    assert payload["explicit"]["source_path"] == "visual.objects.[1]"
