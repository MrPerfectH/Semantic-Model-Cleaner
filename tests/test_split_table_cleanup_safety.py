"""Deleting a fragment's last item must not delete a retained table."""
import json

import pytest

from semantic_model_cleaner import change_plan, tmdl_writer


def project(tmp_path, *, retained=True, neighbor=False):
    model = tmp_path / "M.SemanticModel"
    report = tmp_path / "R.Report"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_bytes(b"table Sales\r\n\tcolumn Id\r\n\t\tdataType: int64\r\n" if retained
                                       else b"table Sales\r\n\tannotation Extra = metadata\r\n")
    split = tables / "SalesMeasures.tmdl"
    split.write_bytes(b"table Sales\r\n\tmeasure Spare = 1\r\n\t\tformatString: 0\r\n\r\n"
                      + (b"table Neighbor\r\n\tmeasure Keep = 2\r\n" if neighbor else b""))
    (tables / "Date.tmdl").write_bytes(b"table Date\r\n\tcolumn Id\r\n\t\tdataType: int64\r\n")
    (model / "definition/model.tmdl").write_bytes(b"model Model\r\nref table Sales\r\nref table Date\r\n")
    (model / "definition/relationships.tmdl").write_bytes(
        b"relationship SalesToDate\r\n\tfromColumn: Sales.Id\r\n\ttoColumn: Date.Id\r\n" if retained else b"")
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text("{}")
    (report / "definition.pbir").write_text(json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}))
    return model, report, split


def operation():
    return {"kind": "actions", "actions": [{"action": "delete", "table": "Sales", "name": "Spare", "item_type": "Measure"}]}


@pytest.mark.parametrize("neighbor", [False, True])
def test_split_table_delete_preview_apply_verify_restore_preserves_retained_structure(tmp_path, neighbor):
    model, report, split = project(tmp_path, neighbor=neighbor)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    plan = change_plan.create_plan(model, [report], [operation()])
    assert change_plan._inventory(roots) == before
    assert [change["path"] for change in plan["changes"]] == ["model/definition/tables/SalesMeasures.tmdl"]
    journal = tmp_path / "journal"
    assert change_plan.apply_plan(plan, journal)["ok"]
    assert change_plan.verify_plan(plan)["ok"]
    after = change_plan._inventory(roots)
    for key, content in before.items():
        if key != "model/definition/tables/SalesMeasures.tmdl":
            assert after[key] == content
    assert split.read_bytes() == before["model/definition/tables/SalesMeasures.tmdl"].replace(
        b"\tmeasure Spare = 1\r\n\t\tformatString: 0\r\n\r\n", b"")
    assert change_plan.restore_plan(plan, journal)["ok"]
    assert change_plan._inventory(roots) == before


def test_last_item_across_multiple_table_declarations_blocks_before_any_write(tmp_path):
    model, report, _ = project(tmp_path, retained=False)
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    result = tmdl_writer.delete_item(model, "Sales", "Spare", "Measure")
    assert not result["ok"], result
    assert result["written"] is False
    assert "multiple TMDL declarations" in result["error"]
    assert change_plan._inventory(roots) == before
    with pytest.raises(change_plan.PlanError, match="multiple TMDL declarations"):
        change_plan.create_plan(model, [report], [operation()])
    assert change_plan._inventory(roots) == before


def test_last_table_item_in_shared_file_preserves_other_table_bytes(tmp_path):
    model, report, split = project(tmp_path, retained=False, neighbor=True)
    (model / "definition/tables/Sales.tmdl").unlink()
    roots = change_plan._roots(model, [report])
    before = change_plan._inventory(roots)
    plan = change_plan.create_plan(model, [report], [operation()])
    assert change_plan._inventory(roots) == before
    journal = tmp_path / "journal"
    assert change_plan.apply_plan(plan, journal)["ok"]
    assert change_plan.verify_plan(plan)["ok"]
    assert split.read_bytes() == b"table Neighbor\r\n\tmeasure Keep = 2\r\n"
    assert b"ref table Sales" not in (model / "definition/model.tmdl").read_bytes()
    assert change_plan.restore_plan(plan, journal)["ok"]
    assert change_plan._inventory(roots) == before
