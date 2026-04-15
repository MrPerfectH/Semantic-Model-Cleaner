import json

from semantic_model_cleaner import analyzer, webapp as web_app


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
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["ok"] is True
    assert captured["table"] == "Sales"
    assert captured["name"] == "Revenue"
    assert captured["item_type"] == "Measure"
    assert captured["dax_expression"] == "SUM(Sales[Amount])"


def test_api_action_accepts_move_to_table_group(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    model_path.mkdir()
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
    assert "var savedDefault = readExplorerDefaultPath(mode);" in html
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
