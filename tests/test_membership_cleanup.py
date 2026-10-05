"""Issue #99: reviewed changes preserve perspective/culture reference integrity."""
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, change_plan as plans, tmdl_writer, webapp
from semantic_model_cleaner.tmdl_declarations import (
    extract_culture_metadata, extract_perspective_members, scan_tmdl_declarations,
)


FIXTURE = Path(__file__).parent / "fixtures/calculation_group_dependencies/Models/Synthetic Dependencies.SemanticModel/definition"
PERSPECTIVE = "model/definition/perspectives/Executive.tmdl"
CULTURE = "model/definition/cultures/pl-PL.tmdl"


def project(tmp_path, newline="\n"):
    model = tmp_path / "Models/Synthetic.SemanticModel"
    definition = model / "definition"
    files = {
        "tables/Sales.tmdl": "table Sales\n\tmeasure Revenue = 1\n\tmeasure 'Revenue Goal' = 2\n"
                             "\tcolumn Region\n\t\tdataType: string\n\t\tsourceColumn: Region\n"
                             "\tcolumn 'Order Date'\n\t\tdataType: dateTime\n",
        "tables/Targets.tmdl": "table Targets\n\tmeasure Target = 1\n",
        "tables/Time Intelligence.tmdl": "table 'Time Intelligence'\n\tcolumn Name\n\t\tdataType: string\n",
        "perspectives/Executive.tmdl": (FIXTURE / "perspectives/Executive.tmdl").read_text(encoding="utf-8"),
        "cultures/pl-PL.tmdl": (FIXTURE / "cultures/pl-PL.tmdl").read_text(encoding="utf-8").replace(
            "\t\t\t\tmeasure 'Revenue Goal'", "\t\t\t\tmeasure Revenue\n\t\t\t\t\tcaption: Przychód\n\n"
            "\t\t\t\tmeasure 'Revenue Goal'"),
        "cultures/en-US.tmdl": "culture en-US\n\ttranslations\n\t\tmodel Model\n\t\t\ttable Targets\n"
                               "\t\t\t\tmeasure Target\n\t\t\t\t\tcaption: Sales[Revenue]\n",
        "perspectives/Other.tmdl": "perspective Other\n\t/// Sales[Revenue] stays in this comment\n"
                                  "\tperspectiveTable Targets\n\t\tperspectiveMeasure Target\n",
    }
    for relative, text in files.items():
        path = definition / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    report = tmp_path / "Reports/Empty.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(
        '{"datasetReference":{"byPath":{"path":"../../Models/Synthetic.SemanticModel"}}}', encoding="utf-8")
    return model, report


def delete(name="Revenue", item_type="Measure"):
    return {"kind": "actions", "actions": [
        {"action": "delete", "table": "Sales", "name": name, "item_type": item_type}]}


def inventory(model, report):
    return plans._inventory(plans._roots(model, [report]))


def assert_no_dangling_memberships(model):
    items = analyzer.parse_model_items(model)
    tables = {item.table for item in items}
    identities = {(item.table, item.name) for item in items}
    for path in (model / "definition/perspectives").glob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        scan_tmdl_declarations(text, strict=True)
        for member in extract_perspective_members(text):
            assert (member.table, member.name) in identities if member.name else member.table in tables
    for path in (model / "definition/cultures").glob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        scan_tmdl_declarations(text, strict=True)
        for member in extract_culture_metadata(text)[0]:
            assert (member.table, member.name) in identities if member.name else member.table in tables


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_delete_preview_apply_and_restore_include_memberships_byte_exact(tmp_path, newline):
    model, report = project(tmp_path, newline)
    before = inventory(model, report)
    plan = plans.create_plan(model, [report], [delete()])
    assert inventory(model, report) == before  # preview never writes input files
    assert {change["path"] for change in plan["changes"]} == {
        PERSPECTIVE, CULTURE, "model/definition/tables/Sales.tmdl"}
    assert all(change["diff"] for change in plan["changes"])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    after = inventory(model, report)
    assert after[PERSPECTIVE] == before[PERSPECTIVE].replace(
        ("\t\tperspectiveMeasure Revenue" + newline).encode(), b"")
    assert after[CULTURE] == before[CULTURE].replace(
        ("\t\t\t\tmeasure Revenue" + newline + "\t\t\t\t\tcaption: Przychód" + newline).encode(), b"")
    for key in before.keys() - {PERSPECTIVE, CULTURE, "model/definition/tables/Sales.tmdl"}:
        assert after[key] == before[key]
    assert_no_dangling_memberships(model)
    analysis = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert not any(row["item"].name == "Revenue" for row in analysis["items"])
    assert plans.verify_plan(plan)["state"] == "applied"
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert inventory(model, report) == before


