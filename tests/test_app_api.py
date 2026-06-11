import json
from pathlib import Path

from semantic_model_cleaner import analyzer, webapp as web_app


PRODUCT_QA_WORKSPACE_DIR = (
    Path(__file__).resolve().parents[1] / "examples" / "product-qa-workspace"
)


def _fake_results():
    return {
        "items": [
            {
                "item": analyzer.ModelItem(
                    item_type="Measure",
                    table="Sales",
                    name="Revenue",
                    dax_body="// [Legacy Revenue]\nSUM(Sales[Amount])",
                ),
                "status": "NOT USED",
                "usages": [],
                "removal_risk": "Safe",
            }
        ],
        "summary": {
            "total_measures": 1,
            "total_columns": 0,
            "total_calc_columns": 0,
            "used_in_visuals": 0,
            "used_relationship": 0,
            "used_rls": 0,
            "used_key_column": 0,
            "used_hierarchy": 0,
            "used_sort_column": 0,
            "indirect": 0,
            "not_used": 1,
            "total_usage_refs": 0,
            "models": ["Sales.SemanticModel"],
            "reports": ["Executive"],
            "tables": {
                "Sales": {
                    "total": 1,
                    "used": 0,
                    "unused": 1,
                    "measures": 1,
                    "measures_used": 0,
                    "columns": 0,
                    "columns_used": 0,
                }
            },
        },
        "table_summaries": [
            {
                "name": "Sales",
                "role_label": "isolated",
                "role_reason": "No relationships were found for this table.",
                "item_count": 1,
                "measure_count": 1,
                "column_count": 0,
                "calculated_column_count": 0,
                "direct_report_measure_count": 0,
                "direct_report_column_count": 0,
                "used_item_count": 0,
                "unused_item_count": 1,
                "hidden_item_count": 0,
                "usage_ref_count": 0,
                "report_count": 0,
                "reports": [],
                "page_count": 0,
                "pages": [],
                "relationship_count": 0,
                "active_relationship_count": 0,
                "inactive_relationship_count": 0,
                "one_to_many_count": 0,
                "many_to_one_count": 0,
                "one_to_one_count": 0,
                "many_to_many_count": 0,
                "related_tables": [],
                "relationship_only_columns": [],
                "single_column_measures": [],
                "relationships": [],
                "signals": ["No direct report references were found for this table."],
                "items": [
                    {
                        "name": "Revenue",
                        "ref": "Sales[Revenue]",
                        "type": "Measure",
                        "status": "NOT USED",
                        "removal_risk": "Safe",
                        "usage_count": 0,
                    }
                ],
            }
        ],
        "warnings": [
            {
                "code": "AMBIGUOUS_NAMEOF_TARGET",
                "severity": "warning",
                "message": "Test warning",
                "model": "Sales.SemanticModel",
                "table": "Metric Parameter",
                "source_file": "/tmp/Metric Parameter.tmdl",
            }
        ],
    }


def _fake_review_results():
    results = _fake_results()
    results["items"][0]["item"] = analyzer.ModelItem(
        item_type="Column",
        table="Sales",
        name="CustomerKey",
        dax_body="",
        is_hidden=True,
    )
    results["items"][0]["removal_risk"] = "Review"
    results["items"][0]["review_triggers"] = ["Item is hidden"]
    results["summary"]["total_measures"] = 0
    results["summary"]["total_columns"] = 1
    results["summary"]["tables"]["Sales"]["measures"] = 0
    results["summary"]["tables"]["Sales"]["measures_used"] = 0
    results["summary"]["tables"]["Sales"]["columns"] = 1
    results["summary"]["tables"]["Sales"]["columns_used"] = 0
    results["table_summaries"][0]["measure_count"] = 0
    results["table_summaries"][0]["column_count"] = 1
    results["table_summaries"][0]["items"][0]["name"] = "CustomerKey"
    results["table_summaries"][0]["items"][0]["ref"] = "Sales[CustomerKey]"
    results["table_summaries"][0]["items"][0]["type"] = "Column"
    results["table_summaries"][0]["items"][0]["removal_risk"] = "Review"
    results["table_summaries"][0]["items"][0]["review_triggers"] = ["Item is hidden"]
    return results


def _fake_column_results():
    results = _fake_results()
    results["items"][0]["item"] = analyzer.ModelItem(
        item_type="Column",
        table="Sales",
        name="Region",
        dax_body="",
    )
    results["summary"]["total_measures"] = 0
    results["summary"]["total_columns"] = 1
    results["summary"]["tables"]["Sales"]["measures"] = 0
    results["summary"]["tables"]["Sales"]["columns"] = 1
    results["table_summaries"][0]["measure_count"] = 0
    results["table_summaries"][0]["column_count"] = 1
    results["table_summaries"][0]["items"][0]["name"] = "Region"
    results["table_summaries"][0]["items"][0]["ref"] = "Sales[Region]"
    results["table_summaries"][0]["items"][0]["type"] = "Column"
    return results


def test_index_renders_packaged_template():
    web_app._state["runtime"] = web_app.experiments.runtime_config(raw_channel="stable")
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b"Semantic Model Cleaner" in response.data
    assert b"Find connected reports" in response.data
    assert b"compareResultSection" in response.data
    assert b"runSemanticModelCompare" in response.data


def test_index_shows_beta_banner_when_runtime_enabled():
    web_app._state["runtime"] = web_app.experiments.runtime_config(
        raw_channel="beta",
        extra_experiments=["compare-models"],
    )

    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b"Beta channel enabled" in response.data
    assert b"Model Compare" in response.data
    assert b"UI build identifier" in response.data


def test_api_analyze_allows_cleanup_for_single_model(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    model_path.mkdir()
    report_path.mkdir()

    monkeypatch.setattr(web_app.analyzer, "analyze", lambda **_: _fake_results())

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["total_measures"] == 1
    assert payload["warnings"][0]["code"] == "AMBIGUOUS_NAMEOF_TARGET"
    assert payload["items"][0]["statusDetail"] == "NOT USED"
    assert payload["items"][0]["daxExpression"] == "// [Legacy Revenue]\nSUM(Sales[Amount])"
    assert payload["items"][0]["mSourceDetails"] is None
    assert payload["items"][0]["dependsOnMeasures"] == []
    assert payload["items"][0]["dependsOnColumns"] == []
    assert payload["items"][0]["usedByItems"] == []
    assert payload["items"][0]["usageDetails"] == []
    assert payload["items"][0]["reportCount"] == 0
    assert payload["items"][0]["pageCount"] == 0
    assert payload["items"][0]["commentedRefs"] == ["[Legacy Revenue]"]
    assert payload["items"][0]["reportUseSummary"] == "No"
    assert payload["items"][0]["measureDependentCount"] == 0
    assert payload["items"][0]["reportUsedMeasureDependentCount"] == 0
    assert payload["items"][0]["relationshipRefCount"] == 0
    assert payload["items"][0]["otherModelUses"] == []
    assert payload["items"][0]["usageState"] == "Unused"
    assert payload["items"][0]["issueState"] == ""
    assert payload["items"][0]["deleteSafety"] == "Safe"
    assert payload["tables"][0]["name"] == "Sales"
    assert payload["tables"][0]["usageStatus"] == "NOT USED"
    assert payload["tables"][0]["usageState"] == "Unused"
    assert payload["tables"][0]["issueState"] == ""
    assert payload["tables"][0]["directReportMeasureCount"] == 0
    assert payload["tables"][0]["directReportColumnCount"] == 0
    assert payload["tables"][0]["signals"] == ["No direct report references were found for this table."]
    assert payload["reportIssues"] == []


def test_api_analyze_returns_report_issues_for_selected_reports(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    tables_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\tmeasure 'Revenue Total' = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (report_path / "definition" / "pages" / "Page1" / "page.json").write_text(
        json.dumps({"displayName": "Overview"}, indent=2),
        encoding="utf-8",
    )
    (visual_dir / "visual.json").write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "card",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Property": "Revenue Totl",
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                            }
                                        }
                                    }
                                ]
                            }
                        }
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reportIssues"][0]["issueType"] == "missing_measure"
    assert payload["reportIssues"][0]["report"] == "Executive"
    assert payload["reportIssues"][0]["page"] == "Overview"
    assert payload["reportIssues"][0]["suggestions"][0]["name"] == "Revenue Total"


