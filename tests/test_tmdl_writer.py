import tmdl_writer


def test_delete_item_removes_empty_table_model_ref_and_relationships(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)

    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn Id\n"
        "\t\tdataType: int64\n",
        encoding="utf-8",
    )

    (model_path / "definition" / "model.tmdl").write_text(
        "model Model\n"
        "ref table Sales\n",
        encoding="utf-8",
    )

    (model_path / "definition" / "relationships.tmdl").write_text(
        "relationship SalesToDate\n"
        "\tfromColumn: Sales.Id\n"
        "\ttoColumn: Date.Id\n",
        encoding="utf-8",
    )

    result = tmdl_writer.delete_item(model_path, "Sales", "Id", "Column")

    assert result["ok"] is True
    assert result["table_deleted"] is True
    assert result["removed_relationships"] == ["relationship SalesToDate"]
    assert not sales_file.exists()
    assert "ref table Sales" not in (model_path / "definition" / "model.tmdl").read_text(encoding="utf-8")
    assert (model_path / "definition" / "relationships.tmdl").read_text(encoding="utf-8").strip() == ""
