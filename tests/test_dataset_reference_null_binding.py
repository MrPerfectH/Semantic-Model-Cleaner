"""A null datasetReference binding is inactive; only two active bindings are ambiguous.

Fabric-exported definition.pbir files keep both keys and set the unused one to
null (the published schema allows ``object | null`` for each). Every discovery,
selection and mutation path reads report_binding_status, so these checks cover
the shared decision plus the entry points that consume it.
"""
import json
import os
from pathlib import Path
import shutil

import pytest

from semantic_model_cleaner import analyzer, ci
from semantic_model_cleaner.cleanup_policy import evaluate_deletion_policy


SECRET = "Password=hunter2-should-never-print"


def write_report(root: Path, name: str, reference) -> Path:
    report = root / f"{name}.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition" / "report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": reference}), encoding="utf-8")
    return report


@pytest.fixture
def model(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    (model / "definition" / "tables").mkdir(parents=True)
    (model / "definition" / "tables" / "Sales.tmdl").write_text(
        "table Sales\n\tcolumn Amount\n\t\tdataType: int64\n", encoding="utf-8")
    return model


def path_to(model: Path, report_root: Path, name: str) -> str:
    return os.path.relpath(model, report_root / f"{name}.Report").replace(os.sep, "/")


def status(report: Path, model: Path) -> dict:
    return analyzer.report_binding_status(report, model)


def test_null_by_connection_leaves_active_by_path_binding(tmp_path, model):
    report = write_report(tmp_path, "Local", {"byPath": {"path": path_to(model, tmp_path, "Local")},
                                              "byConnection": None})
    assert status(report, model)["status"] == "connected"


def test_null_by_path_leaves_active_by_connection_binding(tmp_path, model):
    report = write_report(tmp_path, "Live", {
        "byPath": None, "byConnection": {"connectionString": f'Data Source=x;Initial Catalog="Sales";{SECRET}'}})
    binding = status(report, model)
    assert binding["status"] == "connected_by_name"
    assert binding["publishedModelName"] == "Sales"
    assert SECRET not in json.dumps(binding)


def test_null_by_connection_with_other_model_path_is_not_connected(tmp_path, model):
    report = write_report(tmp_path, "Other", {"byPath": {"path": "../Other.SemanticModel"}, "byConnection": None})
    assert status(report, model)["status"] == "not_connected"


def test_null_by_path_with_other_published_model_is_not_connected(tmp_path, model):
    report = write_report(tmp_path, "Elsewhere", {
        "byPath": None, "byConnection": {"connectionString": "Initial Catalog=Notifications"}})
    binding = status(report, model)
    assert binding["status"] == "not_connected"
    assert binding["publishedModelName"] == "Notifications"


def test_two_active_bindings_remain_ambiguous(tmp_path, model):
    report = write_report(tmp_path, "Both", {
        "byPath": {"path": path_to(model, tmp_path, "Both")},
        "byConnection": {"connectionString": f'Initial Catalog="Sales";{SECRET}'}})
    binding = status(report, model)
    assert binding["status"] == "ambiguous_definition"
    assert SECRET not in json.dumps(binding)


def test_both_null_has_no_binding(tmp_path, model):
    report = write_report(tmp_path, "Neither", {"byPath": None, "byConnection": None})
    assert status(report, model)["status"] == "missing_dataset_reference"


@pytest.mark.parametrize("reference", [
    {"byPath": "../Sales.SemanticModel", "byConnection": None},
    {"byPath": ["../Sales.SemanticModel"]},
    {"byPath": None, "byConnection": f"Initial Catalog=Sales;{SECRET}"},
    {"byConnection": [f"Initial Catalog=Sales;{SECRET}"]},
    {"byPath": None, "byConnection": {"connectionString": 42}},
    {"byPath": {"path": 7}, "byConnection": None},
    "../Sales.SemanticModel",
])
def test_malformed_non_null_binding_is_invalid_without_echoing_values(tmp_path, model, reference):
    report = write_report(tmp_path, "Malformed", reference)
    binding = status(report, model)
    assert binding["status"] == "invalid_definition"
    assert binding["status"] not in analyzer.BOUND_REPORT_STATUSES
    assert SECRET not in json.dumps(binding)
    assert "hunter2" not in binding["message"]


def test_null_bindings_select_matching_reports_in_every_entry_point(tmp_path, model):
    root = tmp_path
    local = write_report(root, "Local", {"byPath": {"path": path_to(model, root, "Local")}, "byConnection": None})
    live = write_report(root, "Live", {"byPath": None,
                                       "byConnection": {"connectionString": 'Initial Catalog="Sales"'}})
    other = write_report(root, "Notifications", {
        "byPath": None, "byConnection": {"connectionString": "Initial Catalog=Notifications"}})
    both = write_report(root, "Both", {"byPath": {"path": path_to(model, root, "Both")},
                                       "byConnection": {"connectionString": 'Initial Catalog="Sales"'}})
    reports = [local, live, other, both]

    bound, skipped = analyzer.partition_reports_by_binding(reports, model)
    assert sorted(p.name for p in bound) == ["Live.Report", "Local.Report"]
    assert {row["name"]: row["status"] for row in skipped} == {
        "Notifications": "not_connected", "Both": "ambiguous_definition"}

    scope = analyzer.report_binding_scope(model, reports)
    assert sorted(Path(row["path"]).name for row in scope["selected"]) == ["Live.Report", "Local.Report"]

    result = analyzer.analyze(root, model_paths=[model])
    assert sorted(Path(row["path"]).name for row in result["report_binding"]["selected"]) == [
        "Live.Report", "Local.Report"]
    excluded = [w for w in result["warnings"] if w.get("code") == "REPORT_SCOPE_EXCLUDED"]
    assert len(excluded) == 2 and any("Both" in w["message"] for w in excluded)

    _, checked = ci.run_check(root)
    assert sorted(Path(p).name for p in checked["scope"]["reports"]) == ["Live.Report", "Local.Report"]

    # Mutation workflows accept the null-binding reports as verified scope.
    policy = evaluate_deletion_policy(model, [local, live], [
        {"action": "delete", "item_type": "Column", "table": "Sales", "name": "Amount"}])
    assert [r["binding"] for r in policy["scope"]["reports"]] == ["connected_by_name", "connected"]
    assert not [v for v in policy["violations"] if v["rule_id"] == "SMC-D001"]
    rejected = evaluate_deletion_policy(model, [both], [
        {"action": "delete", "item_type": "Column", "table": "Sales", "name": "Amount"}])
    assert [v["rule_id"] for v in rejected["violations"]] == ["SMC-D001"]


def test_demo_workspace_binding_unchanged(tmp_path):
    root = tmp_path / "demo"
    shutil.copytree(Path(analyzer.__file__).parent / "demo_workspace", root)
    model = next(root.rglob("*.SemanticModel"))
    report = next(root.rglob("*.Report"))
    assert status(report, model)["status"] == "connected"
