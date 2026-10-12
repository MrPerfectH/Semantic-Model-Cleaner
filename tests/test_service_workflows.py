import json
from pathlib import Path
import subprocess
import sys

import pytest

from semantic_model_cleaner.service_provider import (
    Target,
    ServiceProvider,
    ProbeError,
    public_summary,
)

FIXTURE = Path(__file__).parent / "fixtures/service_probe/supported.json"
T, W, M, R, OTHER = [f"00000000-0000-0000-0000-{i:012}" for i in range(1, 6)]


def transcript():
    return json.loads(FIXTURE.read_text())


def provider(tmp_path, data=None, scope=(W,)):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps(data or transcript()))
    return ServiceProvider(Target(T, W, M, scope), fixture=path)


def test_discover_exact_target_and_public_redaction(tmp_path):
    result = provider(tmp_path).discover()
    assert result["status"] == "complete_within_selected_scope"
    assert result["reports"][0]["report_id"] == R
    assert result["target"]["model_id"] == M
    assert result["known_connected_report_count"] == 1
    assert result["unknown_downstream_report_count"] is None
    assert result["global_completeness"] is False
    assert result["evidence_kind"] == "fixture"
    assert result["live_acceptance"] == "unverified"
    public = json.dumps(public_summary(result))
    for value in (T, W, M, R, "Synthetic"):
        assert value not in public


def test_empty_and_denied_scope_not_conflated(tmp_path):
    data = transcript()
    data["responses"][1]["body"]["value"] = []
    result = provider(tmp_path, data).discover()
    assert result["workspaces"][0]["status"] == "empty"
    assert result["selected_scope_complete"] is True
    data["responses"][1]["status"] = 403
    result = provider(tmp_path, data).discover()
    assert result["workspaces"][0]["status"] == "denied"
    assert result["selected_scope_complete"] is False
    assert result["unknown_downstream_report_count"] is None


def test_cross_workspace_and_deduplication(tmp_path):
    data = transcript()
    row = data["responses"][1]["body"]["value"][0]
    data["responses"][1]["body"]["value"].append(dict(row))
    data["responses"].insert(
        2,
        {
            "method": "GET",
            "url": f"https://api.powerbi.com/v1.0/myorg/groups/{OTHER}/reports",
            "body": {"value": [dict(row, id=OTHER)]},
        },
    )
    result = provider(tmp_path, data, (W, OTHER, W)).discover()
    assert len(result["workspaces"]) == 2
    assert len(result["reports"]) == 2


def test_wrong_target_and_missing_scope_rejected_before_network(tmp_path):
    with pytest.raises(ProbeError):
        Target(T, W, "PROD", (W,))
    with pytest.raises(ProbeError):
        Target(T, W, M, ())
    p = provider(tmp_path)
    p.target = Target(OTHER, W, M, (W,))
    result = p.discover()
    assert result["errors"][0]["code"] == "selected_tenant_mismatch"
    assert result["requests"] == []


def cli_args(action="discover"):
    return [
        "service",
        action,
        "--tenant-id",
        T,
        "--workspace-id",
        W,
        "--model-id",
        M,
        "--report-workspace-id",
        W,
        "--fixture",
        str(FIXTURE),
    ]