@pytest.mark.parametrize("kind,name,target", [
    ("measure_renames", "Revenue", "Owner's Revenue"),
    ("column_renames", "Region", "New Region"),
    ("table_renames", "Sales", "Sales = New"),
])
def test_rename_changes_only_structural_references_and_round_trips(tmp_path, kind, name, target):
    model, report = project(tmp_path, "\r\n")
    # A column and a measure may have similar names in unrelated object scopes.
    perspective = model / "definition/perspectives/Executive.tmdl"
    perspective.write_bytes(perspective.read_bytes().replace(b"\tperspectiveTable Sales\r\n",
        b"\tperspectiveTable Sales\r\n\t\tperspectiveColumn Region\r\n"))
    before = inventory(model, report)
    rename = {"table": "Sales", "target_table": target} if kind == "table_renames" else {
        "table": "Sales", "name": name, "target_name": target}
    plan = plans.create_plan(model, [report], [{"kind": "rename", kind: [rename]}])
    assert {CULTURE, PERSPECTIVE} <= {change["path"] for change in plan["changes"]}
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    after = inventory(model, report)
    from semantic_model_cleaner.tmdl_identifiers import quote_tmdl_name
    quoted = quote_tmdl_name(target)
    for key, keyword in ((PERSPECTIVE, "perspective" + ("Table" if kind == "table_renames" else
                         "Measure" if kind == "measure_renames" else "Column")),
                         (CULTURE, "table" if kind == "table_renames" else
                          "measure" if kind == "measure_renames" else "column")):
        assert after[key] == before[key].replace(
            f"{keyword} {name}\r\n".encode(), f"{keyword} {quoted}\r\n".encode())
    assert after["model/definition/cultures/en-US.tmdl"] == before["model/definition/cultures/en-US.tmdl"]
    assert after["model/definition/perspectives/Other.tmdl"] == before["model/definition/perspectives/Other.tmdl"]
    assert_no_dangling_memberships(model)
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert inventory(model, report) == before


def test_combined_table_and_item_renames_update_new_scope(tmp_path):
    model, report = project(tmp_path)
    op = {"kind": "rename", "table_renames": [{"table": "Sales", "target_table": "New Sales"}],
          "measure_renames": [{"table": "Sales", "name": "Revenue", "target_name": "Net"}],
          "column_renames": [{"table": "Sales", "name": "Region", "target_name": "Area"}]}
    plan = plans.create_plan(model, [report], [op])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert_no_dangling_memberships(model)
    entries, _ = extract_culture_metadata((model / "definition/cultures/pl-PL.tmdl").read_text(encoding="utf-8"))
    assert ("New Sales", "Net") in {(entry.table, entry.name) for entry in entries}
    assert ("New Sales", "Area") in {(entry.table, entry.name) for entry in entries}


def test_delete_prunes_empty_translation_table_but_preserves_perspective_table(tmp_path):
    model, report = project(tmp_path)
    culture = model / "definition/cultures/pl-PL.tmdl"
    culture.write_bytes(b"culture pl-PL\n\ttranslations\n\t\tmodel Model\n\t\t\ttable Sales\n"
                        b"\t\t\t\tmeasure Revenue\n\t\t\t\t\tcaption: Revenue\n")
    plan = plans.create_plan(model, [report], [delete()])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert culture.read_bytes() == b"culture pl-PL\n\ttranslations\n\t\tmodel Model\n"
    assert b"perspectiveTable Sales" in (model / "definition/perspectives/Executive.tmdl").read_bytes()


def test_last_item_deletion_removes_whole_table_memberships_and_translations(tmp_path):
    model, report = project(tmp_path)
    culture = model / "definition/cultures/pl-PL.tmdl"
    payload = b"\tannotation Example = ```\ntable Sales\n\tmeasure Revenue = 1\n\tcolumn Revenue\n```\n"
    culture.write_bytes(culture.read_bytes() + payload)
    actions = [delete(name, kind)["actions"][0] for name, kind in (
        ("Revenue", "Measure"), ("Revenue Goal", "Measure"), ("Region", "Column"), ("Order Date", "Column"))]
    plan = plans.create_plan(model, [report], [{"kind": "actions", "actions": actions}])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert not (model / "definition/tables/Sales.tmdl").exists()
    assert b"perspectiveTable Sales" not in (model / "definition/perspectives/Executive.tmdl").read_bytes()
    assert b"\ttable Sales" not in (model / "definition/cultures/pl-PL.tmdl").read_bytes()
    assert culture.read_bytes().endswith(payload)
    assert_no_dangling_memberships(model)