def test_serialize_results_includes_bare_table_dependencies():
    results = {
        "items": [
            {
                "item": analyzer.ModelItem(
                    item_type="Column",
                    table="Sales",
                    name="Amount",
                ),
                "status": "NOT USED",
                "usages": [],
                "removal_risk": "Safe",
            },
            {
                "item": analyzer.ModelItem(
                    item_type="Measure",
                    table="Measures",
                    name="Row Count",
                    dax_body="COUNTROWS('Sales')",
                ),
                "status": "NOT USED",
                "usages": [],
                "removal_risk": "Caution",
            },
        ],
        "summary": {
            "total_measures": 1,
            "total_columns": 1,
            "total_calc_columns": 0,
            "used_in_visuals": 0,
            "used_relationship": 0,
            "used_rls": 0,
            "used_key_column": 0,
            "used_hierarchy": 0,
            "used_sort_column": 0,
            "indirect": 0,
            "not_used": 2,
            "total_usage_refs": 0,
            "models": ["Sales.SemanticModel"],
            "reports": ["Executive"],
            "tables": {},
        },
        "table_summaries": [
            {
                "name": "Sales",
                "role_label": "isolated",
                "role_reason": "No relationships were found for this table.",
                "item_count": 1,
                "measure_count": 0,
                "column_count": 1,
                "calculated_column_count": 0,
                "used_item_count": 0,
                "unused_item_count": 1,
                "hidden_item_count": 0,
                "usage_ref_count": 0,
                "report_count": 0,
                "reports": [],
                "page_count": 0,
                "pages": [],
                "relationship_count": 0,
                "active_relationship_count": 0,
                "inactive_relationship_count": 0,
                "one_to_many_count": 0,
                "many_to_one_count": 0,
                "one_to_one_count": 0,
                "many_to_many_count": 0,
                "related_tables": [],
                "relationship_only_columns": [],
                "single_column_measures": [],
                "external_dax_dependents": ["Measures[Row Count]"],
                "relationships": [],
                "signals": [
                    "1 DAX item outside this table depends on it.",
                    "No direct report references were found for this table.",
                ],
                "items": [
                    {
                        "name": "Amount",
                        "ref": "Sales[Amount]",
                        "type": "Column",
                        "status": "NOT USED",
                        "removal_risk": "Safe",
                        "usage_count": 0,
                    }
                ],
            }
        ],
        "warnings": [],
    }

    web_app._state["model_paths"] = []
    payload = web_app._serialize_results(results)

    measure = next(item for item in payload["items"] if item["table"] == "Measures")
    assert measure["dependsOnTables"] == ["Sales"]
    assert payload["tables"][0]["externalDaxDependents"] == ["Measures[Row Count]"]


def test_serialize_results_includes_reference_locator_fields():
    results = {
        "items": [
            {
                "item": analyzer.ModelItem(
                    item_type="Measure",
                    table="Sales",
                    name="Revenue",
                ),
                "status": "USED",
                "usages": [
                    analyzer.UsageRef(
                        table="Sales",
                        name="Revenue",
                        ref_type="Measure",
                        report="Executive",
                        page="Finance",
                        visual_type="lineClusteredColumnComboChart",
                        visual_title="Revenue trend",
                        visual_id="VisualContainer1",
                        context="Formatting",
                        source_path="objects.title.properties.text",
                        artifact_kind="Visual",
                        artifact_path="definition/pages/Page1/visuals/VisualContainer1/visual.json",
                    )
                ],
                "removal_risk": "Caution",
            }
        ],
        "summary": {
            "total_measures": 1,
            "total_columns": 0,
            "total_calc_columns": 0,
            "used_in_visuals": 1,
            "used_relationship": 0,
            "used_rls": 0,
            "used_key_column": 0,
            "used_hierarchy": 0,
            "used_sort_column": 0,
            "indirect": 0,
            "not_used": 0,
            "total_usage_refs": 1,
            "models": ["Sales.SemanticModel"],
            "reports": ["Executive"],
            "tables": {},
        },
        "table_summaries": [],
        "warnings": [],
    }

    payload = web_app._serialize_results(results)

    usage_detail = payload["items"][0]["usageDetails"][0]
    assert usage_detail["visualId"] == "VisualContainer1"
    assert usage_detail["artifactKind"] == "Visual"
    assert usage_detail["artifactPath"] == "definition/pages/Page1/visuals/VisualContainer1/visual.json"
    assert usage_detail["sourcePath"] == "objects.title.properties.text"

    reference = payload["references"][0]
    assert reference["visualId"] == "VisualContainer1"
    assert reference["artifactKind"] == "Visual"
    assert reference["artifactPath"] == "definition/pages/Page1/visuals/VisualContainer1/visual.json"
    assert reference["sourcePath"] == "objects.title.properties.text"


def test_serialize_results_marks_stale_only_usage_and_stale_details():
    results = {
        "items": [
            {
                "item": analyzer.ModelItem(
                    item_type="Measure",
                    table="_Measures",
                    name="Revenue LY",
                ),
                "status": "NOT USED",
                "usages": [],
                "stale_usages": [
                    analyzer.UsageRef(
                        table="_Measures",
                        name="Revenue LY",
                        ref_type="metadata",
                        report="Linden Report",
                        page="FINANCE",
                        visual_type="lineClusteredColumnComboChart",
                        visual_title="Trend",
                        visual_id="5d2afbc25ca3d1f2ceb0",
                        context="Stale Formatting",
                        source_path="visual.objects.labels.[1].selector.metadata",
                        artifact_kind="Visual",
                        artifact_path="definition/pages/c5df0ff5fdb8f21f2629/visuals/5d2afbc25ca3d1f2ceb0/visual.json",
                        selector_value="_Measures.Revenue LY",
                        is_stale=True,
                    )
                ],
                "removal_risk": "Safe",
            }
        ],
        "summary": {
            "total_measures": 1,
            "total_columns": 0,
            "total_calc_columns": 0,
            "used_in_visuals": 0,
            "used_relationship": 0,
            "used_rls": 0,
            "used_key_column": 0,
            "used_hierarchy": 0,
            "used_sort_column": 0,
            "indirect": 0,
            "not_used": 1,
            "total_usage_refs": 0,
            "models": ["Sales.SemanticModel"],
            "reports": ["Linden Report"],
            "tables": {},
        },
        "table_summaries": [],
        "warnings": [],
    }

    payload = web_app._serialize_results(results)
    item = payload["items"][0]
    assert item["usageState"] == "Stale only"
    assert item["issueState"] == "Stale"
    assert item["deleteSafety"] == "Safe"
    assert item["staleUsageCount"] == 1
    assert item["staleUsageDetails"][0]["selectorValue"] == "_Measures.Revenue LY"
    stale_reference = next(ref for ref in payload["references"] if ref["isStale"])
    assert stale_reference["context"] == "Stale Formatting"


def test_api_serialization_groups_report_health_workflow():
    results = _fake_results()
    unsupported_reason = (
        "Unsupported Metadata: Perspectives in definition/perspectives/Executive.tmdl "
        "can reference Sales[Revenue]. Hidden dependency: perspective membership may "
        "keep this field available outside scanned report visuals. User harm: deleting "
        "it could break curated perspective views."
    )
    results["report_issues"] = [
        {
            "severity": "error",
            "issueType": "invalid_report_json",
            "report": "Executive",
            "page": "Overview",
            "visualId": "Visual1",
            "artifactKind": "Visual",
            "artifactPath": "definition/pages/Page1/visuals/Visual1/visual.json",
            "message": "Could not parse PBIR JSON file.",
        },
        {
            "severity": "warning",
            "issueType": "invalid_report_extension_measure",
            "report": "Executive",
            "page": "",
            "visualId": "",
            "artifactKind": "Report Extension",
            "artifactPath": "definition/reportExtensions.json",
            "message": "Report extension measure is missing required field 'dataType'.",
        },
    ]
    results["items"][0]["removal_risk"] = "Review"
    results["items"][0]["review_triggers"] = [unsupported_reason]
    results["items"][0]["stale_usages"] = [
        analyzer.UsageRef(
            table="Sales",
            name="Revenue",
            ref_type="metadata",
            report="Executive",
            page="Overview",
            visual_type="card",
            visual_title="Revenue",
            visual_id="Visual1",
            context="Stale Formatting",
            source_path="visual.objects.labels.[1].selector.metadata",
            artifact_kind="Visual",
            artifact_path="definition/pages/Page1/visuals/Visual1/visual.json",
            selector_value="Sales.Revenue",
            is_stale=True,
        )
    ]

    payload = web_app._serialize_results(results)

    health = payload["reportHealth"]
    assert health["totalIssueCount"] == 4
    assert [group["key"] for group in health["groups"]] == [
        "invalid_pbir_json",
        "report_extension_metadata",
        "stale_report_references",
        "unsupported_metadata",
    ]
    stale_group = next(group for group in health["groups"] if group["key"] == "stale_report_references")
    assert stale_group["count"] == 1
    assert stale_group["action"] == {
        "type": "cleanup_stale",
        "label": "Preview stale cleanup",
        "entryCount": 1,
    }
    unsupported_group = next(group for group in health["groups"] if group["key"] == "unsupported_metadata")
    assert unsupported_group["items"][0]["reviewTriggers"] == [unsupported_reason]


