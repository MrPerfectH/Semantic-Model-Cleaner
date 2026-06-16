import json

from semantic_model_cleaner import report_writer


def test_create_backup_can_run_twice_quickly(tmp_path):
    report_path = tmp_path / "Executive.Report"
    definition_dir = report_path / "definition"
    definition_dir.mkdir(parents=True)
    (definition_dir / "report.json").write_text("{}", encoding="utf-8")

    first = report_writer.create_backup(report_path)
    second = report_writer.create_backup(report_path)

    assert first.exists()
    assert second.exists()
    assert first != second


def test_rewrite_measure_table_references_updates_selected_pbir_files(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    bookmark_dir = report_path / "definition" / "bookmarks"
    visual_dir.mkdir(parents=True)
    bookmark_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    bookmark_file = bookmark_dir / "Bookmark1.bookmark.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Entity": "_Measures"}},
                                                "Property": "Revenue LY",
                                            }
                                        },
                                        "queryRef": "_Measures.Revenue LY",
                                        "queryRefs": ["_Measures.Revenue LY", "_Measures.Other"],
                                    }
                                ]
                            }
                        }
                    },
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "_Measures.Revenue LY"}},
                            {"selector": {"metadata": "_Measures.Other"}},
                        ]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bookmark_file.write_text(
        json.dumps(
            {
                "explorationState": {
                    "sections": {
                        "Page1": {
                            "visualContainers": {
                                "Visual1": {
                                    "singleVisual": {
                                        "projections": {
                                            "Y": [
                                                {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "_Measures"}},
                                                        "Property": "Revenue LY",
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    preview = report_writer.rewrite_measure_table_references(
        report_paths=[report_path],
        moves=[{"table": "_Measures", "name": "Revenue LY", "target_table": "Sales"}],
        dry_run=True,
    )
    assert preview["ok"] is True
    assert preview["updated_reference_count"] == 5
    assert "_Measures.Revenue LY" in visual_file.read_text(encoding="utf-8")

    result = report_writer.rewrite_measure_table_references(
        report_paths=[report_path],
        moves=[{"table": "_Measures", "name": "Revenue LY", "target_table": "Sales"}],
    )

    assert result["ok"] is True
    assert result["updated_file_count"] == 2
    assert result["updated_reference_count"] == 5
    visual_payload = json.loads(visual_file.read_text(encoding="utf-8"))
    projection = visual_payload["visual"]["query"]["queryState"]["Y"]["projections"][0]
    assert projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Sales"
    assert projection["queryRef"] == "Sales.Revenue LY"
    assert projection["queryRefs"] == ["Sales.Revenue LY", "_Measures.Other"]
    assert visual_payload["visual"]["objects"]["labels"][0]["selector"]["metadata"] == "Sales.Revenue LY"
    bookmark_payload = json.loads(bookmark_file.read_text(encoding="utf-8"))
    bookmark_measure = bookmark_payload["explorationState"]["sections"]["Page1"]["visualContainers"]["Visual1"]["singleVisual"]["projections"]["Y"][0]["Measure"]
    assert bookmark_measure["Expression"]["SourceRef"]["Entity"] == "Sales"


def test_rewrite_measure_table_references_updates_source_ref_alias_from_entry(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "SemanticQueryDataShapeCommand": {
                            "Query": {
                                "From": [{"Name": "m", "Entity": "_Measures", "Type": 0}],
                                "Select": [
                                    {
                                        "Measure": {
                                            "Expression": {"SourceRef": {"Source": "m"}},
                                            "Property": "Revenue LY",
                                        }
                                    }
                                ],
                            }
                        },
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Source": "m"}},
                                                "Property": "Revenue LY",
                                            }
                                        },
                                        "queryRef": "m.Revenue LY",
                                    }
                                ]
                            }
                        },
                    },
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "m.Revenue LY"}},
                        ]
                    },
                    "customMetadata": {"Entity": "_Measures"},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.rewrite_measure_table_references(
        report_paths=[report_path],
        moves=[{"table": "_Measures", "name": "Revenue LY", "target_table": "Sales"}],
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    query = payload["visual"]["query"]
    from_entry = query["SemanticQueryDataShapeCommand"]["Query"]["From"][0]
    projection = query["queryState"]["Y"]["projections"][0]
    assert from_entry["Entity"] == "Sales"
    assert projection["field"]["Measure"]["Expression"]["SourceRef"]["Source"] == "m"
    assert projection["queryRef"] == "m.Revenue LY"
    assert payload["visual"]["objects"]["labels"][0]["selector"]["metadata"] == "m.Revenue LY"
    assert payload["visual"]["customMetadata"]["Entity"] == "_Measures"


def test_rewrite_model_reference_changes_updates_table_and_measure_names(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                "Property": "Revenue",
                                            }
                                        },
                                        "queryRef": "Sales.Revenue",
                                    }
                                ]
                            },
                            "Category": {
                                "projections": [
                                    {
                                        "field": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                "Property": "Region",
                                            }
                                        },
                                        "queryRef": "Sales.Region",
                                    }
                                ]
                            },
                        }
                    },
                    "filterConfig": {
                        "filters": [
                            {
                                "field": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                                        "Property": "Amount",
                                    }
                                },
                                "filter": {
                                    "Version": 2,
                                    "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                                },
                            }
                        ]
                    },
                    "objects": {
                        "columns": [
                            {
                                "properties": {
                                    "field": {
                                        "expr": {
                                            "Aggregation": {
                                                "Expression": {
                                                    "Column": {
                                                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                        "Property": "Amount",
                                                    }
                                                },
                                                "Function": 0,
                                            }
                                        }
                                    },
                                    "queryRef": "Sum(Sales.Amount)",
                                }
                            }
                        ]
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_extensions = report_path / "definition" / "reportExtensions.json"
    report_extensions.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "name": "Sales",
                        "measures": [
                            {
                                "name": "Report Margin",
                                "expression": "CALCULATE([Revenue], Sales[Amount] > 0)",
                                "references": {"columns": [{"entity": "Sales", "name": "Amount"}]},
                            }
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report_path],
        table_renames=[{"table": "Sales", "target_table": "Fact Sales"}],
        measure_renames=[{"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}],
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    y_projection = payload["visual"]["query"]["queryState"]["Y"]["projections"][0]
    category_projection = payload["visual"]["query"]["queryState"]["Category"]["projections"][0]
    filter_from = payload["visual"]["filterConfig"]["filters"][0]["filter"]["From"][0]
    column_object = payload["visual"]["objects"]["columns"][0]["properties"]
    extension_payload = json.loads(report_extensions.read_text(encoding="utf-8"))
    extension_entity = extension_payload["entities"][0]
    extension_measure = extension_entity["measures"][0]
    assert y_projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "Fact Sales"
    assert y_projection["field"]["Measure"]["Property"] == "Net Revenue"
    assert y_projection["queryRef"] == "Fact Sales.Net Revenue"
    assert category_projection["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Fact Sales"
    assert category_projection["queryRef"] == "Fact Sales.Region"
    assert filter_from["Entity"] == "Fact Sales"
    assert column_object["field"]["expr"]["Aggregation"]["Expression"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Fact Sales"
    assert column_object["queryRef"] == "Sum(Fact Sales.Amount)"
    assert extension_entity["name"] == "Fact Sales"
    assert extension_measure["expression"] == "CALCULATE([Revenue], 'Fact Sales'[Amount] > 0)"
    assert extension_measure["references"]["columns"][0]["entity"] == "Fact Sales"


def test_rewrite_model_reference_changes_updates_alias_backed_measure_rename(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "SemanticQueryDataShapeCommand": {
                            "Query": {
                                "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                                "Select": [
                                    {
                                        "Measure": {
                                            "Expression": {"SourceRef": {"Source": "s"}},
                                            "Property": "Revenue",
                                        }
                                    }
                                ],
                            }
                        },
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Source": "s"}},
                                                "Property": "Revenue",
                                            }
                                        },
                                        "queryRef": "s.Revenue",
                                    }
                                ]
                            }
                        },
                    },
                    "customMetadata": {"Entity": "Sales"},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report_path],
        table_renames=[{"table": "Sales", "target_table": "Fact Sales"}],
        measure_renames=[{"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}],
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    query = payload["visual"]["query"]
    from_entry = query["SemanticQueryDataShapeCommand"]["Query"]["From"][0]
    projection = query["queryState"]["Y"]["projections"][0]
    assert from_entry["Entity"] == "Fact Sales"
    assert projection["field"]["Measure"]["Expression"]["SourceRef"]["Source"] == "s"
    assert projection["field"]["Measure"]["Property"] == "Net Revenue"
    assert projection["queryRef"] == "s.Net Revenue"
    assert payload["visual"]["customMetadata"]["Entity"] == "Sales"


def test_rewrite_model_reference_changes_rejects_invalid_schema_declared_visual(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
                "name": "Visual1",
                "visual": {
                    "query": {
                        "queryState": {
                            "Y": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                "Property": "Revenue",
                                            }
                                        },
                                        "queryRef": "Sales.Revenue",
                                    }
                                ]
                            }
                        }
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report_path],
        table_renames=[{"table": "Sales", "target_table": "Fact Sales"}],
    )

    assert result["ok"] is False
    assert result["validation_errors"][0]["file"] == str(visual_file)
    assert "position" in result["validation_errors"][0]["message"]
    assert "Fact Sales" not in visual_file.read_text(encoding="utf-8")


