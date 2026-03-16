from semantic_model_cleaner import analyzer, compare as compare_engine, webapp as web_app


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


def _fake_compare_results():
    return {
        "summary": {
            "baselineModel": "Baseline.SemanticModel",
            "candidateModel": "Candidate.SemanticModel",
            "totalChanges": 2,
            "countsByChangeType": {
                "added": 1,
                "removed": 0,
                "changed": 1,
            },
            "levels": {
                "model": {"added": 0, "removed": 0, "changed": 0},
                "relationship": {"added": 0, "removed": 0, "changed": 0},
                "table": {"added": 1, "removed": 0, "changed": 0},
                "measure": {"added": 0, "removed": 0, "changed": 1},
                "column": {"added": 0, "removed": 0, "changed": 0},
            },
        },
        "changes": [
            {
                "level": "table",
                "changeType": "added",
                "objectId": "table::Product",
                "table": "Product",
                "name": "Product",
                "propertyChanges": [],
                "before": None,
                "after": {
                    "name": "Product",
                    "properties": {},
                    "measureNames": [],
                    "columnNames": [],
                },
            },
            {
                "level": "measure",
                "changeType": "changed",
                "objectId": "measure::Sales::Revenue",
                "table": "Sales",
                "name": "Revenue",
                "propertyChanges": [
                    {
                        "property": "expression",
                        "before": "SUM(Sales[Amount])",
                        "after": "SUM(Sales[NetAmount])",
                    }
                ],
                "before": {
                    "table": "Sales",
                    "name": "Revenue",
                    "properties": {"expression": "SUM(Sales[Amount])"},
                },
                "after": {
                    "table": "Sales",
                    "name": "Revenue",
                    "properties": {"expression": "SUM(Sales[NetAmount])"},
                },
            },
        ],
        "warnings": [],
    }


def test_home_renders_mode_menu():
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Semantic Model Tools" in html
    assert 'href="/analyze"' in html
    assert 'href="/compare"' in html


def test_analyze_page_renders_packaged_template():
    client = web_app.app.test_client()
    response = client.get("/analyze")

    assert response.status_code == 200
    assert b"Semantic Model Cleaner" in response.data


def test_compare_page_renders():
    client = web_app.app.test_client()
    response = client.get("/compare")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Semantic Model Compare (1:1)" in html
    assert 'id="baselinePath"' in html
    assert 'id="candidatePath"' in html


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
    assert payload["items"][0]["dependsOnMeasures"] == []
    assert payload["items"][0]["dependsOnColumns"] == []
    assert payload["items"][0]["usedByItems"] == []
    assert payload["items"][0]["usageDetails"] == []
    assert payload["items"][0]["commentedRefs"] == ["[Legacy Revenue]"]
    assert payload["tables"][0]["name"] == "Sales"
    assert payload["tables"][0]["signals"] == ["No direct report references were found for this table."]


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


def test_api_compare_success(monkeypatch, tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"
    baseline.mkdir()
    candidate.mkdir()

    monkeypatch.setattr(web_app.compare, "compare_models", lambda **_: _fake_compare_results())

    client = web_app.app.test_client()
    response = client.post(
        "/api/compare",
        json={
            "baseline_model_path": str(baseline),
            "candidate_model_path": str(candidate),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["totalChanges"] == 2
    assert payload["changes"][0]["level"] == "table"


def test_api_compare_rejects_same_model(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()

    client = web_app.app.test_client()
    response = client.post(
        "/api/compare",
        json={
            "baseline_model_path": str(model),
            "candidate_model_path": str(model),
        },
    )

    assert response.status_code == 400
    assert "must be different" in response.get_json()["error"]


def test_api_compare_rejects_non_model_path(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "not-model"
    baseline.mkdir()
    candidate.mkdir()

    client = web_app.app.test_client()
    response = client.post(
        "/api/compare",
        json={
            "baseline_model_path": str(baseline),
            "candidate_model_path": str(candidate),
        },
    )

    assert response.status_code == 400
    assert ".SemanticModel" in response.get_json()["error"]


def test_api_compare_export_json_returns_latest_compare():
    web_app._state["last_compare_results"] = _fake_compare_results()

    client = web_app.app.test_client()
    response = client.get("/api/compare/export?format=json")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert "Baseline_vs_Candidate_model_compare.json" in response.headers["Content-Disposition"]
    payload = response.get_json()
    assert payload["summary"]["baselineModel"] == "Baseline.SemanticModel"


def test_api_compare_export_xlsx_returns_attachment(monkeypatch):
    web_app._state["last_compare_results"] = _fake_compare_results()
    monkeypatch.setattr(compare_engine, "create_compare_xlsx_bytes", lambda results: b"PK\x03\x04fake-xlsx")

    client = web_app.app.test_client()
    response = client.get("/api/compare/export?format=xlsx")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "Baseline_vs_Candidate_model_compare.xlsx" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"PK")


def test_api_compare_export_requires_prior_compare():
    web_app._state["last_compare_results"] = None

    client = web_app.app.test_client()
    response = client.get("/api/compare/export?format=json")

    assert response.status_code == 400
    assert "Run compare first" in response.get_json()["error"]


def test_api_compare_export_rejects_unknown_format():
    web_app._state["last_compare_results"] = _fake_compare_results()

    client = web_app.app.test_client()
    response = client.get("/api/compare/export?format=bad")

    assert response.status_code == 400
    assert "Unsupported export format" in response.get_json()["error"]


def test_analyze_page_renders_empty_selection_state():
    client = web_app.app.test_client()
    response = client.get("/analyze")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "No model selected" in html
    assert "No reports selected" in html
    assert 'data-view="tables"' in html
    assert "Table Details" in html
    assert "/api/discover" not in html
    assert "if (mode === 'report' && chosenModels.length) return parentDir(chosenModels[0].path);" in html
    assert 'id="btnExplorerUp"' in html
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
