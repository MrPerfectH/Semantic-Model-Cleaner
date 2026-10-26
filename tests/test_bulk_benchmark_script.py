"""The published bulk fixture must succeed and prove actual byte-exact recovery."""
import json

import pytest

from semantic_model_cleaner import analyzer
from test_scale_scripts import script


SIZES = {"deletions": 6, "tables": 2, "columns": 4, "measures": 3,
         "reports": 2, "pages_per_report": 1, "visuals": 4}


def test_synthetic_bulk_benchmark_records_successful_recovery_and_phase_timings(tmp_path):
    module = script("benchmark_bulk_plan")
    result = module.benchmark(tmp_path / "benchmark", profile=True, **SIZES)
    assert result["ok"] and result["proof"] == {"planning_read_only": True, "apply_verified": True,
        "removed_items": 6, "restored_byte_exact": True}
    assert result["fixture"] == {"items": 14, "delete_actions": 6, "operations": 1,
        "tables": 2, "reports": 2, "pages": 2, "visuals": 4}
    assert result["validation"]["existing_problem_count"] == result["validation"]["remaining_problem_count"] == 0
    assert result["validation"]["pbir_schema"]["before"]["invalid"] == 0
    assert result["validation"]["pbir_schema"]["before"]["valid"] == 6
    assert result["phases_inclusive"]["schema_validation"]["calls"] == 2
    assert result["phases_inclusive"]["plan_analysis"]["calls"] == 2
    assert result["planning_reads"]["text"] > 0 and result["planning_reads"]["bytes"] > 0
    assert (tmp_path / "benchmark/planning.pstats").is_file()
    # A fresh generated copy must produce exactly the same reviewed bytes and validation.
    second = module.benchmark(tmp_path / "again", **SIZES)
    assert second["equivalence"] == result["equivalence"]


def test_bulk_generator_creates_the_requested_successful_787_case(tmp_path):
    module = script("benchmark_bulk_plan")
    root, model, reports, operations, counts = module.generate_fixture(tmp_path / "fixture", visuals=160)
    assert len(analyzer.parse_model_items(model)) == 1960
    assert counts["delete_actions"] == 787 and counts["reports"] == 8 and counts["pages"] == 160
    assert len(operations[0]["actions"]) == 787
    assert all(analyzer.report_binding_status(report, model)["status"] == "connected" for report in reports)
    assert len(list(root.rglob("visual.json"))) == 160


@pytest.mark.parametrize("change", [{"deletions": 999999}, {"visuals": 0}, {"tables": -1},
                                     {"visuals": 1}, {"measures": True}])
def test_bulk_generator_rejects_invalid_sizes_before_writes(tmp_path, change):
    module = script("benchmark_bulk_plan")
    target = tmp_path / "invalid"
    with pytest.raises(ValueError):
        module.generate_fixture(target, **{**SIZES, **change})
    assert not target.exists()


def test_bulk_benchmark_refuses_existing_output(tmp_path, capsys):
    module = script("benchmark_bulk_plan")
    sentinel = tmp_path / "untouched.json"
    sentinel.write_text("original", encoding="utf-8")
    assert module.main([str(tmp_path)]) == 2
    assert not json.loads(capsys.readouterr().out)["ok"]
    assert sentinel.read_text(encoding="utf-8") == "original"