def test_rewrite_model_reference_changes_rejects_invalid_schema_declared_report(tmp_path):
    report_path = tmp_path / "Executive.Report"
    definition_dir = report_path / "definition"
    definition_dir.mkdir(parents=True)
    report_file = definition_dir / "report.json"
    report_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
                "filters": [
                    {
                        "field": {
                            "Column": {
                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                "Property": "Amount",
                            }
                        }
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.rewrite_model_reference_changes(
        report_paths=[report_path],
        table_renames=[{"table": "Sales", "target_table": "Fact Sales"}],
    )

    assert result["ok"] is False
    assert result["validation_errors"][0]["file"] == str(report_file)
    assert "themeCollection" in result["validation_errors"][0]["message"]
    assert "Fact Sales" not in report_file.read_text(encoding="utf-8")


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


def test_migrate_report_measure_to_model_preserves_supported_metadata(tmp_path):
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
                                "dataCategory": "Currency",
                                "description": "Revenue defined in the report.",
                                "expression": "[Existing] + 1",
                                "displayFolder": "Executive",
                                "formatString": "$#,0.00",
                                "hidden": True,
                                "annotations": [
                                    {"name": "CreatedBy", "value": "Report extension"},
                                    {"name": "SemanticModelCleaner", "value": "Promoted"},
                                ],
                                "measureTemplate": {
                                    "daxTemplateName": "QuickMeasure",
                                    "version": 1,
                                },
                            }
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
    assert result["preserved_metadata"] == [
        "expression",
        "dataType",
        "dataCategory",
        "description",
        "displayFolder",
        "formatString",
        "hidden",
        "annotations",
    ]
    assert result["unpreserved_metadata"] == [
        {
            "field": "measureTemplate",
            "reason": "Report extension measure templates are creation metadata and do not have a TMDL measure equivalent.",
        }
    ]

    sales_content = sales_file.read_text(encoding="utf-8")
    assert "\t/// Revenue defined in the report." in sales_content
    assert "\tmeasure 'Report Revenue' = [Existing] + 1" in sales_content
    assert "\t\tdataType: double" in sales_content
    assert "\t\tdataCategory: Currency" in sales_content
    assert "\t\tformatString: $#,0.00" in sales_content
    assert "\t\tdisplayFolder: Executive" in sales_content
    assert "\t\tisHidden" in sales_content
    assert "\t\tannotation CreatedBy = Report extension" in sales_content
    assert "\t\tannotation SemanticModelCleaner = Promoted" in sales_content


def test_migrate_report_measure_to_model_rolls_back_when_report_save_fails(monkeypatch, tmp_path):
    model_path = tmp_path / "Sales.SemanticModel"
    report_path = tmp_path / "Executive.Report"
    tables_dir = model_path / "definition" / "tables"
    report_def_dir = report_path / "definition"
    tables_dir.mkdir(parents=True)
    report_def_dir.mkdir(parents=True)

    sales_file = tables_dir / "Sales.tmdl"
    extensions_file = report_def_dir / "reportExtensions.json"
    sales_file.write_text(
        "table Sales\n"
        "\tmeasure Existing = 1\n",
        encoding="utf-8",
    )
    extensions_file.write_text(
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
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    original_sales = sales_file.read_text(encoding="utf-8")
    original_extensions = extensions_file.read_text(encoding="utf-8")

    def fail_save(*_args, **_kwargs):
        raise ValueError("Report extension save failed")

    monkeypatch.setattr(report_writer, "_save_report_extensions", fail_save)

    result = report_writer.migrate_measure_to_model(
        model_path=model_path,
        report_path=report_path,
        entity_name="Sales",
        measure_name="Report Revenue",
    )

    assert result["ok"] is False
    assert result["rolled_back"] is True
    assert "Report extension save failed" in result["error"]
    assert sales_file.read_text(encoding="utf-8") == original_sales
    assert extensions_file.read_text(encoding="utf-8") == original_extensions


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


def test_cleanup_stale_metadata_selectors_rejects_invalid_file_before_writing(tmp_path):
    report_path = tmp_path / "Executive.Report"
    first_visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    second_visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual2"
    first_visual_dir.mkdir(parents=True)
    second_visual_dir.mkdir(parents=True)
    first_visual = first_visual_dir / "visual.json"
    second_visual = second_visual_dir / "visual.json"
    first_visual.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {"queryState": {"Y": {"projections": []}}},
                    "objects": {
                        "labels": [
                            {
                                "properties": {"show": {"expr": {"Literal": {"Value": "true"}}}},
                                "selector": {"metadata": "_Measures.Stale"},
                            }
                        ]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    second_visual.write_text("{ bad json", encoding="utf-8")
    original_first = first_visual.read_text(encoding="utf-8")

    result = report_writer.cleanup_stale_metadata_selectors(
        entries=[
            {
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "selector_value": "_Measures.Stale",
            },
            {
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual2/visual.json",
                "selector_value": "_Measures.Stale",
            },
        ]
    )

    assert result["ok"] is False
    assert "Invalid JSON" in result["error"]
    assert first_visual.read_text(encoding="utf-8") == original_first


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


def test_apply_report_issue_actions_removes_orphan_bookmark_visual_state(tmp_path):
    report_path = tmp_path / "Executive.Report"
    bookmark_dir = report_path / "definition" / "bookmarks"
    bookmark_dir.mkdir(parents=True)
    bookmark_file = bookmark_dir / "bookmark1.bookmark.json"
    bookmark_file.write_text(
        json.dumps(
            {
                "displayName": "A&P Spend",
                "explorationState": {
                    "sections": {
                        "Page1": {
                            "visualContainers": {
                                "Visual1": {"singleVisual": {"visualType": "card"}},
                                "DeletedVisual": {"singleVisual": {"visualType": "card"}},
                            }
                        }
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/bookmarks/bookmark1.bookmark.json",
                "source_path": "explorationState.sections.Page1.visualContainers.DeletedVisual",
            }
        ]
    )

    assert result["ok"] is True
    assert result["updated_reference_count"] == 1
    payload = json.loads(bookmark_file.read_text(encoding="utf-8"))
    visual_containers = payload["explorationState"]["sections"]["Page1"]["visualContainers"]
    assert "DeletedVisual" not in visual_containers
    assert "Visual1" in visual_containers


def test_cleanup_stale_formatting_selector_entries_removes_exact_data_point(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "columnChart",
                    "objects": {
                        "dataPoint": [
                            {
                                "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#228B22'"}}}}}},
                                "selector": {
                                    "data": [
                                        {
                                            "scopeId": {
                                                "Comparison": {
                                                    "Left": {
                                                        "Column": {
                                                            "Expression": {"SourceRef": {"Entity": "Legacy Sales"}},
                                                            "Property": "Old Region",
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    ]
                                },
                            },
                            {
                                "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#E87722'"}}}}}},
                                "selector": {
                                    "data": [
                                        {
                                            "scopeId": {
                                                "Comparison": {
                                                    "Left": {
                                                        "Column": {
                                                            "Expression": {"SourceRef": {"Entity": "Legacy Sales"}},
                                                            "Property": "Old Region",
                                                        }
                                                    },
                                                    "Right": {"Literal": {"Value": "'West'"}},
                                                }
                                            }
                                        }
                                    ]
                                },
                            },
                            {
                                "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#000000'"}}}}}},
                            },
                        ]
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
                "source_path": "visual.objects.dataPoint.[0].selector.data.[0].scopeId.Comparison.Left.Column",
                "selector_value": "Legacy Sales[Old Region]",
                "stale_kind": "visual_formatting_selector_entry",
            }
        ]
    )

    assert result["ok"] is True
    assert result["removed_count"] == 2

    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    data_points = payload["visual"]["objects"]["dataPoint"]
    assert len(data_points) == 1
    assert "selector" not in data_points[0]


