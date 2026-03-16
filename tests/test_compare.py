from pathlib import Path

from semantic_model_cleaner import compare


def _write_model(model_dir: Path, *, model_tmdl: str, tables: dict[str, str], relationships: str = "") -> None:
    definition = model_dir / "definition"
    tables_dir = definition / "tables"
    tables_dir.mkdir(parents=True)
    (definition / "model.tmdl").write_text(model_tmdl, encoding="utf-8")
    if relationships:
        (definition / "relationships.tmdl").write_text(relationships, encoding="utf-8")
    for filename, text in tables.items():
        (tables_dir / filename).write_text(text, encoding="utf-8")


def _changes_for_level(results: dict, level: str) -> list[dict]:
    return [c for c in results["changes"] if c["level"] == level]


def test_compare_detects_add_remove_change_across_levels(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"

    _write_model(
        baseline,
        model_tmdl=(
            "model Baseline\n"
            "\tcompatibilityLevel: 1601\n"
            "\tdiscourageImplicitMeasures\n"
        ),
        relationships=(
            "relationship SalesToDate\n"
            "\tfromColumn: Sales.DateKey\n"
            "\ttoColumn: Date.DateKey\n"
            "\tfromCardinality: many\n"
            "\ttoCardinality: one\n"
            "\tisActive: true\n"
        ),
        tables={
            "Sales.tmdl": (
                "table Sales\n"
                "\tisHidden\n"
                "\tmeasure Revenue = SUM(Sales[Amount])\n"
                "\tmeasure Gross = SUM(Sales[Gross])\n"
                "\tcolumn Amount\n"
                "\t\tdisplayFolder: Metrics\n"
                "\tcolumn LegacyName\n"
            ),
            "Date.tmdl": (
                "table Date\n"
                "\tcolumn DateKey\n"
            ),
        },
    )

    _write_model(
        candidate,
        model_tmdl=(
            "model Candidate\n"
            "\tcompatibilityLevel: 1602\n"
            "\tdiscourageImplicitMeasures\n"
        ),
        relationships=(
            "relationship SalesToDate\n"
            "\tfromColumn: Sales.DateKey\n"
            "\ttoColumn: Date.DateKey\n"
            "\tfromCardinality: many\n"
            "\ttoCardinality: one\n"
            "\tisActive: false\n"
            "\n"
            "relationship SalesToProduct\n"
            "\tfromColumn: Sales.ProductKey\n"
            "\ttoColumn: Product.ProductKey\n"
            "\tfromCardinality: many\n"
            "\ttoCardinality: one\n"
            "\tisActive: true\n"
        ),
        tables={
            "Sales.tmdl": (
                "table Sales\n"
                "\tisHidden: false\n"
                "\tmeasure Revenue = SUM(Sales[NetAmount])\n"
                "\tmeasure Net = SUM(Sales[NetAmount])\n"
                "\tcolumn Amount\n"
                "\t\tdisplayFolder: Core\n"
                "\tcolumn NewName\n"
            ),
            "Product.tmdl": (
                "table Product\n"
                "\tcolumn ProductKey\n"
            ),
        },
    )

    results = compare.compare_models(baseline, candidate)
    levels = results["summary"]["levels"]

    assert levels["model"]["changed"] == 1
    assert levels["relationship"]["added"] == 1
    assert levels["relationship"]["changed"] == 1
    assert levels["table"]["added"] == 1
    assert levels["table"]["removed"] == 1
    assert levels["table"]["changed"] == 1
    assert levels["measure"]["added"] == 1
    assert levels["measure"]["removed"] == 1
    assert levels["measure"]["changed"] == 1
    assert levels["column"]["added"] == 1
    assert levels["column"]["removed"] == 1
    assert levels["column"]["changed"] == 1

    measure_changes = _changes_for_level(results, "measure")
    revenue = next(c for c in measure_changes if c["name"] == "Revenue")
    assert revenue["changeType"] == "changed"
    assert revenue["propertyChanges"][0]["property"] == "expression"


def test_compare_does_not_emit_child_diffs_for_removed_table(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"

    _write_model(
        baseline,
        model_tmdl="model Baseline\n",
        tables={
            "Legacy.tmdl": (
                "table Legacy\n"
                "\tmeasure OldMeasure = 1\n"
                "\tcolumn OldColumn\n"
            )
        },
    )
    _write_model(
        candidate,
        model_tmdl="model Candidate\n",
        tables={},
    )

    results = compare.compare_models(baseline, candidate)
    table_changes = _changes_for_level(results, "table")
    measure_changes = _changes_for_level(results, "measure")
    column_changes = _changes_for_level(results, "column")

    assert len(table_changes) == 1
    assert table_changes[0]["changeType"] == "removed"
    assert measure_changes == []
    assert column_changes == []


def test_compare_rename_behavior_is_add_plus_remove(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"

    _write_model(
        baseline,
        model_tmdl="model Baseline\n",
        tables={
            "Sales.tmdl": (
                "table Sales\n"
                "\tcolumn OldName\n"
            )
        },
    )
    _write_model(
        candidate,
        model_tmdl="model Candidate\n",
        tables={
            "Sales.tmdl": (
                "table Sales\n"
                "\tcolumn NewName\n"
            )
        },
    )

    results = compare.compare_models(baseline, candidate)
    column_changes = _changes_for_level(results, "column")

    assert len(column_changes) == 2
    change_types = sorted([c["changeType"] for c in column_changes])
    assert change_types == ["added", "removed"]


def test_compare_ignores_comment_only_expression_changes(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"

    _write_model(
        baseline,
        model_tmdl="model Baseline\n",
        tables={
            "Sales.tmdl": "table Sales\n\tmeasure Revenue = SUM(Sales[Amount])\n",
        },
    )
    _write_model(
        candidate,
        model_tmdl="model Candidate\n",
        tables={
            "Sales.tmdl": (
                "table Sales\n"
                "\tmeasure Revenue = // comment\n"
                "\t\t\tSUM(Sales[Amount])\n"
            ),
        },
    )

    results = compare.compare_models(baseline, candidate)
    assert _changes_for_level(results, "measure") == []


def test_compare_export_helpers(tmp_path):
    baseline = tmp_path / "Baseline.SemanticModel"
    candidate = tmp_path / "Candidate.SemanticModel"

    _write_model(
        baseline,
        model_tmdl="model Baseline\n",
        tables={"Sales.tmdl": "table Sales\n"},
    )
    _write_model(
        candidate,
        model_tmdl="model Candidate\n\tcompatibilityLevel: 1602\n",
        tables={"Sales.tmdl": "table Sales\n"},
    )

    results = compare.compare_models(baseline, candidate)
    json_payload = compare.format_compare_json_output(results)
    xlsx_payload = compare.create_compare_xlsx_bytes(results)

    assert '"summary"' in json_payload
    assert xlsx_payload.startswith(b"PK")
