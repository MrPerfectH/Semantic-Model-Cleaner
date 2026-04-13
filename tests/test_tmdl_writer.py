from semantic_model_cleaner import tmdl_writer


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


def test_set_dax_expression_updates_measure(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\t\tdisplayFolder: Core\n",
        encoding="utf-8",
    )

    result = tmdl_writer.set_dax_expression(
        model_path=model_path,
        table="Sales",
        name="Revenue",
        item_type="Measure",
        dax_expression="DIVIDE(\n    SUM(Sales[Amount]),\n    100\n)",
    )

    assert result["ok"] is True
    content = sales_file.read_text(encoding="utf-8")
    assert "\tmeasure Revenue = DIVIDE(" in content
    assert "SUM(Sales[Amount])," in content
    assert "\t\tdisplayFolder: Core" in content


def test_set_dax_expression_updates_calculated_column(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn MarginPct\n"
        "\t\texpression = DIVIDE(Sales[Profit], Sales[Amount])\n"
        "\t\thidden\n",
        encoding="utf-8",
    )

    result = tmdl_writer.set_dax_expression(
        model_path=model_path,
        table="Sales",
        name="MarginPct",
        item_type="Calculated Column",
        dax_expression="DIVIDE(\nSales[Profit],\nSales[Amount]\n)",
    )

    assert result["ok"] is True
    content = sales_file.read_text(encoding="utf-8")
    assert "\t\texpression = DIVIDE(" in content
    assert "\t\t\tSales[Profit]," in content
    assert "\t\thidden" in content


def test_set_table_group_inserts_and_updates_annotation(tmp_path):
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

    result = tmdl_writer.set_table_group(model_path, "Sales", "PNL Actuals")

    assert result["ok"] is True
    content = sales_file.read_text(encoding="utf-8")
    assert "\tannotation TabularEditor_TableGroup = PNL Actuals" in content

    result = tmdl_writer.set_table_group(model_path, "Sales", "Actuals")

    assert result["ok"] is True
    updated = sales_file.read_text(encoding="utf-8")
    assert "\tannotation TabularEditor_TableGroup = Actuals" in updated
    assert "PNL Actuals" not in updated


def test_create_measure_appends_properties(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Existing = 1\n",
        encoding="utf-8",
    )

    result = tmdl_writer.create_measure(
        model_path=model_path,
        table="Sales",
        name="Report Revenue",
        dax_expression="DIVIDE(\n    [Existing],\n    2\n)",
        display_folder="Executive",
        format_string="0.0",
        hidden=True,
    )

    assert result["ok"] is True
    content = sales_file.read_text(encoding="utf-8")
    assert "\tmeasure 'Report Revenue' = DIVIDE(" in content
    assert "\t\t\t    [Existing]," in content
    assert "\t\tformatString: 0.0" in content
    assert "\t\tdisplayFolder: Executive" in content
    assert "\t\tisHidden" in content