def test_cleanup_stale_formatting_rule_removes_values_rule_entry(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "tableEx",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "Current Sales"}},
                                                "Property": "Region",
                                            }
                                        },
                                        "queryRef": "Current Sales.Region",
                                    }
                                ]
                            }
                        }
                    },
                    "objects": {
                        "values": [
                            {
                                "properties": {
                                    "fontFamily": {"expr": {"Literal": {"Value": "'Calibri'"}}},
                                },
                            },
                            {
                                "properties": {
                                    "fontColor": {
                                        "solid": {
                                            "color": {
                                                "expr": {
                                                    "FillRule": {
                                                        "Input": {
                                                            "Aggregation": {
                                                                "Expression": {
                                                                    "Column": {
                                                                        "Expression": {"SourceRef": {"Entity": "Orders"}},
                                                                        "Property": "Sales",
                                                                    }
                                                                },
                                                                "Function": 0,
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                                "selector": {
                                    "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                    "metadata": "Sum(Orders.Sales)",
                                },
                            },
                            {
                                "properties": {
                                    "backColor": {
                                        "solid": {
                                            "color": {
                                                "expr": {
                                                    "Conditional": {
                                                        "Cases": [
                                                            {
                                                                "Condition": {
                                                                    "Comparison": {
                                                                        "Left": {
                                                                            "Aggregation": {
                                                                                "Expression": {
                                                                                    "Column": {
                                                                                        "Expression": {"SourceRef": {"Entity": "Orders"}},
                                                                                        "Property": "Sales",
                                                                                    }
                                                                                },
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        ]
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                        ]
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
                "source_path": "visual.objects.values.[1].properties.fontColor.solid.color.expr.FillRule.Input.Aggregation",
                "selector_value": "Orders[Sales]",
                "stale_kind": "formatting_rule_reference",
            }
        ]
    )

    assert result["ok"] is True
    assert result["removed_count"] == 2

    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    assert len(payload["visual"]["objects"]["values"]) == 1
    assert "fontFamily" in payload["visual"]["objects"]["values"][0]["properties"]
    projections = payload["visual"]["query"]["queryState"]["Values"]["projections"]
    assert projections[0]["field"]["Column"]["Property"] == "Region"


def test_cleanup_mixed_path_entries_removes_all_in_one_pass(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "tableEx",
                    "objects": {
                        "values": [
                            {
                                "properties": {
                                    "fontColor": {
                                        "solid": {
                                            "color": {
                                                "expr": {
                                                    "FillRule": {
                                                        "Input": {
                                                            "Aggregation": {
                                                                "Expression": {
                                                                    "Column": {
                                                                        "Expression": {"SourceRef": {"Entity": "Orders"}},
                                                                        "Property": "Sales",
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            {
                                "field": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Entity": "Legacy"}},
                                        "Property": "Removed",
                                    }
                                }
                            },
                            {
                                "properties": {
                                    "fontColor": {
                                        "solid": {
                                            "color": {
                                                "expr": {
                                                    "FillRule": {
                                                        "Input": {
                                                            "Aggregation": {
                                                                "Expression": {
                                                                    "Column": {
                                                                        "Expression": {"SourceRef": {"Entity": "Orders"}},
                                                                        "Property": "Margin",
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            {"properties": {"fontFamily": {"expr": {"Literal": {"Value": "'Calibri'"}}}}},
                        ]
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
                "source_path": "visual.objects.values.[0].properties.fontColor.solid.color.expr.FillRule.Input.Aggregation",
                "selector_value": "Orders[Sales]",
                "stale_kind": "formatting_rule_reference",
            },
                {
                    "report_path": str(report_path),
                    "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                    "source_path": "visual.objects.values.[1]",
                    "stale_kind": "exact_reference",
                },
            {
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.objects.values.[2].properties.fontColor.solid.color.expr.FillRule.Input.Aggregation",
                "selector_value": "Orders[Margin]",
                "stale_kind": "formatting_rule_reference",
            },
        ]
    )

    assert result["ok"] is True
    assert result["removed_count"] == 3

    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    values = payload["visual"]["objects"]["values"]
    assert len(values) == 1
    assert "fontFamily" in values[0]["properties"]


def test_apply_report_issue_actions_replaces_exact_projection_reference(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "Old Sales"}},
                                                "Property": "Old Region",
                                            }
                                        },
                                        "queryRef": "Old Sales.Old Region",
                                    }
                                ]
                            }
                        }
                    },
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "Old Sales.Old Region"}},
                            {"selector": {"metadata": "Other.Table"}},
                        ]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "replace",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.query.queryState.Values.projections.[0].field.Column",
                "table": "Old Sales",
                "name": "Old Region",
                "target_table": "Sales",
                "target_name": "Region",
            }
        ]
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    projection = payload["visual"]["query"]["queryState"]["Values"]["projections"][0]
    assert projection["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Sales"
    assert projection["field"]["Column"]["Property"] == "Region"
    assert projection["queryRef"] == "Sales.Region"
    assert payload["visual"]["objects"]["labels"][0]["selector"]["metadata"] == "Old Sales.Old Region"
    assert payload["visual"]["objects"]["labels"][1]["selector"]["metadata"] == "Other.Table"


def test_apply_report_issue_actions_replaces_filter_alias_reference(tmp_path):
    report_path = tmp_path / "Executive.Report"
    page_dir = report_path / "definition" / "pages" / "Page1"
    page_dir.mkdir(parents=True)
    page_file = page_dir / "page.json"
    page_file.write_text(
        json.dumps(
            {
                "filterConfig": {
                    "filters": [
                        {
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": "Cost Center"}},
                                    "Property": "cost_center_status_name",
                                }
                            },
                            "filter": {
                                "From": [{"Name": "c", "Entity": "Cost_Center", "Type": 0}],
                                "Where": [
                                    {
                                        "Condition": {
                                            "In": {
                                                "Expressions": [
                                                    {
                                                        "Column": {
                                                            "Expression": {"SourceRef": {"Source": "c"}},
                                                            "Property": "cost_center_include_status",
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                            },
                        }
                    ]
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "replace",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/page.json",
                "source_path": "filterConfig.filters.[0].filter.Where.[0].Condition.In.Expressions.[0].Column",
                "table": "Cost_Center",
                "name": "cost_center_include_status",
                "target_table": "Cost Center",
                "target_name": "cost_center_status_name",
            }
        ]
    )

    assert result["ok"] is True
    payload = json.loads(page_file.read_text(encoding="utf-8"))
    filter_obj = payload["filterConfig"]["filters"][0]
    assert filter_obj["filter"]["From"][0]["Entity"] == "Cost Center"
    expression = filter_obj["filter"]["Where"][0]["Condition"]["In"]["Expressions"][0]["Column"]
    assert expression["Expression"]["SourceRef"]["Source"] == "c"
    assert expression["Property"] == "cost_center_status_name"


def test_apply_report_issue_actions_removes_filter_and_formatting_property(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "objects": {
                        "values": [
                            {
                                "properties": {
                                    "fontColor": {
                                        "solid": {
                                            "color": {
                                                "expr": {
                                                    "FillRule": {
                                                        "Input": {
                                                            "Aggregation": {
                                                                "Expression": {
                                                                    "Column": {
                                                                        "Expression": {"SourceRef": {"Entity": "Orders"}},
                                                                        "Property": "Sales",
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    },
                                    "alignment": {"expr": {"Literal": {"Value": "'left'"}}},
                                }
                            }
                        ]
                    }
                },
                "filterConfig": {
                    "filters": [
                        {
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": "Old Sales"}},
                                    "Property": "Old Region",
                                }
                            }
                        },
                        {
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": "Keep"}},
                                    "Property": "Keep Me",
                                }
                            }
                        },
                    ]
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "filterConfig.filters.[0].field.Column",
            },
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.objects.values.[0].properties.fontColor.solid.color.expr.FillRule.Input.Aggregation",
            },
        ]
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    assert len(payload["filterConfig"]["filters"]) == 1
    assert payload["filterConfig"]["filters"][0]["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Keep"
    properties = payload["visual"]["objects"]["values"][0]["properties"]
    assert "fontColor" not in properties
    assert "alignment" in properties


def test_apply_report_issue_actions_removes_multiple_filter_rows_in_one_pass(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "filterConfig": {
                        "filters": [
                            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "A"}}},
                            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "B"}}},
                            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "C"}}},
                            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "D"}}},
                        ]
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": f"visual.filterConfig.filters.[{idx}].field.Column",
                "table": "T",
                "name": name,
                "ref_type": "Column",
            }
            for idx, name in enumerate(["A", "B", "C", "D"])
        ]
    )

    assert result["ok"] is True
    assert result["updated_reference_count"] == 4
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    assert payload["visual"]["filterConfig"]["filters"] == []


def test_apply_report_issue_actions_removes_related_visual_references(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "Old Table"}},
                                                "Property": "Old Field",
                                            }
                                        }
                                    },
                                    {
                                        "field": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "Keep"}},
                                                "Property": "Keep Field",
                                            }
                                        }
                                    },
                                ]
                            }
                        },
                        "sortDefinition": {
                            "sort": [
                                {
                                    "field": {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Entity": "Old Table"}},
                                            "Property": "Old Field",
                                        }
                                    }
                                }
                            ]
                        },
                    },
                    "objects": {
                        "labels": [
                            {"selector": {"metadata": "Old Table.Old Field"}},
                            {"selector": {"metadata": "Keep.Keep Field"}},
                        ]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.query.queryState.Values.projections.[0].field.Column",
                "table": "Old Table",
                "name": "Old Field",
            }
        ]
    )

    assert result["ok"] is True
    payload = json.loads(visual_file.read_text(encoding="utf-8"))
    values = payload["visual"]["query"]["queryState"]["Values"]["projections"]
    assert len(values) == 1
    assert values[0]["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "Keep"
    assert payload["visual"]["query"]["sortDefinition"]["sort"] == []
    assert payload["visual"]["objects"]["labels"] == [{"selector": {"metadata": "Keep.Keep Field"}}]


def _write_remove_fixture(report_path, entity="Old Table", prop="Old Field"):
    visual_dir = report_path / "definition" / "pages" / "Page1" / "visuals" / "Visual1"
    visual_dir.mkdir(parents=True)
    visual_file = visual_dir / "visual.json"
    visual_file.write_text(
        json.dumps(
            {
                "visual": {
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {"field": {"Column": {
                                        "Expression": {"SourceRef": {"Entity": entity}},
                                        "Property": prop,
                                    }}},
                                ]
                            }
                        }
                    },
                    "objects": {
                        "labels": [{"selector": {"metadata": f"{entity}.{prop}"}}]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return visual_file


def test_apply_report_issue_actions_dry_run_previews_without_writing(tmp_path):
    report_path = tmp_path / "Executive.Report"
    visual_file = _write_remove_fixture(report_path)
    before = visual_file.read_text(encoding="utf-8")

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.query.queryState.Values.projections.[0].field.Column",
                "table": "Old Table",
                "name": "Old Field",
            }
        ],
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    # The preview reports what WOULD change, including the related sibling sweep...
    assert result["updated_reference_count"] >= 1
    # ...but nothing is written to disk.
    assert visual_file.read_text(encoding="utf-8") == before


def test_apply_report_issue_actions_aborts_without_writing_when_validation_fails(tmp_path, monkeypatch):
    report_path = tmp_path / "Executive.Report"
    visual_file = _write_remove_fixture(report_path)
    before = visual_file.read_text(encoding="utf-8")

    monkeypatch.setattr(
        report_writer,
        "validate_pbir_json_file",
        lambda *args, **kwargs: {"ok": False, "errors": [{"file": str(visual_file), "message": "boom"}]},
    )

    result = report_writer.apply_report_issue_actions(
        entries=[
            {
                "action": "remove",
                "report_path": str(report_path),
                "artifact_path": "definition/pages/Page1/visuals/Visual1/visual.json",
                "source_path": "visual.query.queryState.Values.projections.[0].field.Column",
                "table": "Old Table",
                "name": "Old Field",
            }
        ],
    )

    assert result["ok"] is False
    assert result.get("validation_errors")
    # A failed validation must leave every report file byte-for-byte unchanged.
    assert visual_file.read_text(encoding="utf-8") == before
