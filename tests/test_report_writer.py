import json

from semantic_model_cleaner import report_writer


def test_migrate_report_measure_to_model_moves_definition_and_rewrites_refs(tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    report_def_dir = report_path / "definition"
    tables_dir.mkdir(parents=True)
    report_def_dir.mkdir(parents=True)

    sales_file = tables_dir / "Sales.tmdl"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Existing = 1\n",
        encoding="utf-8",
    )
    (report_def_dir / "reportExtensions.json").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json",
                "name": "extension",
                "entities": [
                    {
                        "name": "Sales",
                        "measures": [
                            {
                                "name": "Report Revenue",
                                "dataType": "Double",
                                "expression": "[Existing] + 1",
                                "displayFolder": "Executive",
                                "formatString": "0.0",
                                "hidden": True,
                            },
                            {
                                "name": "KPI Label",
                                "dataType": "Text",
                                "expression": "FORMAT([Report Revenue], \"0.0\")",
                                "references": {
                                    "measures": [
                                        {
                                            "schema": "extension",
                                            "entity": "Sales",
                                            "name": "Report Revenue",
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.migrate_measure_to_model(
        model_path=model_path,
        report_path=report_path,
        entity_name="Sales",
        measure_name="Report Revenue",
    )

    assert result["ok"] is True
    assert result["updated_reference_count"] == 1

    sales_content = sales_file.read_text(encoding="utf-8")
    assert "\tmeasure 'Report Revenue' = [Existing] + 1" in sales_content
    assert "\t\tformatString: 0.0" in sales_content
    assert "\t\tdisplayFolder: Executive" in sales_content
    assert "\t\tisHidden" in sales_content

    updated_extensions = json.loads((report_def_dir / "reportExtensions.json").read_text(encoding="utf-8"))
    measures = updated_extensions["entities"][0]["measures"]
    assert [measure["name"] for measure in measures] == ["KPI Label"]
    assert measures[0]["references"]["measures"] == [{"entity": "Sales", "name": "Report Revenue"}]