def test_api_analyze_rejects_multiple_models(monkeypatch, tmp_path):
    model_a = tmp_path / "Sales.SemanticModel"
    model_b = tmp_path / "Finance.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    model_a.mkdir()
    model_b.mkdir()
    report_path.mkdir()

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_a), str(model_b)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert "exactly one semantic model" in payload["error"]


def test_api_analyze_includes_review_triggers(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    model_path.mkdir()
    report_path.mkdir()

    monkeypatch.setattr(web_app.analyzer, "analyze", lambda **_: _fake_review_results())

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["items"][0]["removalRisk"] == "Review"
    assert payload["items"][0]["reviewTriggers"] == ["Item is hidden"]
    assert payload["references"][0]["reviewTriggers"] == ["Item is hidden"]


def test_api_serialization_preserves_unsupported_metadata_review_reason():
    results = _fake_results()
    reason = (
        "Unsupported Metadata: Perspectives in definition/perspectives/Executive.tmdl "
        "can reference Sales[Revenue]. Hidden dependency: perspective membership may "
        "keep this field available outside scanned report visuals. User harm: deleting "
        "it could break curated perspective views."
    )
    results["items"][0]["removal_risk"] = "Review"
    results["items"][0]["review_triggers"] = [reason]
    results["table_summaries"][0]["items"][0]["removal_risk"] = "Review"
    results["table_summaries"][0]["items"][0]["review_triggers"] = [reason]

    payload = web_app._serialize_results(results)

    assert payload["items"][0]["removalRisk"] == "Review"
    assert payload["items"][0]["deleteSafety"] == "Review"
    assert payload["items"][0]["reviewTriggers"] == [reason]
    assert payload["references"][0]["reviewTriggers"] == [reason]
    assert payload["tables"][0]["items"][0]["reviewTriggers"] == [reason]


def test_api_analyze_returns_report_health_issues(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    tables_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n",
        encoding="utf-8",
    )
    (report_path / "definition" / "pages" / "Page1" / "page.json").write_text(
        json.dumps({"displayName": "Overview"}),
        encoding="utf-8",
    )
    (visual_dir / "visual.json").write_text("{ bad json", encoding="utf-8")

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reportIssues"][0]["issueType"] == "invalid_report_json"
    assert payload["reportIssues"][0]["artifactKind"] == "Visual"
    assert payload["reportIssues"][0]["artifactPath"] == "definition/pages/Page1/visuals/Visual1/visual.json"
    assert payload["reportHealth"]["groups"][0]["key"] == "invalid_pbir_json"
    assert payload["reportHealth"]["groups"][0]["count"] == 1


def test_api_analyze_product_qa_workspace_exposes_report_health_groups():
    model_path = PRODUCT_QA_WORKSPACE_DIR / "Models" / "ProductQA.SemanticModel"
    report_path = PRODUCT_QA_WORKSPACE_DIR / "Reports" / "Executive.Report"

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    health_keys = {group["key"] for group in payload["reportHealth"]["groups"]}
    assert {
        "stale_report_references",
        "broken_model_references",
        "unsupported_metadata",
        "invalid_pbir_json",
    } <= health_keys
    assert any(
        item["table"] == "Report Metrics"
        and item["name"] == "Report Margin"
        and item["sourceKind"] == "report"
        for item in payload["items"]
    )
    assert any(
        item["table"] == "Sales"
        and item["name"] == "Cleanup Note"
        and item["deleteSafety"] == "Safe"
        for item in payload["items"]
    )


def test_api_analyze_rejects_tmsl_model_bim_with_clear_message(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    model_path.mkdir()
    report_path.mkdir()
    (model_path / "model.bim").write_text("{}", encoding="utf-8")
    (model_path / "definition.pbism").write_text('{"version":"4.0"}', encoding="utf-8")
    (report_path / "definition.pbir").write_text('{"version":"4.0"}', encoding="utf-8")

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "TMSL/model.bim" in error
    assert "Convert the Semantic Model to TMDL" in error


def test_api_compare_returns_model_to_model_diffs(tmp_path):
    baseline_model = tmp_path / "Baseline.SemanticModel"
    candidate_model = tmp_path / "Candidate.SemanticModel"
    baseline_tables_dir = baseline_model / "definition" / "tables"
    candidate_tables_dir = candidate_model / "definition" / "tables"
    baseline_tables_dir.mkdir(parents=True)
    candidate_tables_dir.mkdir(parents=True)

    (baseline_tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: Amount\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\t\tdisplayFolder: Finance\n"
        "\tmeasure Obsolete = 1\n",
        encoding="utf-8",
    )
    (baseline_tables_dir / "Legacy.tmdl").write_text(
        "table Legacy\n"
        "\tcolumn LegacyKey\n",
        encoding="utf-8",
    )
    (candidate_tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\t\tsourceColumn: Amount\n"
        "\t\thidden\n"
        "\tmeasure Revenue = SUMX(Sales, Sales[Amount])\n"
        "\t\tdisplayFolder: Executive\n"
        "\t\tisHidden: true\n"
        "\tmeasure 'New Margin' = DIVIDE([Revenue], 100)\n",
        encoding="utf-8",
    )
    (candidate_tables_dir / "Store.tmdl").write_text(
        "table Store\n"
        "\tcolumn StoreKey\n",
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/compare",
        json={
            "baseline_model_path": str(baseline_model),
            "candidate_model_path": str(candidate_model),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["tables"] == {
        "added": 1,
        "removed": 1,
        "changed": 0,
        "unchanged": 1,
    }
    assert payload["summary"]["measures"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 0,
    }
    assert payload["summary"]["columns"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 0,
    }
    assert payload["summary"]["totalDifferences"] == 8

    revenue_diff = next(
        diff for diff in payload["diffs"]
        if diff["category"] == "measures" and diff["table"] == "Sales" and diff["name"] == "Revenue"
    )
    assert revenue_diff["status"] == "changed"
    assert revenue_diff["properties"] == [
        {"name": "expression", "baseline": "SUM(Sales[Amount])", "candidate": "SUMX(Sales, Sales[Amount])"},
        {"name": "displayFolder", "baseline": "Finance", "candidate": "Executive"},
        {"name": "isHidden", "baseline": False, "candidate": True},
    ]

    amount_diff = next(
        diff for diff in payload["diffs"]
        if diff["category"] == "columns" and diff["table"] == "Sales" and diff["name"] == "Amount"
    )
    assert amount_diff["properties"] == [
        {"name": "dataType", "baseline": "int64", "candidate": "decimal"},
        {"name": "isHidden", "baseline": False, "candidate": True},
    ]
    assert any(diff["category"] == "tables" and diff["status"] == "added" and diff["table"] == "Store" for diff in payload["diffs"])
    assert any(diff["category"] == "tables" and diff["status"] == "removed" and diff["table"] == "Legacy" for diff in payload["diffs"])


def test_api_compare_export_downloads_review_formats(tmp_path):
    baseline_model = tmp_path / "Baseline.SemanticModel"
    candidate_model = tmp_path / "Candidate.SemanticModel"
    baseline_tables_dir = baseline_model / "definition" / "tables"
    candidate_tables_dir = candidate_model / "definition" / "tables"
    baseline_tables_dir.mkdir(parents=True)
    candidate_tables_dir.mkdir(parents=True)
    (baseline_tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\t\tdisplayFolder: Finance\n",
        encoding="utf-8",
    )
    (candidate_tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tmeasure Revenue = SUMX(Sales, Sales[Amount])\n"
        "\t\tdisplayFolder: Executive\n"
        "\t\tisHidden: true\n",
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    compare_response = client.post(
        "/api/compare",
        json={
            "baseline_model_path": str(baseline_model),
            "candidate_model_path": str(candidate_model),
        },
    )
    assert compare_response.status_code == 200

    markdown = client.get("/api/compare/export?format=md")
    assert markdown.status_code == 200
    assert markdown.headers["Content-Disposition"].endswith('filename=Baseline_vs_Candidate_model_compare.md')
    markdown_text = markdown.get_data(as_text=True)
    assert "# Semantic Model Compare: Baseline -> Candidate" in markdown_text
    assert "| Measures | 0 | 0 | 1 | 0 |" in markdown_text
    assert "Sales[Revenue]" in markdown_text
    assert "displayFolder" in markdown_text

    csv_response = client.get("/api/compare/export?format=csv")
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert "category,status,type,table,name,property,baseline,candidate" in csv_text
    assert "measures,changed,Measure,Sales,Revenue,expression,SUM(Sales[Amount]),\"SUMX(Sales, Sales[Amount])\"" in csv_text

    json_response = client.get("/api/compare/export?format=json")
    assert json_response.status_code == 200
    json_payload = json.loads(json_response.get_data(as_text=True))
    assert json_payload["summary"]["totalDifferences"] == 1
    assert json_payload["diffs"][0]["properties"][0]["name"] == "expression"


def test_api_compare_export_requires_compare_results():
    previous_results = web_app._state.get("last_compare_results")
    web_app._state["last_compare_results"] = None
    try:
        client = web_app.app.test_client()
        response = client.get("/api/compare/export?format=json")

        assert response.status_code == 400
        assert "No compare results available" in response.get_json()["error"]
    finally:
        web_app._state["last_compare_results"] = previous_results


def test_api_cleanup_stale_report_metadata_can_preview_without_writing(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
                "name": "Visual1",
                "position": {"x": 0, "y": 0, "z": 0, "height": 100, "width": 100},
                "visual": {
                    "query": {"queryState": {"Values": {"projections": []}}},
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "Sales.Revenue"}},
                            {"selector": {"metadata": "Sales.Obsolete Revenue"}},
                        ]
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    before = visual_file.read_text(encoding="utf-8")

    client = web_app.app.test_client()
    response = client.post(
        "/api/report/cleanup-stale",
        json={
            "dry_run": True,
            "entries": [
                {
                    "report_path": str(report_path),
                    "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                    "selector_value": "Sales.Obsolete Revenue",
                    "source_path": "visual.objects.labels.[1].selector.metadata",
                    "stale_kind": "",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["dry_run"] is True
    assert payload["removed_count"] == 1
    assert payload["result"]["updated_files"] == [str(visual_file.resolve())]
    assert visual_file.read_text(encoding="utf-8") == before


def test_api_cleanup_stale_report_metadata_preview_matches_apply(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
                "name": "Visual1",
                "position": {"x": 0, "y": 0, "z": 0, "height": 100, "width": 100},
                "visual": {
                    "query": {"queryState": {"Values": {"projections": []}}},
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "Sales.Revenue"}},
                            {"selector": {"metadata": "Sales.Obsolete Revenue"}},
                        ]
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    entries = [
        {
            "report_path": str(report_path),
            "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
            "selector_value": "Sales.Obsolete Revenue",
            "source_path": "visual.objects.labels.[1].selector.metadata",
            "stale_kind": "",
        }
    ]

    client = web_app.app.test_client()
    preview = client.post(
        "/api/report/cleanup-stale",
        json={"dry_run": True, "entries": entries},
    ).get_json()
    apply = client.post(
        "/api/report/cleanup-stale",
        json={"entries": entries},
    ).get_json()

    assert preview["result"]["dry_run"] is True
    assert apply["result"]["dry_run"] is False
    assert apply["removed_count"] == preview["removed_count"] == 1
    assert apply["result"]["removed_entries"] == preview["result"]["removed_entries"]
    updated_payload = json.loads(visual_file.read_text(encoding="utf-8"))
    labels = updated_payload["visual"]["objects"]["labels"]
    assert labels == [{"selector": {"metadata": "Sales.Revenue"}}]


def test_api_analyze_exposes_table_permission_rls_usage(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    roles_dir = model_path / "definition" / "roles"
    tables_dir.mkdir(parents=True)
    roles_dir.mkdir(parents=True)
    (report_path / "definition").mkdir(parents=True)
    (tables_dir / "Store.tmdl").write_text(
        "table Store\n"
        "\tcolumn 'Store Code'\n"
        "\t\tdataType: int64\n",
        encoding="utf-8",
    )
    (roles_dir / "Store Role.tmdl").write_text(
        "role 'Store Role'\n"
        "\tmodelPermission: read\n"
        "\ttablePermission Store = 'Store'[Store Code] IN {1, 10}\n",
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    store_code = payload["items"][0]
    assert store_code["statusDetail"] == "USED (RLS: Store Role)"
    assert store_code["usageState"] == "Indirect"
    assert store_code["deleteSafety"] == "Blocked"
    assert store_code["otherModelUses"] == ["RLS"]


def test_api_analyze_returns_model_item_source_file(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    report_path.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n",
        encoding="utf-8",
    )
    split_file = tables_dir / "Sales.Measures.tmdl"
    split_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    revenue = next(item for item in payload["items"] if item["table"] == "Sales" and item["name"] == "Revenue")
    reference = next(ref for ref in payload["references"] if ref["table"] == "Sales" and ref["name"] == "Revenue")
    assert revenue["sourceFile"] == str(split_file)
    assert reference["sourceFile"] == str(split_file)


def test_api_analyze_includes_m_source_details_for_regular_columns(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    report_path.mkdir()
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Region\n"
        "\tpartition Sales = import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        "\t\t\t\tSource = #table({\"Region\"}, {{\"US\"}})\n"
        "\t\t\tin\n"
        "\t\t\t\tSource\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app.analyzer, "analyze", lambda **_: _fake_column_results())

    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(model_path)],
            "report_paths": [str(report_path)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["items"][0]["daxExpression"] is None
    assert "Source = #table" in payload["items"][0]["mSourceDetails"]


def test_api_dax_updates_expression(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    model_path.mkdir()
    captured = {}

    def fake_set_dax_expression(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "file": "x", "action": "set_dax_expression"}

    monkeypatch.setattr(web_app.tmdl_writer, "set_dax_expression", fake_set_dax_expression)
    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/dax",
        json={
            "model_path": str(model_path),
            "table": "Sales",
            "name": "Revenue",
            "item_type": "Measure",
            "dax_expression": "SUM(Sales[Amount])",
            "sourceFile": "/tmp/Sales.Measures.tmdl",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["ok"] is True
    assert captured["table"] == "Sales"
    assert captured["name"] == "Revenue"
    assert captured["item_type"] == "Measure"
    assert captured["dax_expression"] == "SUM(Sales[Amount])"
    assert captured["source_file"] == "/tmp/Sales.Measures.tmdl"


def test_api_action_accepts_move_to_table_group(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_apply_actions(passed_model_path, actions):
        captured["model_path"] = passed_model_path
        captured["actions"] = actions
        return [{"ok": True, "action": "move_to_table_group", "table": "Sales", "name": "Sales", "item_type": "Table"}]

    monkeypatch.setattr(web_app.tmdl_writer, "apply_actions", fake_apply_actions)
    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/action",
        json={
            "model_path": str(model_path),
            "actions": [
                {
                    "action": "move_to_table_group",
                    "table": "Sales",
                    "name": "Sales",
                    "item_type": "Table",
                    "table_group": "PNL Actuals",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["results"][0]["ok"] is True
    assert captured["model_path"] == model_path
    assert captured["actions"][0]["table_group"] == "PNL Actuals"


def test_api_action_returns_batch_errors_without_partial_write(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/action",
        json={
            "model_path": str(model_path),
            "actions": [
                {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
                {"action": "hide", "table": "Sales", "name": "Missing", "item_type": "Measure"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert len(payload["errors"]) == 2
    assert payload["results"][0]["skipped"] is True
    assert "\t\tisHidden" not in sales_file.read_text(encoding="utf-8")


def test_api_action_preview_returns_plan_without_writing(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/action/preview",
        json={
            "model_path": str(model_path),
            "create_backup": True,
            "auto_refresh": False,
            "actions": [
                {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["plan"]["dry_run"] is True
    assert payload["plan"]["written"] is False
    assert payload["plan"]["create_backup"] is True
    assert payload["plan"]["backup"]["mode"] == "will_create_before_apply"
    assert payload["plan"]["auto_refresh"] is False
    assert payload["plan"]["action_count"] == 1
    assert payload["plan"]["affected_files"] == [str(sales_file)]
    assert payload["plan"]["actions"][0]["label"] == "Hide"
    assert "\t\tisHidden" not in sales_file.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("Sales.SemanticModel_backup_*"))


def test_api_action_preview_reports_invalid_batch_without_writing(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/action/preview",
        json={
            "model_path": str(model_path),
            "actions": [
                {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
                {"action": "hide", "table": "Sales", "name": "Missing", "item_type": "Measure"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["plan"]["valid_action_count"] == 1
    assert payload["plan"]["invalid_action_count"] == 1
    assert "Missing" in payload["errors"][0]
    assert "\t\tisHidden" not in sales_file.read_text(encoding="utf-8")


def test_api_action_does_not_create_backup_when_plan_is_invalid(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )
    web_app._state["backup_path"] = None

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/action",
        json={
            "model_path": str(model_path),
            "create_backup": True,
            "actions": [
                {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
                {"action": "hide", "table": "Sales", "name": "Missing", "item_type": "Measure"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["backup_path"] is None
    assert payload["plan"]["ok"] is False
    assert not list(tmp_path.glob("Sales.SemanticModel_backup_*"))
    assert "\t\tisHidden" not in sales_file.read_text(encoding="utf-8")


def test_api_action_creates_backup_for_each_requested_apply(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )
    web_app._state["backup_path"] = None

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    first = client.post(
        "/api/action",
        json={
            "model_path": str(model_path),
            "create_backup": True,
            "actions": [
                {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
            ],
        },
    ).get_json()
    second = client.post(
        "/api/action",
        json={
            "model_path": str(model_path),
            "create_backup": True,
            "actions": [
                {"action": "unhide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
            ],
        },
    ).get_json()

    assert first["backup_path"]
    assert second["backup_path"]
    assert first["backup_path"] != second["backup_path"]


def test_api_migrate_report_measure_promotes_extension_to_model(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    report_def_dir = report_path / "definition"
    tables_dir.mkdir(parents=True)
    report_def_dir.mkdir(parents=True)
    web_app._state["backup_path"] = None

    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tmeasure Existing = 1\n",
        encoding="utf-8",
    )
    (report_def_dir / "reportExtensions.json").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json",
                "name": "extension",
                "entities": [
                    {
                        "name": "Sales",
                        "measures": [
                            {
                                "name": "Report Revenue",
                                "dataType": "Double",
                                "expression": "[Existing] + 1",
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/report-measure/migrate",
        json={
            "model_path": str(model_path),
            "report_path": str(report_path),
            "table": "Sales",
            "name": "Report Revenue",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["ok"] is True
    assert "\tmeasure 'Report Revenue' = [Existing] + 1" in (tables_dir / "Sales.tmdl").read_text(encoding="utf-8")
    updated_extensions = json.loads((report_def_dir / "reportExtensions.json").read_text(encoding="utf-8"))
    assert updated_extensions["entities"] == []


def test_api_move_measure_updates_only_selected_reports(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    selected_report = tmp_path / "Selected.Report"
    unselected_report = tmp_path / "Unselected.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "_Measures.tmdl").write_text(
        "table _Measures\n"
        "\tmeasure 'Revenue LY' = 1\n",
        encoding="utf-8",
    )
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n",
        encoding="utf-8",
    )

    for report_path in (selected_report, unselected_report):
        visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
        visual_dir.mkdir(parents=True)
        (visual_dir / "visual.json").write_text(
            json.dumps(
                {
                    "visual": {
                        "query": {
                            "queryState": {
                                "Y": {
                                    "projections": [
                                        {
                                            "field": {
                                                "Measure": {
                                                    "Expression": {"SourceRef": {"Entity": "_Measures"}},
                                                    "Property": "Revenue LY",
                                                }
                                            },
                                            "queryRef": "_Measures.Revenue LY",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    dry_run = client.post(
        "/api/measure/move",
        json={
            "model_path": str(model_path),
            "report_paths": [str(selected_report)],
            "moves": [{"table": "_Measures", "name": "Revenue LY", "target_table": "Sales"}],
            "dry_run": True,
        },
    )
    assert dry_run.status_code == 200
    assert dry_run.get_json()["report_result"]["updated_reference_count"] == 2
    assert "\tmeasure 'Revenue LY'" in (tables_dir / "_Measures.tmdl").read_text(encoding="utf-8")

    response = client.post(
        "/api/measure/move",
        json={
            "model_path": str(model_path),
            "report_paths": [str(selected_report)],
            "moves": [{"table": "_Measures", "name": "Revenue LY", "target_table": "Sales"}],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["selected_report_count"] == 1
    assert "\tmeasure 'Revenue LY'" not in (tables_dir / "_Measures.tmdl").read_text(encoding="utf-8")
    assert "\tmeasure 'Revenue LY' = 1" in (tables_dir / "Sales.tmdl").read_text(encoding="utf-8")

    selected_visual = json.loads(
        (selected_report / "definition" / "pages" / "Page1" / "visuals" / "Visual1" / "visual.json").read_text(
            encoding="utf-8"
        )
    )
    unselected_visual = json.loads(
        (unselected_report / "definition" / "pages" / "Page1" / "visuals" / "Visual1" / "visual.json").read_text(
            encoding="utf-8"
        )
    )
    selected_projection = selected_visual["visual"]["query"]["queryState"]["Y"]["projections"][0]
    unselected_projection = unselected_visual["visual"]["query"]["queryState"]["Y"]["projections"][0]
    assert selected_projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Sales"
    assert selected_projection["queryRef"] == "Sales.Revenue LY"
    assert unselected_projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "_Measures"
    assert unselected_projection["queryRef"] == "_Measures.Revenue LY"


def test_api_rename_model_metadata_updates_selected_reports_only(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    selected_report = tmp_path / "Selected.Report"
    unselected_report = tmp_path / "Unselected.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (model_path / "definition" / "model.tmdl").write_text(
        "model Model\n"
        "ref table Sales\n",
        encoding="utf-8",
    )

    for report_path in (selected_report, unselected_report):
        visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
        visual_dir.mkdir(parents=True)
        (visual_dir / "visual.json").write_text(
            json.dumps(
                {
                    "visual": {
                        "query": {
                            "queryState": {
                                "Y": {
                                    "projections": [
                                        {
                                            "field": {
                                                "Measure": {
                                                    "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                    "Property": "Revenue",
                                                }
                                            },
                                            "queryRef": "Sales.Revenue",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/model/rename",
        json={
            "model_path": str(model_path),
            "report_paths": [str(selected_report)],
            "table_renames": [{"table": "Sales", "target_table": "Fact Sales"}],
            "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["selected_report_count"] == 1
    assert not (tables_dir / "Sales.tmdl").exists()
    assert "measure 'Net Revenue'" in (tables_dir / "Fact Sales.tmdl").read_text(encoding="utf-8")

    selected_visual = json.loads(
        (selected_report / "definition" / "pages" / "Page1" / "visuals" / "Visual1" / "visual.json").read_text(
            encoding="utf-8"
        )
    )
    unselected_visual = json.loads(
        (unselected_report / "definition" / "pages" / "Page1" / "visuals" / "Visual1" / "visual.json").read_text(
            encoding="utf-8"
        )
    )
    selected_projection = selected_visual["visual"]["query"]["queryState"]["Y"]["projections"][0]
    unselected_projection = unselected_visual["visual"]["query"]["queryState"]["Y"]["projections"][0]
    assert selected_projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Fact Sales"
    assert selected_projection["field"]["Measure"]["Property"] == "Net Revenue"
    assert selected_projection["queryRef"] == "Fact Sales.Net Revenue"
    assert unselected_projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Sales"
    assert unselected_projection["field"]["Measure"]["Property"] == "Revenue"
    assert unselected_projection["queryRef"] == "Sales.Revenue"


def test_api_move_measure_rolls_back_model_when_report_apply_fails(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (report_path / "definition").mkdir(parents=True)
    measures_file = tables_dir / "_Measures.tmdl"
    sales_file = tables_dir / "Sales.tmdl"
    measures_file.write_text(
        "table _Measures\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n",
        encoding="utf-8",
    )
    original_measures = measures_file.read_text(encoding="utf-8")
    original_sales = sales_file.read_text(encoding="utf-8")

    def fake_report_rewrite(*, dry_run=False, **_kwargs):
        if dry_run:
            return {"ok": True, "updated_reference_count": 1, "updated_files": [{"file": "visual.json"}]}
        return {"ok": False, "error": "Report write failed"}

    monkeypatch.setattr(web_app.report_writer, "rewrite_measure_table_references", fake_report_rewrite)
    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/measure/move",
        json={
            "model_path": str(model_path),
            "report_paths": [str(report_path)],
            "moves": [{"table": "_Measures", "name": "Revenue", "target_table": "Sales"}],
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["rolled_back"] is True
    assert payload["report_result"]["error"] == "Report write failed"
    assert measures_file.read_text(encoding="utf-8") == original_measures
    assert sales_file.read_text(encoding="utf-8") == original_sales


def test_api_rename_model_metadata_rolls_back_model_when_report_apply_fails(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (report_path / "definition").mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    model_file = model_path / "definition" / "model.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    model_file.write_text(
        "model Model\n"
        "ref table Sales\n",
        encoding="utf-8",
    )
    original_sales = sales_file.read_text(encoding="utf-8")
    original_model = model_file.read_text(encoding="utf-8")

    def fake_report_rewrite(*, dry_run=False, **_kwargs):
        if dry_run:
            return {"ok": True, "updated_reference_count": 1, "updated_files": [{"file": "visual.json"}]}
        return {"ok": False, "error": "Report write failed"}

    monkeypatch.setattr(web_app.report_writer, "rewrite_model_reference_changes", fake_report_rewrite)
    monkeypatch.setattr(web_app.tmdl_writer, "check_git_dirty", lambda _: None)

    client = web_app.app.test_client()
    response = client.post(
        "/api/model/rename",
        json={
            "model_path": str(model_path),
            "report_paths": [str(report_path)],
            "table_renames": [{"table": "Sales", "target_table": "Fact Sales"}],
            "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}],
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["rolled_back"] is True
    assert payload["report_result"]["error"] == "Report write failed"
    assert sales_file.exists()
    assert sales_file.read_text(encoding="utf-8") == original_sales
    assert model_file.read_text(encoding="utf-8") == original_model
    assert not (tables_dir / "Fact Sales.tmdl").exists()


def test_api_rename_model_metadata_returns_report_validation_errors(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    tables_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (model_path / "definition" / "model.tmdl").write_text(
        "model Model\n"
        "ref table Sales\n",
        encoding="utf-8",
    )
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
                "name": "Visual1",
                "visual": {
                    "query": {
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                "Property": "Revenue",
                                            }
                                        },
                                        "queryRef": "Sales.Revenue",
                                    }
                                ]
                            }
                        }
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/model/rename",
        json={
            "model_path": str(model_path),
            "report_paths": [str(report_path)],
            "table_renames": [{"table": "Sales", "target_table": "Fact Sales"}],
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "PBIR validation failed"
    assert payload["validation_errors"][0]["file"] == str(visual_file)
    assert "position" in payload["validation_errors"][0]["message"]
    assert "Fact Sales" not in visual_file.read_text(encoding="utf-8")


def test_api_find_connected_reports_resolves_definition_pbir_by_path(tmp_path):
    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    reports_root = tmp_path / "Reports"
    connected = reports_root / "Executive.Report"
    false_positive = reports_root / "Nested" / "False Positive.Report"
    connected.mkdir(parents=True)
    false_positive.mkdir(parents=True)
    (connected / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../../Models/Sales.SemanticModel"}}}),
        encoding="utf-8",
    )
    (false_positive / "definition.pbir").write_text(
        json.dumps({
            "datasetReference": {"byPath": {"path": "../Models/Sales.SemanticModel"}},
            "note": "The selected Sales.SemanticModel appears here but this relative path points elsewhere.",
        }),
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={
            "model_path": str(model_path),
            "search_root": str(reports_root),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model_name"] == "Sales"
    assert payload["scanned_definition_files"] == 2
    assert [report["path"] for report in payload["reports"]] == [str(connected.resolve())]
    assert payload["reports"][0]["status"] == "connected"
    assert "definition.pbir" in payload["reports"][0]["definitionFiles"][0]
    assert any(
        status["path"] == str(false_positive.resolve()) and status["status"] == "not_connected"
        for status in payload["reportStatuses"]
    )


def test_api_find_connected_reports_marks_by_connection_reports_as_remote(tmp_path):
    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    reports_root = tmp_path / "Reports"
    remote = reports_root / "Remote.Report"
    remote.mkdir(parents=True)
    (remote / "definition.pbir").write_text(
        json.dumps({
            "datasetReference": {
                "byConnection": {
                    "connectionString": "Data Source=powerbi://api.powerbi.com/v1.0/myorg/Sales",
                    "pbiServiceModelId": "00000000-0000-0000-0000-000000000000",
                }
            }
        }),
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={
            "model_path": str(model_path),
            "search_root": str(reports_root),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reports"] == []
    remote_status = next(status for status in payload["reportStatuses"] if status["path"] == str(remote.resolve()))
    assert remote_status["status"] == "remote"
    assert "cannot be verified against a local Semantic Model path" in remote_status["message"]
    assert any("Remote.Report" in warning and "remote" in warning for warning in payload["warnings"])


def test_api_find_connected_reports_reports_invalid_definition_pbir(tmp_path):
    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    reports_root = tmp_path / "Reports"
    invalid = reports_root / "Invalid.Report"
    invalid.mkdir(parents=True)
    (invalid / "definition.pbir").write_text('{"datasetReference": ', encoding="utf-8")

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={
            "model_path": str(model_path),
            "search_root": str(reports_root),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reports"] == []
    invalid_status = next(status for status in payload["reportStatuses"] if status["path"] == str(invalid.resolve()))
    assert invalid_status["status"] == "invalid_definition"
    assert "Invalid definition.pbir JSON" in invalid_status["message"]
    assert any("Invalid.Report" in warning and "Invalid definition.pbir JSON" in warning for warning in payload["warnings"])


def test_api_find_connected_reports_reports_missing_dataset_reference(tmp_path):
    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    reports_root = tmp_path / "Reports"
    missing_reference = reports_root / "Missing Reference.Report"
    missing_reference.mkdir(parents=True)
    (missing_reference / "definition.pbir").write_text(json.dumps({"version": "4.0"}), encoding="utf-8")

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={
            "model_path": str(model_path),
            "search_root": str(reports_root),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reports"] == []
    missing_status = next(
        status for status in payload["reportStatuses"] if status["path"] == str(missing_reference.resolve())
    )
    assert missing_status["status"] == "missing_dataset_reference"
    assert "datasetReference.byPath.path" in missing_status["message"]
    assert any(
        "Missing Reference.Report" in warning and "datasetReference.byPath.path" in warning
        for warning in payload["warnings"]
    )


def test_api_find_connected_reports_reports_missing_definition_pbir(tmp_path):
    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    reports_root = tmp_path / "Reports"
    missing_definition = reports_root / "Missing Definition.Report"
    missing_definition.mkdir(parents=True)

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={
            "model_path": str(model_path),
            "search_root": str(reports_root),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reports"] == []
    assert payload["scanned_definition_files"] == 0
    missing_status = next(
        status for status in payload["reportStatuses"] if status["path"] == str(missing_definition.resolve())
    )
    assert missing_status["status"] == "missing_definition"
    assert "Missing definition.pbir" in missing_status["message"]
    assert any(
        "Missing Definition.Report" in warning and "Missing definition.pbir" in warning
        for warning in payload["warnings"]
    )


def test_api_export_json_returns_latest_analysis():
    web_app._state["last_results"] = _fake_results()

    client = web_app.app.test_client()
    response = client.get("/api/export?format=json")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert "Sales_usage_analysis.json" in response.headers["Content-Disposition"]
    payload = response.get_json()
    assert payload["summary"]["models"] == ["Sales.SemanticModel"]
    assert payload["warnings"][0]["code"] == "AMBIGUOUS_NAMEOF_TARGET"


def test_api_export_xlsx_returns_attachment(monkeypatch):
    web_app._state["last_results"] = _fake_results()
    monkeypatch.setattr(web_app.analyzer, "create_xlsx_bytes", lambda results: b"PK\x03\x04fake-xlsx")

    client = web_app.app.test_client()
    response = client.get("/api/export?format=xlsx")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "Sales_usage_analysis.xlsx" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"PK")


def test_api_export_requires_prior_analysis():
    web_app._state["last_results"] = None

    client = web_app.app.test_client()
    response = client.get("/api/export?format=json")

    assert response.status_code == 400
    assert "Run analysis first" in response.get_json()["error"]


def test_api_export_rejects_unknown_format():
    web_app._state["last_results"] = _fake_results()

    client = web_app.app.test_client()
    response = client.get("/api/export?format=bad")

    assert response.status_code == 400
    assert "Unsupported export format" in response.get_json()["error"]


def test_index_renders_empty_selection_state():
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "No model selected" in html
    assert "No reports selected" in html
    assert 'data-view="tables"' in html
    assert 'data-view="reports"' in html
    assert 'id="reportsTableSection"' in html
    assert 'data-reportcol="severity"' in html
    assert 'data-reportcol="visualTitle"' in html
    assert 'id="reportIssueCategoryButtons"' in html
    assert 'id="reportIssueReportSelect"' in html
    assert 'id="reportIssuePageSelect"' in html
    assert 'id="checkAllReportIssues"' in html
    assert 'id="btnApplyReportSuggestionsShown"' in html
    assert 'id="btnRemoveReportIssuesShown"' in html
    assert 'id="btnCleanStaleShown"' in html
    assert 'id="btnCleanAllCleanup"' in html
    assert "Apply selected" in html
    assert "Remove selected" in html
    assert "Clean selected cleanup" in html
    assert "Clean all cleanup" in html
    assert "function applyReportIssueFilters() {" in html
    assert "function reportIssueKey(issue) {" in html
    assert "function getSelectedReportIssues() {" in html
    assert "function isReportIssueActionable(issue) {" in html
    assert "function isReportIssueCleanup(issue) {" in html
    assert "function renderReportsTable() {" in html
    assert "function reportIssueHiddenHtml(issue) {" in html
    assert "Visual hidden" in html
    assert "Visual visible" in html
    assert "Page hidden" in html
    assert "Page visible" in html
    assert "function reportIssuePositionLabel(issue) {" in html
    assert "function cleanVisibleReportStaleIssues() {" in html
    assert "function cleanAllReportCleanupIssues() {" in html
    assert "function reportCleanupEntriesForIssues(issues) {" in html
    assert "function applyVisibleReportSuggestions() {" in html
    assert "function removeVisibleReportIssues() {" in html
    assert "function reportIssueSelectedSuggestion(issue) {" in html
    assert "class=\"report-suggestion-select\"" in html
    assert "Replacement as Table[Name]" not in html
    assert "Inactive filter card" in html
    assert "Bookmark visual state" in html
    assert "function reportIssueSuggestionHtml(issue) {" in html
    assert "async function cleanReportIssueStaleRef(index) {" in html
    assert "Table Details" in html
    assert "/api/discover" not in html
    assert "function reportStartPathFromModel(modelPath) {" in html
    assert "if (mode === 'report' && chosenModels.length) return reportStartPathFromModel(chosenModels[0].path);" in html
    assert 'id="checkAllTables"' in html
    assert 'id="tableGroupInput"' in html
    assert 'id="btnMoveToTableGroup"' in html
    assert 'id="showActionLogCheckbox"' in html
    assert 'id="tableToolsSection"' in html
    assert 'id="wrapTableTextCheckbox"' in html
    assert 'id="btnAutoSizeColumns"' in html
    assert 'id="pageSizeSelect"' in html
    assert 'id="btnPrevPage"' in html
    assert 'id="btnNextPage"' in html
    assert 'id="filterIssue"' in html
    assert "All issues" in html
    assert "No issues" in html
    assert "filterIssue: []" in html
    assert "function issueFilterValue(itemOrStatus) {" in html
    assert "var issues = getSelectedValues('filterIssue');" in html
    assert "matchesSelectedValues(issueFilterValue(item), issues)" in html
    assert "matchesSelectedValues(issueFilterValue(table), issues)" in html
    assert "matchesSelectedValues(issueFilterValue(r), issues)" in html
    assert "function issueAndReviewSearchText(record) {" in html
    assert "function mainSearchTextForItem(item) {" in html
    assert "function mainSearchTextForTable(table) {" in html
    assert "function mainSearchTextForRef(ref) {" in html
    assert "record.reviewTriggers || []" in html
    assert "record.brokenDaxRefs || []" in html
    assert "record.staleUsageDetails || []" in html
    assert "mainSearchTextForItem(item).includes(search)" in html
    assert "mainSearchTextForTable(table).includes(search)" in html
    assert "mainSearchTextForRef(r).includes(search)" in html
    assert 'id="resultGuideSection"' in html
    assert 'id="resultGuideBody"' in html
    assert "How to read these results" in html
    assert "function renderResultGuideLegend() {" in html
    assert "function legendItemHtml(entry) {" in html
    assert "Usage vs Cleanup" in html
    assert "Usage describes observed report/model evidence; Cleanup describes the recommended action." in html
    assert "Filters narrow every result view with the same vocabulary shown in badges and the guide." in html
    assert "summary cards show model/report totals and cleanup recommendations for the current analysis." in html
    assert "definition: usageHelpText({ usageState: 'Used' })" in html
    assert "definition: usageHelpText({ usageState: 'Indirect' })" in html
    assert "definition: usageHelpText({ usageState: 'Stale only' })" in html
    assert "definition: usageHelpText({ usageState: 'Unused' })" in html
    assert "definition: issueHelpText({ issueState: 'Broken' })" in html
    assert "definition: issueHelpText({ issueState: 'Stale' })" in html
    assert "definition: cleanupHelpText('Safe')" in html
    assert "definition: cleanupHelpText('Review')" in html
    assert "definition: cleanupHelpText('Blocked')" in html
    assert "definition: cleanupHelpText('Keep')" in html
    assert "$('resultGuideSection').classList.remove('hidden');" in html
    assert 'id="appFlowSwitcher"' in html
    assert 'data-app-flow="cleanup"' in html
    assert 'data-app-flow="compare"' in html
    assert 'id="compareFlow"' in html
    assert "Semantic Model Compare (1:1)" in html
    assert 'id="compareBaselinePills"' in html
    assert 'id="compareCandidatePills"' in html
    assert 'id="btnBrowseCompareBaseline"' in html
    assert 'id="btnBrowseCompareCandidate"' in html
    assert 'id="btnRunCompare"' in html
    assert 'id="compareResultSection"' in html
    assert 'id="compareResultTabs"' in html
    assert 'data-compare-view="summary"' in html
    assert 'data-compare-view="details"' in html
    assert 'id="compareSummaryView"' in html
    assert 'id="compareDetailsView"' in html
    assert 'id="compareSummaryCards"' in html
    assert 'id="compareDiffBody"' in html
    assert 'id="compareStatusFilter"' in html
    assert 'id="compareCategoryFilter"' in html
    assert 'id="compareVisibleCount"' in html
    assert 'id="btnExportCompareJson"' in html
    assert 'id="btnExportCompareMarkdown"' in html
    assert 'id="btnExportCompareCsv"' in html
    assert "var compareBaselineModel = null;" in html
    assert "var compareCandidateModel = null;" in html
    assert "var compareResults = null;" in html
    assert "var compareResultView = 'summary';" in html
    assert "var compareStatusFilter = 'all';" in html
    assert "var compareCategoryFilter = 'all';" in html
    assert "function setAppFlow(flow) {" in html
    assert "function renderCompareSelection() {" in html
    assert "function setCompareResultView(view) {" in html
    assert "function filteredCompareDiffs() {" in html
    assert "function renderCompareResults(data) {" in html
    assert "async function runSemanticModelCompare() {" in html
    assert "function clearCompareResults() {" in html
    assert "function compareModelPillHtml(model, side) {" in html
    assert "function isModelExplorerMode(mode) {" in html
    assert "explorerMode === 'compareBaseline'" in html
    assert "explorerMode === 'compareCandidate'" in html
    assert "$('btnBrowseCompareBaseline').onclick = function() { openExplorer('compareBaseline'); };" in html
    assert "$('btnBrowseCompareCandidate').onclick = function() { openExplorer('compareCandidate'); };" in html
    assert "if (explorerMode === 'compareBaseline') {" in html
    assert "if (explorerMode === 'compareCandidate') {" in html
    assert "clearCompareResults();" in html
    assert "$('btnRunCompare').onclick = runSemanticModelCompare;" in html
    assert 'id="reportHealthBanner"' in html
    assert 'id="reportHealthCount"' in html
    assert 'id="reportHealthList"' in html
    assert 'id="reportHealthActionStatus"' in html
    assert "var allReportIssues = [];" in html
    assert "var allReportHealth = { totalIssueCount: 0, groups: [] };" in html
    assert 'id="actionPlanPreview"' in html
    assert 'id="actionPlanSummary"' in html
    assert 'id="actionPlanItems"' in html
    assert 'id="actionPlanFiles"' in html
    assert "function previewQueuedActionPlan(" in html
    assert "function renderActionPlanPreview(plan) {" in html
    assert "function confirmActionPlanApply(plan) {" in html
    assert "/api/action/preview" in html
    assert "var reportHealthStaleCleanupEntries = [];" in html
    assert "function renderReportHealth() {" in html
    assert "function previewReportHealthStaleCleanup() {" in html
    assert "function applyReportHealthStaleCleanup() {" in html
    assert "function renderReportHealthStalePreview(result) {" in html
    assert 'id="reportHealthPreviewList"' in html
    assert "data-report-health-action=\"cleanup_stale\"" in html
    assert "data-report-health-action=\"apply_stale\"" in html
    assert 'id="filterCounts"' not in html
    assert "Dropdown filters support multi-select" not in html
    assert 'data-col="usageState"' in html
    assert 'data-col="issueState"' in html
    assert 'data-col="reportCount"' in html
    assert 'data-col="pageCount"' in html
    assert 'data-col="usageCount"' in html
    assert 'data-col="measureDependentCount"' in html
    assert 'data-col="reportUsedMeasureDependentCount"' not in html
    assert 'data-col="relationshipRefCount"' in html
    assert 'data-col="otherModelUseCount"' in html
    assert 'data-col="deleteSafety"' in html
    assert 'data-col="usageState" title=' in html
    assert 'data-col="issueState" title=' in html
    assert 'data-col="sourceKind" title=' in html
    assert 'data-col="measureDependentCount" title=' in html
    assert 'Used measures <span class="header-help"' not in html
    assert 'data-col="deleteSafety" title=' in html
    assert 'data-tablecol="directReportMeasureCount"' in html
    assert 'data-tablecol="directReportColumnCount"' in html
    assert 'data-tablecol="roleLabel"' not in html
    assert ".cell-ellipsis" in html
    assert ".cell-nowrap" in html
    assert ".header-help" in html
    assert "body.wrap-table-text .cell-ellipsis" in html
    assert "function getPagedRows(rows, viewName) {" in html
    assert "function updatePageControls() {" in html
    assert "initializeHeaderTooltips();" in html
    assert "setActionLogVisible(readShowActionLogPreference());" in html
    assert "setWrapTableTextEnabled(readWrapTableTextPreference());" in html
    assert "var wrapTableTextStorageKey = 'smc.wrapTableText';" in html
    assert "var pageSizeStorageKey = 'smc.pageSize';" in html
    assert "var explorerDefaultPathStoragePrefix = 'smc.explorerDefaultPath.';" in html
    assert "var columnWidthStoragePrefix = 'smc.columnWidths.'" in html
    assert "function fitCurrentTableColumnsToScreen() {" in html
    assert "function fitMinWidthForHeader(th, index) {" in html
    assert "th.dataset.reportcol" in html
    assert "function isReportHeader(th) {" in html
    assert "function calculateDefaultWidths(tableSectionId) {" in html
    assert "function setupResizableTable(tableSectionId) {" in html
    assert "function otherModelUseCellContent(item) {" in html
    assert "function deleteSafetyBadge(item) {" in html
    assert 'id="btnExplorerUp"' in html
    assert 'id="btnExplorerSetDefault"' in html
    assert 'id="explorerDefaultSummary"' in html
    assert "function readExplorerDefaultPath(mode) {" in html
    assert "function writeExplorerDefaultPath(mode, path) {" in html
    assert "function updateExplorerDefaultUI() {" in html
    assert "var savedDefault = mode === 'folder' ? '' : readExplorerDefaultPath(mode);" in html
    assert "Search folder is based on the selected model" in html
    assert "Searching definition.pbir files under " in html
    assert "definition*.pbir" not in html
    assert "$('btnExplorerSetDefault').onclick = function() {" in html
    assert "$('btnExplorerUp').onclick = function() { if (explorerParentPath) browseDir(explorerParentPath); };" in html


def test_api_browse_lists_child_directories_and_parent(tmp_path):
    workspace = tmp_path / "Workspace"
    reports = workspace / "Reports"
    nested = reports / "Regional.Report"
    misc = reports / "Archive"
    hidden = reports / ".git"
    workspace.mkdir()
    reports.mkdir()
    nested.mkdir()
    misc.mkdir()
    hidden.mkdir()

    client = web_app.app.test_client()
    response = client.get("/api/browse", query_string={"path": str(reports)})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current"] == str(reports.resolve())
    assert payload["parent"] == str(workspace.resolve())
    assert payload["entries"] == [
        {"name": "Archive", "path": str(misc.resolve()), "type": "dir"},
        {"name": "Regional.Report", "path": str(nested.resolve()), "type": "report"},
    ]


def test_normalize_browse_path_fixes_windows_drive_relative_input(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    assert web_app._normalize_browse_path(r"C:Projects\Semantic-Model-Cleaner") == (
        r"C:\Projects\Semantic-Model-Cleaner"
    )


def test_normalize_browse_path_removes_leading_slash_from_windows_drive(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    assert web_app._normalize_browse_path(r"/C:\Projects\Semantic-Model-Cleaner") == (
        r"C:\Projects\Semantic-Model-Cleaner"
    )


def test_index_renders_demo_workspace_button():
    web_app._state["runtime"] = web_app.experiments.runtime_config(raw_channel="stable")
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b"btnLoadDemo" in response.data
    assert b"Try the demo workspace" in response.data


def _snapshot_workspace_state():
    keys = ("workspace", "model_search_roots", "report_search_roots", "model_paths", "report_paths")
    return {key: web_app._state[key] for key in keys}


def _restore_workspace_state(snapshot):
    web_app._state.update(snapshot)


def test_api_demo_copies_bundled_workspace_and_analyzes(monkeypatch, tmp_path):
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path / "userdir"))
    snapshot = _snapshot_workspace_state()
    try:
        client = web_app.app.test_client()
        response = client.post("/api/demo")

        assert response.status_code == 200
        payload = response.get_json()
        target = Path(payload["workspace"])
        assert target == tmp_path / "userdir" / "demo-workspace"
        assert payload["reset"] is False
        assert [m["name"] for m in payload["models"]] == ["TestModel"]
        assert [r["name"] for r in payload["reports"]] == ["TestReport"]
        assert (target / "Models" / "TestModel.SemanticModel" / "definition" / "tables" / "Sales.tmdl").is_file()

        analyze_response = client.post(
            "/api/analyze",
            json={
                "model_paths": [m["path"] for m in payload["models"]],
                "report_paths": [r["path"] for r in payload["reports"]],
            },
        )

        assert analyze_response.status_code == 200
        analyze_payload = analyze_response.get_json()
        assert analyze_payload["items"]
        assert analyze_payload["summary"]["models"] == ["TestModel.SemanticModel"]
    finally:
        _restore_workspace_state(snapshot)


def test_api_demo_resets_modified_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path / "userdir"))
    snapshot = _snapshot_workspace_state()
    try:
        client = web_app.app.test_client()
        first = client.post("/api/demo").get_json()
        sales_tmdl = (
            Path(first["workspace"]) / "Models" / "TestModel.SemanticModel"
            / "definition" / "tables" / "Sales.tmdl"
        )
        sales_tmdl.write_text("table Broken", encoding="utf-8")
        marker = Path(first["workspace"]) / "tester-notes.txt"
        marker.write_text("scratch", encoding="utf-8")

        second = client.post("/api/demo").get_json()

        assert second["reset"] is True
        assert second["workspace"] == first["workspace"]
        assert "table Sales" in sales_tmdl.read_text(encoding="utf-8")
        assert not marker.exists()
    finally:
        _restore_workspace_state(snapshot)


def test_bundled_demo_workspace_ships_with_package():
    demo_root = web_app._bundled_demo_workspace_root()

    assert demo_root.is_dir()
    assert demo_root == Path(web_app.__file__).resolve().parent / "demo_workspace"
    assert (demo_root / "Models" / "TestModel.SemanticModel").is_dir()
    assert (demo_root / "Reports" / "TestReport.Report").is_dir()


def test_api_analyze_rejects_missing_paths(tmp_path):
    client = web_app.app.test_client()
    response = client.post(
        "/api/analyze",
        json={
            "model_paths": [str(tmp_path / "Missing.SemanticModel")],
            "report_paths": [str(tmp_path / "Missing.Report")],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "were not found" in error
    assert "Missing.SemanticModel" in error


def test_api_find_connected_reports_tolerates_path_case_differences(tmp_path):
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    if not (tmp_path / "caseprobe").exists():
        import pytest
        pytest.skip("requires a case-insensitive filesystem")

    model_path = tmp_path / "Models" / "Sales.SemanticModel"
    model_path.mkdir(parents=True)
    report = tmp_path / "Reports" / "Executive.Report"
    report.mkdir(parents=True)
    (report / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../../models/sales.semanticmodel"}}}),
        encoding="utf-8",
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/reports/find-connected",
        json={"model_path": str(model_path), "search_root": str(tmp_path / "Reports")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert [r["path"] for r in payload["reports"]] == [str(report.resolve())]
    assert payload["reports"][0]["status"] == "connected"


def test_index_hides_compare_flow_switcher_on_stable_channel():
    web_app._state["runtime"] = web_app.experiments.runtime_config(raw_channel="stable")
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b'class="app-flow-switcher hidden"' in response.data


def test_index_shows_compare_flow_switcher_on_beta_channel():
    web_app._state["runtime"] = web_app.experiments.runtime_config(raw_channel="beta")
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b'class="app-flow-switcher"' in response.data