def test_real_cli_dispatch_preserves_versioned_discovery():
    completed = subprocess.run(
        [sys.executable, "-m", "semantic_model_cleaner", *cli_args()],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "service-validation/1"
    assert result["target"]["tenant_id"] == T


def test_audit_real_analyzer_isolated_snapshot_and_no_cleanup(tmp_path):
    from semantic_model_cleaner.service_analysis import audit

    result = audit(provider(tmp_path))
    assert result["command"] == "service audit"
    assert result["selected_scope_complete"] is True
    assert result["coverage"]["complete"] is False
    assert result["report_health"]["findings"] == []
    assert result["reports"][0]["status"] == "analyzed"
    assert result["model_definition"]["format"] == "TMDL"
    assert result["reports"][0]["definition"]["format"] == "PBIR"
    assert result["snapshot"]["cached"] is False
    spare = next(row for row in result["analysis"]["items"] if row["name"] == "Spare")
    assert spare["status"] == "No Use Found In Scope"
    assert spare["removalRisk"] == "Review"
    assert "_snapshot_path" not in result["reports"][0]
    assert "/tmp/smc-service-snapshot-" not in json.dumps(result)
    assert result["cleanup_available"] is False


def replace_part(data, path, text):
    import base64

    for part in data["definition"]["parts"]:
        if part["path"] == path:
            part["payload"] = base64.b64encode(text.encode()).decode()
            return
    raise AssertionError(path)


def test_audit_broken_reference_has_report_location_and_findings_exit(tmp_path):
    from semantic_model_cleaner.service_analysis import audit
    from semantic_model_cleaner.service_provider import result_exit

    data = transcript()
    replace_part(
        data["responses"][2]["body"],
        "definition/tables/Sales.tmdl",
        "table Sales\n\tmeasure Spare = 1\n",
    )
    result = audit(provider(tmp_path, data))
    assert result_exit(result) == 1
    findings = result["report_health"]["findings"]
    assert findings[0]["report_id"] == R
    assert findings[0]["visualId"] == "v1"
    assert findings[0]["name"] == "Revenue"
    assert findings[0]["page"]


def test_partial_access_stays_incomplete_not_pass(tmp_path):
    from semantic_model_cleaner.service_analysis import audit
    from semantic_model_cleaner.service_provider import result_exit

    data = transcript()
    data["responses"][-1].update(status=403, body={})
    result = audit(provider(tmp_path, data))
    assert result_exit(result) == 2
    assert result["report_health"]["checked"] is False
    assert result["reports"][0]["status"] == "inaccessible"
    assert result["analysis_limitations"]


def test_snapshot_cleanup_even_when_cancelled(tmp_path):
    from semantic_model_cleaner.service_analysis import snapshot
    from semantic_model_cleaner.analysis_jobs import AnalysisCancelled

    with pytest.raises(AnalysisCancelled):
        with snapshot(provider(tmp_path)) as state:
            root = state.root
            assert root.exists()
            raise AnalysisCancelled()
    assert not root.exists()


def test_audit_command_executes_real_analyzer():
    completed = subprocess.run(
        [sys.executable, "-m", "semantic_model_cleaner", *cli_args("audit")],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["analysis"]["summary"]["total_usage_refs"] == 1


def candidate_dir(tmp_path, table="table Sales\n\tmeasure Revenue = 1\n\tmeasure Spare = 2\n"):
    model = tmp_path / "Candidate.SemanticModel"
    (model / "definition/tables").mkdir(parents=True)
    (model / "definition/model.tmdl").write_text("model Model\n")
    (model / "definition/tables/Sales.tmdl").write_text(table)
    return model


@pytest.mark.parametrize(
    "table,introduced",
    [
        ("table Sales\n\tmeasure Revenue = 2\n\tmeasure Spare = 2\n", 0),
        ("table Sales\n\tmeasure Revenue = 1\n\tmeasure Added = 3\n", 0),
        ("table Sales\n\tmeasure Renamed = 1\n", 1),
        ("table Different\n\tmeasure Revenue = 1\n", 1),
    ],
)
def test_candidate_measure_expression_addition_rename_and_table_removal(
    tmp_path, table, introduced
):
    from semantic_model_cleaner.service_analysis import validate_candidate, tree_digest
    from semantic_model_cleaner.service_provider import result_exit

    model = candidate_dir(tmp_path, table)
    before = tree_digest(model)
    result = validate_candidate(provider(tmp_path), model)
    assert result["comparison"]["same_report_snapshot"] is True
    assert len(result["comparison"]["introduced"]) == introduced
    assert result_exit(result) == (1 if introduced else 0)
    assert result["candidate"]["unchanged_after_run"] is True
    assert tree_digest(model) == before
    assert result["candidate"]["source_kind"] == "local_candidate"
    assert result["model_definition"]["model_id"] == M
    assert result["comparison"]["static_reference_check_only"] is True
    assert result["validation_limits"]


def test_candidate_existing_problem_separate_from_introduced(tmp_path):
    from semantic_model_cleaner.service_analysis import validate_candidate

    data = transcript()
    replace_part(
        data["responses"][2]["body"],
        "definition/tables/Sales.tmdl",
        "table Sales\n\tmeasure Spare = 2\n",
    )
    model = candidate_dir(tmp_path, "table Sales\n\tmeasure Spare = 3\n")
    result = validate_candidate(provider(tmp_path, data), model)
    assert len(result["comparison"]["pre_existing"]) == 1
    assert result["comparison"]["introduced"] == []


def test_candidate_column_removal_against_same_reports(tmp_path):
    import base64
    from semantic_model_cleaner.service_analysis import validate_candidate

    data = transcript()
    replace_part(
        data["responses"][2]["body"],
        "definition/tables/Sales.tmdl",
        "table Sales\n\tcolumn Revenue\n\t\tdataType: int64\n",
    )
    parts = data["responses"][-1]["body"]["definition"]["parts"]
    visual = next(part for part in parts if part["path"].endswith("visual.json"))
    content = base64.b64decode(visual["payload"]).decode().replace('"Measure"', '"Column"')
    visual["payload"] = base64.b64encode(content.encode()).decode()
    result = validate_candidate(
        provider(tmp_path, data),
        candidate_dir(tmp_path, "table Sales\n\tcolumn Different\n\t\tdataType: int64\n"),
    )
    assert len(result["comparison"]["introduced"]) == 1
    assert result["comparison"]["introduced"][0]["refType"] == "Column"


def test_candidate_cli_and_target_validation(tmp_path):
    model = candidate_dir(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "semantic_model_cleaner",
            *cli_args("validate"),
            "--candidate",
            str(model),
        ],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["comparison"]["introduced"] == []
    assert result["candidate"]["sha256"]
