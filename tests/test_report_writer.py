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


def test_cleanup_stale_metadata_selectors_removes_only_unmatched_entries(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "lineClusteredColumnComboChart",
                    "query": {
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "queryRef": "_Measures.PL_LINE Actuals"
                                    },
                                    {
                                        "queryRef": "_Measures.PL_LINE Budget"
                                    }
                                ]
                            }
                        }
                    },
                    "objects": {
                        "labels": [
                            {
                                "properties": {"show": {"expr": {"Literal": {"Value": "true"}}}},
                                "selector": {"metadata": "_Measures.Revenue LY"},
                            },
                            {
                                "properties": {"show": {"expr": {"Literal": {"Value": "true"}}}},
                                "selector": {"metadata": "_Measures.PL_LINE Budget"},
                            },
                        ],
                        "dataPoint": [
                            {
                                "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#000000'"}}}}}},
                                "selector": {"metadata": "_Measures.Revenue LY"},
                            }
                        ],
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.cleanup_stale_metadata_selectors(
        entries=[
            {
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "selector_value": "_Measures.Revenue LY",
            }
        ]
    )

    assert result["ok"] is True
    assert result["removed_count"] == 2

    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    labels = payload["visual"]["objects"]["labels"]
    data_points = payload["visual"]["objects"]["dataPoint"]
    assert len(labels) == 1
    assert labels[0]["selector"]["metadata"] == "_Measures.PL_LINE Budget"
    assert data_points == []


def test_cleanup_stale_bookmark_projection_entries_removes_exact_projection_row(tmp_path):
    report_path = tmp_path / "Executive.Report"
    bookmark_dir = report_path / "definition" / "bookmarks"
    bookmark_dir.mkdir(parents=True)
    bookmark_file = bookmark_dir / "bookmark1.bookmark.json"
    bookmark_file.write_text(
        json.dumps(
            {
                "displayName": "A&P Spend",
                "name": "bookmark1",
                "explorationState": {
                    "activeSection": "Page1",
                    "sections": {
                        "Page1": {
                            "visualContainers": {
                                "Visual1": {
                                    "singleVisual": {
                                        "projections": {
                                            "Y2": [
                                                {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "_Measures"}},
                                                        "Property": "A&P - LY",
                                                    }
                                                },
                                                {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "_Measures"}},
                                                        "Property": "PL_LINE LY",
                                                    }
                                                },
                                            ]
                                        },
                                        "parameters": {
                                            "Y2": [
                                                {
                                                    "expr": {
                                                        "Column": {
                                                            "Expression": {"SourceRef": {"Entity": "FP_KPI_Finance"}},
                                                            "Property": "FP_KPI_Finance",
                                                        }
                                                    }
                                                }
                                            ]
                                        },
                                    }
                                }
                            }
                        }
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.cleanup_stale_metadata_selectors(
        entries=[
            {
                "report_path": str(report_path),
                "artifact_path": "definition/bookmarks/bookmark1.bookmark.json",
                "source_path": "explorationState.sections.Page1.visualContainers.Visual1.singleVisual.projections.Y2.[0].Measure",
                "stale_kind": "bookmark_projection_entry",
            }
        ]
    )

    assert result["ok"] is True
    assert result["removed_count"] == 1

    payload = json.loads(bookmark_file.read_text(encoding="utf-8"))
    projections = payload["explorationState"]["sections"]["Page1"]["visualContainers"]["Visual1"]["singleVisual"]["projections"]["Y2"]
    assert len(projections) == 1
    assert projections[0]["Measure"]["Property"] == "PL_LINE LY"
