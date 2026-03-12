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


def test_index_renders_packaged_template():
    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b"Semantic Model Cleaner" in response.data


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
    assert "/api/discover" not in html
    assert "if (mode === 'report' && chosenModels.length) return parentDir(chosenModels[0].path);" in html


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
