import shutil

from semantic_model_cleaner import analyzer, tmdl_writer


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


def test_move_measure_to_table_preserves_block(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    measures_file = tables_dir / "_Measures.tmdl"
    sales_file = tables_dir / "Sales.tmdl"
    measures_file.write_text(
        "table _Measures\n"
        "\tmeasure 'Revenue LY' = DIVIDE(\n"
        "\t\t\t[Revenue],\n"
        "\t\t\t100\n"
        "\t\t)\n"
        "\t\tformatString: 0.0\n"
        "\t\tdisplayFolder: Executive\n"
        "\t\tisHidden\n"
        "\tmeasure Other = 1\n",
        encoding="utf-8",
    )
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\tmeasure Margin = DIVIDE('_Measures'[Revenue LY], 100)\n",
        encoding="utf-8",
    )

    result = tmdl_writer.move_measure_to_table(model_path, "_Measures", "Revenue LY", "Sales")

    assert result["ok"] is True
    source = measures_file.read_text(encoding="utf-8")
    target = sales_file.read_text(encoding="utf-8")
    assert "\tmeasure 'Revenue LY'" not in source
    assert "\tmeasure Other = 1" in source
    assert "\tmeasure 'Revenue LY' = DIVIDE(" in target
    assert "\t\tformatString: 0.0" in target
    assert "\t\tdisplayFolder: Executive" in target
    assert "\t\tisHidden" in target
    assert "DIVIDE('Sales'[Revenue LY], 100)" in target
    assert result["updated_reference_count"] == 1


def test_move_measure_to_table_rejects_duplicate_target(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "_Measures.tmdl").write_text(
        "table _Measures\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tmeasure Revenue = 2\n",
        encoding="utf-8",
    )

    result = tmdl_writer.move_measure_to_table(model_path, "_Measures", "Revenue", "Sales")

    assert result["ok"] is False
    assert "already has a measure" in result["error"]


def test_rename_measure_updates_declaration_and_dax_refs(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    measures_file = tables_dir / "Measures.tmdl"
    sales_file = tables_dir / "Sales.tmdl"
    measures_file.write_text(
        "table Measures\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\tmeasure Margin = DIVIDE([Revenue], 'Measures'[Revenue])\n",
        encoding="utf-8",
    )
    sales_file.write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n",
        encoding="utf-8",
    )

    result = tmdl_writer.rename_measure(model_path, "Measures", "Revenue", "Net Revenue")

    assert result["ok"] is True
    content = measures_file.read_text(encoding="utf-8")
    assert "\tmeasure 'Net Revenue' = SUM(Sales[Amount])" in content
    assert "DIVIDE([Net Revenue], 'Measures'[Net Revenue])" in content


def test_rename_table_updates_file_declaration_model_relationships_and_dax(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tdefaultDetailRowsDefinition = Sales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: decimal\n"
        "\tmeasure Revenue = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (model_path / "definition" / "model.tmdl").write_text(
        "model Model\n"
        "ref table Sales\n",
        encoding="utf-8",
    )
    (model_path / "definition" / "relationships.tmdl").write_text(
        "relationship SalesToDate\n"
        "\tfromColumn: Sales.Amount\n"
        "\ttoColumn: Date.Amount\n",
        encoding="utf-8",
    )

    result = tmdl_writer.rename_table(model_path, "Sales", "Fact Sales")

    assert result["ok"] is True
    renamed_file = tables_dir / "Fact Sales.tmdl"
    assert not sales_file.exists()
    assert renamed_file.exists()
    content = renamed_file.read_text(encoding="utf-8")
    assert "table 'Fact Sales'" in content
    assert "\tdefaultDetailRowsDefinition = 'Fact Sales'" in content
    assert "SUM('Fact Sales'[Amount])" in content
    assert "ref table 'Fact Sales'" in (model_path / "definition" / "model.tmdl").read_text(encoding="utf-8")
    assert "\tfromColumn: 'Fact Sales'.Amount" in (model_path / "definition" / "relationships.tmdl").read_text(
        encoding="utf-8"
    )


def test_create_backup_can_run_twice_quickly(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text("table Sales\n\tmeasure Revenue = 1\n", encoding="utf-8")

    first = tmdl_writer.create_backup(model_path)
    second = tmdl_writer.create_backup(model_path)

    assert first.exists()
    assert second.exists()
    assert first != second


def test_apply_actions_validates_whole_batch_before_writing(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Revenue = 1\n",
        encoding="utf-8",
    )

    results = tmdl_writer.apply_actions(
        model_path,
        [
            {"action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure"},
            {"action": "hide", "table": "Sales", "name": "Missing", "item_type": "Measure"},
        ],
    )

    assert all(result["ok"] is False for result in results)
    assert results[0]["skipped"] is True
    assert "Missing" in results[1]["error"]
    assert "\t\tisHidden" not in sales_file.read_text(encoding="utf-8")


def test_actions_handle_quoted_tmdl_names_and_relationships(tmp_path):
    model_path = tmp_path / "Demo.SemanticModel"
    tables_dir = model_path / "definition" / "tables"
    tables_dir.mkdir(parents=True)
    sales_file = tables_dir / "Sales Team.tmdl"
    sales_file.write_text(
        "table 'Sales Team'\n"
        "\tcolumn 'Customer Segment'\n"
        "\t\tdataType: string\n"
        "\tmeasure 'Bob''s Revenue' = 1\n",
        encoding="utf-8",
    )
    (model_path / "definition" / "relationships.tmdl").write_text(
        "relationship SalesToSegment\n"
        "\tfromColumn: 'Sales Team'.'Customer Segment'\n"
        "\ttoColumn: Segment.Id\n",
        encoding="utf-8",
    )

    hidden = tmdl_writer.set_hidden(model_path, "Sales Team", "Bob's Revenue", "Measure")
    moved = tmdl_writer.set_display_folder(
        model_path,
        "Sales Team",
        "Bob's Revenue",
        "Measure",
        "Executive Metrics",
    )
    deleted = tmdl_writer.delete_item(model_path, "Sales Team", "Customer Segment", "Column")

    content = sales_file.read_text(encoding="utf-8")
    assert hidden["ok"] is True
    assert moved["ok"] is True
    assert deleted["ok"] is True
    assert "\t\tisHidden" in content
    assert "\t\tdisplayFolder: Executive Metrics" in content
    assert "Customer Segment" not in content
    assert "SalesToSegment" not in (model_path / "definition" / "relationships.tmdl").read_text(
        encoding="utf-8"
    )


def test_analyze_after_cleanup_on_fixture_copy(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree("examples/public-demo-workspace", workspace)
    model_path = workspace / "Models" / "TestModel.SemanticModel"
    report_path = workspace / "Reports" / "TestReport.Report"

    before = analyzer.analyze(workspace, model_paths=[model_path], report_paths=[report_path])
    delete_result = tmdl_writer.apply_actions(
        model_path,
        [
            {
                "action": "delete",
                "table": "Metric Parameter",
                "name": "Metric Fields",
                "item_type": "Column",
            }
        ],
    )
    after = analyzer.analyze(workspace, model_paths=[model_path], report_paths=[report_path])

    assert before["summary"]["total_columns"] == 2
    assert delete_result[0]["ok"] is True
    assert after["summary"]["total_columns"] == 1
    assert all(row["item"].name != "Metric Fields" for row in after["items"])
