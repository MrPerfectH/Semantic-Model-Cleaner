import json
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer


def _write_workspace(tmp_path: Path) -> Path:
    """Workspace with one stale selector, one stale formatting rule, one stale
    bookmark projection, and one error-severity missing measure."""
    workspace = tmp_path / "Workspace"
    model = workspace / "Models" / "Sales.SemanticModel"
    report = workspace / "Reports" / "Executive.Report"
    tables_dir = model / "definition" / "tables"
    page_dir = report / "definition" / "pages" / "Page1"
    visual_dir = page_dir / "visuals" / "Visual1"
    bookmarks_dir = report / "definition" / "bookmarks"
    tables_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    bookmarks_dir.mkdir(parents=True)

    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tcolumn Amount\n"
        "\tcolumn Region\n"
        "\tmeasure 'Revenue Total' = SUM(Sales[Amount])\n"
        "\tmeasure 'Revenue LY' = SUM(Sales[Amount])\n",
        encoding="utf-8",
    )
    (page_dir / "page.json").write_text(
        json.dumps({"displayName": "Overview"}, indent=2), encoding="utf-8"
    )
    (visual_dir / "visual.json").write_text(
        json.dumps(
            {
                "name": "Visual1",
                "visual": {
                    "visualType": "tableEx",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Measure": {
                                                "Property": "Revenue Total",
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                            }
                                        },
                                        "queryRef": "Sales.Revenue Total",
                                    },
                                    {
                                        "field": {
                                            "Measure": {
                                                "Property": "Revenue Totl",
                                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                            }
                                        },
                                        "queryRef": "Sales.Revenue Totl",
                                    },
                                ],
                                "fieldParameters": [
                                    {
                                        "parameterExpr": {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Entity": "FP_Metric"}},
                                                "Property": "FP_Metric",
                                            }
                                        }
                                    }
                                ],
                            }
                        }
                    },
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
                                                                        "Expression": {"SourceRef": {"Entity": "Legacy Sales"}},
                                                                        "Property": "Old Color Driver",
                                                                    }
                                                                },
                                                                "Function": 0,
                                                            }
                                                        },
                                                        "FillRule": {
                                                            "linearGradient2": {
                                                                "min": {"color": {"Literal": {"Value": "'#c1272d'"}}},
                                                                "max": {"color": {"Literal": {"Value": "'#7faf23'"}}},
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                                "selector": {
                                    "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                    "metadata": "Sum(Legacy Sales.Old Color Driver)",
                                },
                            }
                        ],
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
                                                            "Property": "Old Format Selector",
                                                            "Expression": {"SourceRef": {"Entity": "Legacy Sales"}},
                                                        }
                                                    },
                                                    "Right": {"Literal": {"Value": "'Old'"}},
                                                }
                                            }
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (bookmarks_dir / "bookmark1.bookmark.json").write_text(
        json.dumps(
            {
                "displayName": "Last Year",
                "name": "bookmark1",
                "options": {"applyOnlyToTargetVisuals": True, "targetVisualNames": ["Visual1"]},
                "explorationState": {
                    "activeSection": "Page1",
                    "sections": {
                        "Page1": {
                            "visualContainers": {
                                "Visual1": {
                                    "singleVisual": {
                                        "visualType": "tableEx",
                                        "projections": {
                                            "Values": [
                                                {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                        "Property": "Revenue LY",
                                                    }
                                                }
                                            ]
                                        },
                                        "parameters": {
                                            "Values": [
                                                {
                                                    "expr": {
                                                        "Column": {
                                                            "Expression": {"SourceRef": {"Entity": "FP_Metric"}},
                                                            "Property": "FP_Metric",
                                                        }
                                                    }
                                                }
                                            ]
                                        },
                                    }
                                }
                            }
                        }
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return workspace


def _snapshot(workspace: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(workspace)): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def _run_cli(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as excinfo:
        analyzer.main(argv)
    return int(excinfo.value.code or 0)


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _error_issue_count(results: dict) -> int:
    return sum(1 for issue in results["report_issues"] if issue["severity"] == "error")


def test_workspace_fixture_has_all_three_stale_kinds(tmp_path):
    workspace = _write_workspace(tmp_path)

    results = analyzer.analyze(workspace.resolve())

    kinds = {analyzer.stale_cleanup_kind(issue) for issue in analyzer.eligible_stale_issues(results)}
    assert kinds == {"selector", "bookmark", "formatting"}
    assert _error_issue_count(results) >= 1


def test_build_stale_cleanup_entries_matches_ui_entry_shape(tmp_path):
    workspace = _write_workspace(tmp_path)
    results = analyzer.analyze(workspace.resolve())
    reports = analyzer.discover_reports([workspace.resolve()])

    entries = analyzer.build_stale_cleanup_entries(results, reports)

    assert entries
    for entry in entries:
        assert set(entry) == {
            "report_path",
            "artifact_path",
            "selector_value",
            "source_path",
            "stale_kind",
        }
        assert entry["report_path"] == str(reports[0])
        assert entry["stale_kind"] in (
            "",
            "visual_formatting_selector_entry",
            "bookmark_projection_entry",
            "formatting_rule_reference",
        )


def test_error_severity_issues_are_never_cleanup_candidates(tmp_path):
    workspace = _write_workspace(tmp_path)
    results = analyzer.analyze(workspace.resolve())

    for issue in results["report_issues"]:
        if issue["severity"] == "error" or issue["issueType"] == "inactive_visual_filter_reference":
            assert analyzer.stale_cleanup_kind(issue) is None


def test_dry_run_lists_candidates_and_leaves_files_untouched(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)
    before = _snapshot(workspace)

    exit_code = _run_cli(["clean-stale", str(workspace), "--format", "json"])
    payload = _json_output(capsys)

    assert exit_code == 2
    assert payload["dry_run"] is True
    assert payload["applied"] is False
    assert payload["candidate_count"] == len(payload["candidates"]) > 0
    assert sum(payload["counts_by_kind"].values()) == payload["candidate_count"]
    assert payload["counts_by_report"] == {"Executive": payload["candidate_count"]}
    assert payload["removed_count"] == 0
    assert _snapshot(workspace) == before


def test_dry_run_text_output_lists_candidate_details(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)

    exit_code = _run_cli(["clean-stale", str(workspace)])
    out = capsys.readouterr().out

    assert exit_code == 2
    assert "Stale cleanup candidates:" in out
    assert "[formatting] Executive" in out
    assert "Dry run: nothing was written" in out


def test_kind_filter_limits_candidates(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)

    _run_cli(["clean-stale", str(workspace), "--kind", "formatting", "--format", "json"])
    payload = _json_output(capsys)

    assert payload["kinds"] == ["formatting"]
    assert payload["candidate_count"] > 0
    assert {candidate["kind"] for candidate in payload["candidates"]} == {"formatting"}
    assert payload["counts_by_kind"]["selector"] == 0
    assert payload["counts_by_kind"]["bookmark"] == 0


def test_apply_removes_stale_issues_and_keeps_error_issues(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)
    before = analyzer.analyze(workspace.resolve())
    errors_before = _error_issue_count(before)

    exit_code = _run_cli(["clean-stale", str(workspace), "--apply", "--no-backup", "--format", "json"])
    payload = _json_output(capsys)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["removed_count"] > 0
    assert payload["updated_files"]
    assert payload["backup_paths"] == []

    after = analyzer.analyze(workspace.resolve())
    assert analyzer.eligible_stale_issues(after) == []
    assert _error_issue_count(after) == errors_before

    second_exit = _run_cli(["clean-stale", str(workspace), "--format", "json"])
    assert second_exit == 0
    assert _json_output(capsys)["candidate_count"] == 0


def test_apply_creates_a_backup_per_report_by_default(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)
    report = workspace / "Reports" / "Executive.Report"
    before = _snapshot(report)

    exit_code = _run_cli(["clean-stale", str(workspace), "--apply", "--format", "json"])
    payload = _json_output(capsys)

    assert exit_code == 0
    assert len(payload["backup_paths"]) == 1
    backup = Path(payload["backup_paths"][0])
    assert backup.is_dir()
    assert _snapshot(backup) == before


def test_apply_with_no_candidates_exits_zero(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)
    _run_cli(["clean-stale", str(workspace), "--apply", "--no-backup", "--format", "json"])
    capsys.readouterr()

    exit_code = _run_cli(["clean-stale", str(workspace), "--apply", "--no-backup", "--format", "json"])
    payload = _json_output(capsys)

    assert exit_code == 0
    assert payload["candidate_count"] == 0
    assert payload["removed_count"] == 0


def test_no_subcommand_invocation_still_works(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)

    analyzer.main([str(workspace), "--format", "unused"])
    out = capsys.readouterr().out

    assert "Semantic Model" in out or "Unused" in out


def test_no_subcommand_json_invocation_still_works(tmp_path, capsys):
    workspace = _write_workspace(tmp_path)

    analyzer.main([str(workspace), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert "items" in payload
    assert "reportIssues" in payload
