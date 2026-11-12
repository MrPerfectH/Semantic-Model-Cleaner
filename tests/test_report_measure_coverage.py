"""Generic coverage repros; no PMRA metadata or DAX."""
import json
from copy import deepcopy

import pytest

from semantic_model_cleaner import analyzer, change_plan as plans, metadata_validation
from test_report_measure_delete import project, extension, operation


def rows(tmp_path, model, reports):
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=reports,
                              include_report_measure_deletions=True)
    return {r["item"].name: r for r in result["items"]
            if r["item"].source_kind == "report"}


def test_unrecognized_static_owner_retains_targets_but_allows_independent_delete(tmp_path):
    model, reports = project(tmp_path)
    path = extension(reports[0], [('Sales', 'Leaf', '1'), ('Sales', 'Bad', 'VAR X = [Leaf]'),
                                 ('Sales', 'Unused', '2')])
    data = json.loads(path.read_bytes())
    data["entities"][0]["measures"][1]["references"] = {"unrecognizedReferences": True}
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    found = rows(tmp_path, model, [reports[0]])
    assert not found["Bad"]["report_measure_delete"]["groupEligible"]
    assert not found["Leaf"]["report_measure_delete"]["groupEligible"]
    plan = plans.create_plan(model, [reports[0]], [operation(reports[0], "Unused")])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert json.loads(path.read_bytes())["entities"][0]["measures"] == data["entities"][0]["measures"][:2]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert path.read_bytes() == before


def test_empty_expression_inventory_and_inbound_reference(tmp_path):
    model, reports = project(tmp_path)
    extension(reports[0], [('Sales', 'Empty', ''), ('Sales', 'Consumer', '[Empty]'),
                           ('Sales', 'Unused', '1')])
    found = rows(tmp_path, model, [reports[0]])
    assert set(found) == {"Empty", "Consumer", "Unused"}
    assert not found["Empty"]["report_measure_delete"]["eligible"]
    assert not found["Empty"]["report_measure_delete"]["groupEligible"]
    assert plans.create_plan(model, [reports[0]], [operation(reports[0], "Unused")])["changes"]


def test_empty_model_schema_reference_does_not_fall_back_to_extension(tmp_path):
    model, reports = project(tmp_path)
    path = extension(reports[0], [('Sales', 'Leaf', '1'), ('Sales', 'Consumer', '1')])
    data = json.loads(path.read_bytes())
    data["entities"][0]["measures"][1]["references"] = {"measures": [
        {"entity": "Sales", "name": "Leaf", "schema": ""}]}
    path.write_text(json.dumps(data))
    found = rows(tmp_path, model, [reports[0]])
    assert any("model dependency" in s for s in found["Consumer"]["report_measure_delete"]["reasons"])
    assert found["Leaf"]["report_measure_delete"]["eligible"]
    data["entities"][0]["measures"][1]["references"]["measures"][0]["schema"] = "extension"
    path.write_text(json.dumps(data))
    found = rows(tmp_path, model, [reports[0]])
    assert not found["Leaf"]["report_measure_delete"]["eligible"]
    assert found["Leaf"]["report_measure_delete"]["groupEligible"]


@pytest.mark.parametrize("version", ["2.10.0", "2.11.0", "2.12.0", "2.13.0"])
def test_pinned_new_visual_schema_and_live_reference_block(tmp_path, version):
    model, reports = project(tmp_path)
    visual = {
        "$schema": f"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/{version}/schema.json",
        "name": "V", "position": {"x": 0, "y": 0, "height": 10, "width": 10},
        "visual": {"visualType": "card", "objects": {"title": [
            {"properties": {"text": {"expr": {"Measure": {
                "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Unused"}}}}}]}}
    }
    assert metadata_validation.validate_document(visual)["status"] == "valid"
    p = reports[0] / "definition/pages/P/visuals/V/visual.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(visual))
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [operation(reports[0], "Unused")])
    bad = deepcopy(visual)
    bad["visual"]["visualType"] = 42
    assert metadata_validation.validate_document(bad)["status"] == "invalid"


def test_unpublished_visual_schema_remains_unknown(tmp_path):
    model, reports = project(tmp_path)
    p = reports[0] / "definition/pages/P/visuals/V/visual.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"}))
    found = rows(tmp_path, model, [reports[0]])
    assert not found["Unused"]["report_measure_delete"]["supported"]
    assert found["Unused"]["removal_risk"] == "Review"
    with pytest.raises(plans.PlanError):
        plans.create_plan(model, [reports[0]], [operation(reports[0], "Unused")])


def test_static_malformed_owner_does_not_hide_empty_target(tmp_path):
    model, reports = project(tmp_path)
    path = extension(reports[0], [('Sales', 'Empty', ''), ('Sales', 'Malformed', 'VAR X = [Empty]'),
                                 ('Sales', 'Unused', '1')])
    data = json.loads(path.read_bytes())
    data["entities"][0]["measures"][1]["references"] = {"unrecognizedReferences": True}
    path.write_text(json.dumps(data))
    found = rows(tmp_path, model, [reports[0]])
    assert not found["Empty"]["report_measure_delete"]["groupEligible"]
    assert not found["Malformed"]["report_measure_delete"]["groupEligible"]
    assert found["Unused"]["report_measure_delete"]["eligible"]


def test_conflicting_schema_identity_and_dependent_still_fail_closed(tmp_path, monkeypatch):
    import hashlib
    base = "https://example.invalid/"
    docs = [
        ("a.json", {"$schema": "http://json-schema.org/draft-07/schema#", "$id": base + "b.json", "type": "string"}),
        ("b.json", {"$schema": "http://json-schema.org/draft-07/schema#", "$id": base + "b.json", "type": "object"}),
        ("c.json", {"$schema": "http://json-schema.org/draft-07/schema#", "$id": base + "c.json", "$ref": base + "a.json"}),
    ]
    manifest = {"repository": "synthetic", "commit": "synthetic", "schemas": []}
    for name, document in docs:
        raw = json.dumps(document).encode()
        (tmp_path / name).write_bytes(raw)
        manifest["schemas"].append({"path": name, "uri": base + name, "id": document["$id"], "sha256": hashlib.sha256(raw).hexdigest()})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    metadata_validation._bundle.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(metadata_validation, "BUNDLE_ROOT", tmp_path)
            for name in ("a.json", "c.json"):
                result = metadata_validation.validate_document({"$schema": base + name})
                assert result["status"] == "not_validated"
                assert "identity_conflict" in result["reason"]
    finally:
        metadata_validation._bundle.cache_clear()
