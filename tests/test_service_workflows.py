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
    assert public_summary(result)["capacity_observations"] == [
        {"capacityState": "Unknown", "capacityObservation": "preflight"}
    ]


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
        data["responses"][3]["body"],
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
        data["responses"][3]["body"],
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
        data["responses"][3]["body"],
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


def repository_fixture(tmp_path, count=4):
    import base64
    import copy
    import os

    repo = tmp_path / "Repo"
    repo.mkdir()
    model = candidate_dir(repo)
    data = transcript()
    template = data["responses"][-1]
    inventory = []
    definitions = []
    mappings = []
    for index in range(count):
        report_id = f"00000000-0000-0000-0000-{index + 4:012}"
        inventory.append(
            {
                "id": report_id,
                "datasetId": M,
                "reportType": "PowerBIReport",
                "name": "Same display name",
            }
        )
        definition = copy.deepcopy(template)
        definition["url"] = definition["url"].replace(R, report_id)
        definitions.append(definition)
        if index < 2:
            local = repo / "Reports" / f"R{index}.Report"
            local.mkdir(parents=True)
            for part in definition["body"]["definition"]["parts"]:
                path = local / part["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(part["payload"]))
            (local / "definition.pbir").write_text(
                json.dumps(
                    {"datasetReference": {"byPath": {"path": os.path.relpath(model, local)}}}
                )
            )
            mappings.append(
                {
                    "local_report": str(local.relative_to(repo)),
                    "workspace_id": W,
                    "report_id": report_id,
                }
            )
    data["responses"][1]["body"]["value"] = inventory
    data["responses"] = data["responses"][:4] + definitions
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target": {"tenant_id": T, "workspace_id": W, "model_id": M},
                "reports": mappings,
            }
        )
    )
    return repo, model, mapping, data


def test_two_repository_reports_plus_two_additional_and_definition_equality(tmp_path):
    from semantic_model_cleaner.service_analysis import audit

    repo, model, mapping, data = repository_fixture(tmp_path)
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    comparison = result["repository_comparison"]
    assert len(comparison["matched"]) == 2
    assert len(comparison["additional_published"]) == 2
    assert comparison["unresolved"] == []
    assert comparison["matched"][0]["definition_comparison"]["status"] == "equal_content_bytes"
    assert comparison["matched"][0]["identity_evidence"] == "explicit_target_bound_mapping"
    (repo / "Reports/R0.Report/definition/report.json").write_text('{"changed": true}')
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    assert (
        result["repository_comparison"]["matched"][0]["definition_comparison"]["status"]
        == "different_content_bytes"
    )


def test_same_names_without_mapping_and_dev_prod_mapping_are_not_identity(tmp_path):
    from semantic_model_cleaner.service_analysis import audit

    repo, model, mapping, data = repository_fixture(tmp_path)
    result = audit(provider(tmp_path, data), repository=repo, local_model=model)
    assert result["repository_comparison"]["matched"] == []
    assert len(result["repository_comparison"]["unresolved"]) == 2
    assert result["selected_scope_complete"] is False
    content = json.loads(mapping.read_text())
    content["target"]["model_id"] = OTHER
    mapping.write_text(json.dumps(content))
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    assert "repository_comparison" not in result
    assert any(
        g["code"] == "repository_mapping_target_mismatch" for g in result["analysis_limitations"]
    )


def test_local_only_is_only_a_scoped_identity_observation(tmp_path):
    from semantic_model_cleaner.service_analysis import audit

    repo, model, mapping, data = repository_fixture(tmp_path)
    content = json.loads(mapping.read_text())
    content["reports"][0]["report_id"] = "00000000-0000-0000-0000-000000000099"
    mapping.write_text(json.dumps(content))
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    row = result["repository_comparison"]["local_only"][0]
    assert row["reason"] == "mapped_identity_not_observed_connected_in_scope"
    assert "globally unpublished" in result["repository_comparison"]["limitations"][0]


def test_duplicate_or_escaping_mappings_are_not_accepted(tmp_path):
    from semantic_model_cleaner.service_analysis import audit

    repo, model, mapping, data = repository_fixture(tmp_path)
    content = json.loads(mapping.read_text())
    content["reports"].append(content["reports"][0])
    mapping.write_text(json.dumps(content))
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    assert any(g["code"] == "repository_mapping_ambiguous" for g in result["analysis_limitations"])
    content["reports"] = [dict(content["reports"][0], local_report="../elsewhere.Report")]
    mapping.write_text(json.dumps(content))
    result = audit(provider(tmp_path, data), repository=repo, local_model=model, mapping=mapping)
    assert any(
        g["code"] == "repository_mapping_path_invalid" for g in result["analysis_limitations"]
    )


def test_candidate_and_baseline_share_coherent_service_limitations(tmp_path):
    from semantic_model_cleaner.service_analysis import validate_candidate

    data = transcript()
    data["responses"][-1].update(status=403, body={})
    result = validate_candidate(provider(tmp_path, data), candidate_dir(tmp_path))
    shared = {g["id"] for g in result["analysis_limitations"] if g["scope"] == "shared"}
    for key in ("analysis", "candidate_analysis"):
        analysis = result[key]
        assert analysis["coverage"]["complete"] is False
        assert analysis["analysisLimitationSummary"]["distinct_count"] == len(
            result["analysis_limitations"]
        )
        for item in analysis["items"]:
            if item["status"] == "No Use Found In Scope":
                assert shared <= set(item["analysisLimitationIds"])
                assert item["removalRisk"] != "Safe"


def test_snapshot_alias_paths_preserve_service_identity_and_durable_locations(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    from semantic_model_cleaner import service_analysis

    original = service_analysis.tempfile.TemporaryDirectory

    @contextmanager
    def aliased_temporary_directory(**kwargs):
        with original(**kwargs) as directory:
            # Analyzer paths resolve aliases (also Windows short/long TEMP paths).
            # An unresolved parent hop reproduces that identity mismatch on Linux.
            alias = Path(directory) / "alias"
            alias.mkdir()
            yield str(alias / "..")

    monkeypatch.setattr(
        service_analysis.tempfile, "TemporaryDirectory", aliased_temporary_directory
    )
    data = transcript()
    replace_part(
        data["responses"][3]["body"],
        "definition/tables/Sales.tmdl",
        "table Sales\n\tmeasure Spare = 1\n",
    )
    result = service_analysis.audit(provider(tmp_path, data))
    finding = result["report_health"]["findings"][0]
    assert finding["report_id"] == R
    assert finding["workspace_id"] == W
    assert finding["reportPath"].startswith("snapshot://" + result["snapshot"]["id"] + "/")
    assert "\\" not in finding["reportPath"]
    assert "smc-service-snapshot-" not in json.dumps(result)
