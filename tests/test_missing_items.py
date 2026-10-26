"""Reports screen: broken report references grouped by the missing model item."""
from semantic_model_cleaner import webapp as web_app


def _issue(issue_type, table, name, *, report="R1", page="P1", visual="v1", hidden=False, suggestions=()):
    return {"issueType": issue_type, "severity": "error", "report": report, "reportPath": "/w/" + report,
            "page": page, "pageHidden": hidden, "visualHidden": False, "visualId": visual,
            "table": table, "name": name, "suggestions": list(suggestions)}


def test_missing_table_groups_every_field_under_the_table():
    issues = [
        _issue("missing_table", "IW_49n", "order_number", visual="v1"),
        _issue("missing_table", "iw_49n", "plant", visual="v1"),
        _issue("missing_table", "IW_49n", "plant", report="R2", page="Tooltip", visual="v9", hidden=True),
    ]
    result = web_app._build_missing_items(issues)
    assert result["itemCount"] == 1
    item = result["items"][0]
    assert (item["kind"], item["label"]) == ("table", "IW_49n")
    assert (item["totalCount"], item["visibleCount"], item["hiddenCount"]) == (3, 2, 1)
    assert (item["visualCount"], item["visibleVisualCount"], item["reportCount"]) == (2, 1, 2)
    assert item["fields"] == [{"name": "plant", "count": 2}, {"name": "order_number", "count": 1}]
    assert all(issue["missingItemKey"] == item["key"] for issue in issues)
    hidden_report = next(r for r in item["reports"] if r["report"] == "R2")
    assert hidden_report["pages"] == [{"page": "Tooltip", "hidden": True, "count": 1}]


def test_missing_columns_and_measures_are_separate_items():
    issues = [
        _issue("missing_column", "IFLO", "fl_system_status"),
        _issue("missing_column", "IFLO", "fl_system_status", visual="v2"),
        _issue("missing_column", "IFLO", "other_col"),
        _issue("missing_measure", "_Measures", "Open Tasks",
               suggestions=[{"action": "suggest_replace", "table": "_Measures", "name": "Open Task Count", "confidence": "Medium"}]),
        _issue("missing_report_measure", "ReportExt", "Local KPI"),
    ]
    result = web_app._build_missing_items(issues)
    labels = [(i["kind"], i["label"], i["totalCount"]) for i in result["items"]]
    assert labels[0] == ("column", "IFLO[fl_system_status]", 2)
    assert set(labels[1:]) == {("column", "IFLO[other_col]", 1), ("measure", "_Measures[Open Tasks]", 1),
                               ("reportMeasure", "ReportExt[Local KPI]", 1)}
    measure = next(i for i in result["items"] if i["kind"] == "measure")
    assert measure["suggestion"] == {"table": "_Measures", "name": "Open Task Count", "confidence": "Medium"}
    assert result["referenceCount"] == 5 and result["visibleVisualCount"] == 2


def test_items_on_visible_pages_sort_first_and_other_issues_are_ignored():
    issues = [
        _issue("missing_table", "OnlyHidden", "x", hidden=True),
        _issue("missing_table", "OnlyHidden", "y", hidden=True),
        _issue("missing_column", "Seen", "c"),
        _issue("stale_visual_selector", "Sales", "Old"),
        _issue("invalid_report_json", "", ""),
    ]
    result = web_app._build_missing_items(issues)
    assert [i["label"] for i in result["items"]] == ["Seen[c]", "OnlyHidden"]
    assert "missingItemKey" not in issues[3] and "missingItemKey" not in issues[4]