@pytest.mark.parametrize("relative,text", [
    ("perspectives/Executive.tmdl", "perspective Executive\n\t\tperspectiveTable Sales\n"),
    ("perspectives/Executive.tmdl", "perspective Executive\n\tperspectiveTable 'Sales\n"),
    ("perspectives/Executive.tmdl", "perspective Executive\n\tperspectiveTable Sales\n\t\tperspectiveMeasure\n"),
    ("perspectives/Executive.tmdl", "perspective Executive\n\tunknownReference Sales\n"),
    ("cultures/pl-PL.tmdl", "culture pl-PL\n\ttranslations\n\t\ttable Sales\n\t\t\tmeasure Revenue = 1\n"),
    ("cultures/pl-PL.tmdl", "culture pl-PL\n\ttranslations\n\t\ttable Sales\n\t\t\tmeasure Revenue\n\t\t\t\tcaption: \"oops\n"),
    ("cultures/pl-PL.tmdl", "culture pl-PL\n\tlinguisticMetadata = ```\nunterminated\n"),
    ("cultures/pl-PL.tmdl", "culture pl-PL\n/* unterminated\n"),
    ("cultures/pl-PL.tmdl", "culture pl-PL\n? malformed\n"),
    ("cultures/pl-PL.tmdl", ""),
])
@pytest.mark.parametrize("operation", [delete(), {"kind": "rename", "measure_renames": [
    {"table": "Sales", "name": "Revenue", "target_name": "Net"}]}], ids=["delete", "rename"])
def test_malformed_memberships_block_plan_before_writing(tmp_path, relative, text, operation):
    model, report = project(tmp_path)
    (model / "definition" / relative).write_text(text, encoding="utf-8")
    before = inventory(model, report)
    with pytest.raises(plans.PlanError, match="Blocked: cannot safely edit definition/" + relative):
        plans.create_plan(model, [report], [operation])
    assert inventory(model, report) == before


def test_writer_preflight_blocks_all_direct_rename_and_delete_paths(tmp_path):
    model, report = project(tmp_path)
    (model / "definition/cultures/broken.tmdl").write_bytes(b"not a culture\n")
    before = inventory(model, report)
    for result in (
        tmdl_writer.rename_measure(model, "Sales", "Revenue", "Net"),
        tmdl_writer.rename_column(model, "Sales", "Region", "Area"),
        tmdl_writer.rename_table(model, "Sales", "New Sales"),
        tmdl_writer.delete_item(model, "Sales", "Revenue", "Measure"),
    ):
        assert not result["ok"] and "Blocked" in result["error"]
    assert inventory(model, report) == before


def test_annotation_payloads_and_prose_are_never_renamed(tmp_path):
    model, report = project(tmp_path)
    path = model / "definition/cultures/pl-PL.tmdl"
    payload = b"\tannotation Example = ```\ntable Sales\n\tmeasure Revenue\n```\n"
    path.write_bytes(path.read_bytes() + payload)
    result = tmdl_writer.rename_table(model, "Sales", "New Sales")
    assert result["ok"], result
    assert path.read_bytes().endswith(payload)
    assert b"Sales[Amount]" in path.read_bytes()


@pytest.mark.parametrize("operation", [delete(), {"kind": "rename", "measure_renames": [
    {"table": "Sales", "name": "Revenue", "target_name": "Net"}]}], ids=["delete", "rename"])
def test_annotation_payload_cannot_become_the_model_item_source(tmp_path, operation):
    model, report = project(tmp_path)
    path = model / "definition/cultures/pl-PL.tmdl"
    payload = b"\tannotation Example = ```\ntable Sales\n\tmeasure Revenue = 1\n\tcolumn Revenue\n```\n"
    path.write_bytes(path.read_bytes() + payload)
    plan = plans.create_plan(model, [report], [operation])
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert b"measure Revenue" not in (model / "definition/tables/Sales.tmdl").read_bytes()
    assert path.read_bytes().endswith(payload)
    assert_no_dangling_memberships(model)


def test_api_blocks_malformed_file_with_specific_location(tmp_path, monkeypatch):
    model, report = project(tmp_path)
    monkeypatch.setenv("SMC_USER_DIR", str(tmp_path / "state"))
    (model / "definition/cultures/pl-PL.tmdl").write_bytes(b"culture pl-PL\n\ttranslations\n??\n")
    before = inventory(model, report)
    response = webapp.app.test_client().post("/api/plans", json={
        "model_path": str(model), "report_paths": [str(report)], "operations": [delete()]})
    assert response.status_code == 400
    assert "Blocked: cannot safely edit definition/cultures/pl-PL.tmdl: line 3" in response.json["error"]
    assert inventory(model, report) == before


def test_batch_failure_restores_membership_bytes(tmp_path, monkeypatch):
    model, report = project(tmp_path, "\r\n")
    before = inventory(model, report)
    monkeypatch.setattr(tmdl_writer, "set_hidden", lambda *a, **kw: {"ok": False, "error": "injected failure"})
    results = tmdl_writer.apply_actions(model, [delete()["actions"][0],
        {"action": "hide", "table": "Sales", "name": "Revenue Goal", "item_type": "Measure"}])
    assert all(result["rolled_back"] for result in results)
    assert inventory(model, report) == before
