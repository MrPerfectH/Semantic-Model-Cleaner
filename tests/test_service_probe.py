"""Synthetic capability/denial cases; none of these establish live tenant access."""

import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from semantic_model_cleaner import service_probe as probe
from semantic_model_cleaner import service_provider as provider

FIXTURE = Path(__file__).parent / "fixtures/service_probe/supported.json"
TENANT = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-000000000002"
MODEL = "00000000-0000-0000-0000-000000000003"
REPORT = "00000000-0000-0000-0000-000000000004"
OTHER = "00000000-0000-0000-0000-000000000005"
OPERATION = "00000000-0000-0000-0000-000000000006"
MODELS_URL = f"{probe.FABRIC}/workspaces/{WORKSPACE}/semanticModels"
OP_URL = f"{probe.FABRIC}/operations/{OPERATION}"


def fixture():
    data = json.loads(FIXTURE.read_text())
    # Unit fixtures below address definitions by index; preflight is inserted by client_for.
    data["responses"].pop(2)
    return data


def client_for(rows):
    expanded, seen = [], set()
    for row in rows:
        if row["method"] == "POST" and "/getDefinition" in row["url"]:
            workspace_url = row["url"].split("/semanticModels/")[0].split("/reports/")[0]
            if workspace_url not in seen:
                expanded.append({"method": "GET", "url": workspace_url, "status": 403})
                seen.add(workspace_url)
        expanded.append(row)
    rows = expanded
    evidence = probe.Evidence("fixture")
    sleeps = []
    client = probe.Client(
        probe.FixtureTransport({"responses": rows}), evidence, sleep=sleeps.append
    )
    return client, evidence, sleeps


def run_fixture(data=None, extra_workspaces=()):
    client, evidence, _ = client_for((data or fixture())["responses"])
    probe.probe(client, evidence, WORKSPACE, MODEL, extra_workspaces, tenant=TENANT)
    return evidence.data


def replace_part(body, name, content):
    for part in body["definition"]["parts"]:
        if part["path"] == name:
            part["payload"] = base64.b64encode(content.encode()).decode()
            return
    raise AssertionError(name)


def test_supported_definitions_feed_actual_existing_analysis_and_stay_bounded():
    result = run_fixture()
    assert result["status"] == "bounded_probe_completed"
    assert result["analysis"]["report_reference_count"] == 1
    assert result["analysis"]["no_use_found_in_scope_count"] == 1
    assert result["analysis"]["model_item_count"] == 2
    assert result["analysis"]["recommendation_for_no_use_found"] == "Review"
    assert result["analysis"]["cleanup_actions_available"] is False
    assert result["global_completeness"] is False
    assert result["live_acceptance"] == "unverified"
    assert result["report_health"] == {"checked": True, "issue_count": 0}
    assert result["analysis_limitations"][0]["code"] == "bounded_discovery_not_global"
    serialized = json.dumps(result)
    for secret in [
        TENANT,
        WORKSPACE,
        MODEL,
        REPORT,
        "Synthetic model",
        "Revenue",
        "Sales",
        "Bearer",
    ]:
        assert secret not in serialized


def test_inspect_pagination_and_same_name_models_preserve_exact_ids():
    rows = [
        {
            "method": "GET",
            "url": MODELS_URL,
            "body": {
                "value": [{"id": MODEL, "displayName": "Same"}],
                "continuationToken": "opaque+token",
            },
        },
        {
            "method": "GET",
            "url": MODELS_URL + "?continuationToken=opaque%2Btoken",
            "body": {"value": [{"id": OTHER, "displayName": "Same"}]},
        },
    ]
    client, evidence, _ = client_for(rows)
    assert {r["id"] for r in probe.inspect_models(client, WORKSPACE, evidence)} == {MODEL, OTHER}


@pytest.mark.parametrize(
    "next_link",
    [
        MODELS_URL,
        "http://api.fabric.microsoft.com/v1/x",
        "https://attacker.invalid/leak",
        f"{probe.FABRIC}/workspaces/{OTHER}/semanticModels",
        MODELS_URL + "#fragment",
    ],
)
def test_rejects_pagination_cycles_or_scope_escapes(next_link):
    client, _, _ = client_for(
        [{"method": "GET", "url": MODELS_URL, "body": {"value": [], "continuationUri": next_link}}]
    )
    with pytest.raises(probe.ProbeError, match="invalid_pagination"):
        list(client.items(MODELS_URL, "list_models", "workspace-1"))


def test_odata_report_pagination_keeps_direct_consumers_from_second_page():
    data = fixture()
    original = data["responses"][1]
    first = deepcopy(original)
    first["body"] = {"value": [], "@odata.nextLink": original["url"] + "?$skip=1"}
    original["url"] += "?$skip=1"
    data["responses"].insert(1, first)
    assert run_fixture(data)["reports"][0]["status"] == "analyzed"


def test_cross_workspace_discovery_and_inaccessible_workspace_are_distinct():
    data = fixture()
    remote = deepcopy(data["responses"][1])
    remote["url"] = f"{probe.POWERBI}/groups/{OTHER}/reports"
    data["responses"][1]["body"]["value"] = []
    data["responses"].insert(2, remote)
    data["responses"][-1]["url"] = (
        f"{probe.FABRIC}/workspaces/{OTHER}/reports/{REPORT}/getDefinition"
    )
    assert run_fixture(data, [OTHER])["reports"][0]["workspace"] == "workspace-2"
    denied = fixture()
    denied["responses"].insert(
        2, {"method": "GET", "url": remote["url"], "status": 403, "body": {"message": "SECRET"}}
    )
    result = run_fixture(denied, [OTHER])
    assert result["status"] == "incomplete"
    assert result["workspaces"][1]["reason"] == "access_denied"
    assert result["reports"][0]["status"] == "analyzed"
    assert result["report_health"]["issue_count"] == 0
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "authentication_rejected"),
        (403, "access_denied"),
        (404, "not_found_or_inaccessible"),
        (400, "api_request_failed"),
    ],
)
def test_definition_denial_not_confused_with_report_health(status, reason):
    data = fixture()
    data["responses"][-1].update(status=status, body={"message": "SECRET tenant and token"})
    result = run_fixture(data)
    assert result["status"] == "incomplete"
    assert result["reports"][0]["reason"] == reason
    assert result["analysis"]["reports_scanned"] == 0
    assert result["report_health"] == {"checked": False, "issue_count": 0}
    assert reason in {r["code"] for r in result["analysis_limitations"]}
    assert "SECRET" not in json.dumps(result)


def test_unsupported_possible_encryption_is_not_claimed_as_verified_encryption():
    data = fixture()
    data["responses"][-1].update(
        status=400, body={"errorCode": "OperationNotSupportedForItem", "message": "SECRET"}
    )
    result = run_fixture(data)
    assert result["reports"][0]["reason"] == "definition_not_supported_possible_encryption"
    assert result["permission_observations"]["encrypted_items"] == "unverified"


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"datasetId": None}, "direct_model_identity_missing"),
        ({"reportType": "PaginatedReport"}, "unsupported_or_unknown_report_type"),
        ({"datasetWorkspaceId": OTHER}, "model_workspace_conflict"),
        ({"reportType": None}, "unsupported_or_unknown_report_type"),
        ({"datasetId": OTHER}, "different_direct_model"),
    ],
)
def test_unknown_indirect_and_unsupported_reports_never_become_analyzed(changes, expected):
    data = fixture()
    data["responses"][1]["body"]["value"][0].update(changes)
    data["responses"].pop()
    result = run_fixture(data)
    assert result["reports"][0]["reason"] == expected
    assert result["reports"][0]["status"] != "analyzed"
    assert result["status"] == "incomplete"


def test_no_name_based_model_selection():
    data = fixture()
    data["responses"][0]["body"]["value"][0]["id"] = OTHER
    with pytest.raises(probe.ProbeError, match="selected_model_not_visible"):
        run_fixture(data)


@pytest.mark.parametrize("state", ["Failed", "Cancelled", "Unexpected"])
def test_lro_failure_or_unknown_state(state):
    first = fixture()["responses"][2]
    first.update(status=202, headers={"Location": OP_URL}, body={})
    client, _, _ = client_for([first, {"method": "GET", "url": OP_URL, "body": {"status": state}}])
    with pytest.raises(
        probe.ProbeError, match="definition_operation_failed|unknown_operation_state"
    ):
        client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")


def test_lro_and_rate_limit_honor_retry_after_and_fetch_result():
    definition = fixture()["responses"][2]
    first = deepcopy(definition)
    first.update(status=202, headers={"x-ms-operation-id": OPERATION, "Retry-After": "2"}, body={})
    rows = [
        first,
        {"method": "GET", "url": OP_URL, "status": 429, "headers": {"Retry-After": "3"}},
        {
            "method": "GET",
            "url": OP_URL,
            "headers": {"Retry-After": "4"},
            "body": {"status": "Running"},
        },
        {
            "method": "GET",
            "url": OP_URL,
            "headers": {"Location": OP_URL + "/result"},
            "body": {"status": "Succeeded"},
        },
        {"method": "GET", "url": OP_URL + "/result", "body": definition["body"]},
    ]
    client, evidence, sleeps = client_for(rows)
    assert client.definition(WORKSPACE, "semanticModels", MODEL, "model-1") == definition["body"]
    assert sum(sleeps) == 9
    assert len(evidence.data["requests"]) == 6


def test_lro_location_escape_and_excessive_retry_fail_without_second_request():
    first = fixture()["responses"][2]
    first.update(status=202, headers={"Location": "https://attacker.invalid/token"}, body={})
    client, _, _ = client_for([first])
    with pytest.raises(probe.ProbeError, match="invalid_operation_location"):
        client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")
    first["headers"] = {"Location": OP_URL, "Retry-After": "3600"}
    client, _, _ = client_for([first])
    with pytest.raises(probe.ProbeError, match="retry_budget_exceeded"):
        client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")


@pytest.mark.parametrize(
    "method,url",
    [
        ("DELETE", MODELS_URL),
        ("PATCH", MODELS_URL),
        ("POST", f"{probe.FABRIC}/workspaces/{WORKSPACE}/reports/{REPORT}/updateDefinition"),
        ("POST", f"{probe.POWERBI}/groups/{WORKSPACE}/reports/{REPORT}/Rebind"),
        ("GET", "https://attacker.invalid"),
        ("GET", "http://api.fabric.microsoft.com/v1/operations/" + OPERATION),
    ],
)
def test_cloud_mutations_and_untrusted_hosts_cannot_reach_transport(method, url):
    client, evidence, _ = client_for([])
    with pytest.raises(probe.ProbeError, match="request_outside_read_allowlist"):
        client.request(method, url, "forbidden", "test")
    assert evidence.data["requests"] == []


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/absolute",
        "definition/../escape",
        "definition\\escape",
        "./relative",
        "definition//double",
        "null\x00byte",
    ],
)
def test_definition_paths_cannot_escape_private_temporary_root(path, tmp_path):
    body = fixture()["responses"][2]["body"]
    body["definition"]["parts"][0]["path"] = path
    with pytest.raises(probe.ProbeError, match="unsafe_definition_path"):
        probe.unpack_definition(body, tmp_path / "model", "model")
    assert list(tmp_path.iterdir()) == []


def test_definition_duplicate_and_prefix_collision(tmp_path):
    body = fixture()["responses"][2]["body"]
    duplicate = deepcopy(body["definition"]["parts"][0])
    duplicate["path"] = duplicate["path"].upper()
    body["definition"]["parts"].append(duplicate)
    with pytest.raises(probe.ProbeError, match="unsafe_definition_path"):
        probe.unpack_definition(body, tmp_path / "model", "model")
    duplicate["path"] = "definition"
    with pytest.raises(probe.ProbeError, match="unsafe_definition_path"):
        probe.unpack_definition(body, tmp_path / "model", "model")


@pytest.mark.parametrize(
    "kind,changes,reason",
    [
        ("model", {"format": "TMSL"}, "unsupported_model_format"),
        ("report", {"format": "PBIR-Legacy"}, "unsupported_or_incomplete_report"),
    ],
)
def test_unknown_definition_format_is_explicit(kind, changes, reason, tmp_path):
    body = fixture()["responses"][2 if kind == "model" else 3]["body"]
    body["definition"].update(changes)
    with pytest.raises(probe.ProbeError, match=reason):
        probe.unpack_definition(body, tmp_path, kind)


def test_legacy_definition_not_fed_to_analyzer():
    data = fixture()
    body = data["responses"][-1]["body"]
    body["definition"]["parts"][1]["path"] = "report.json"
    result = run_fixture(data)
    assert result["reports"][0]["reason"] == "unsupported_legacy_report"
    assert result["analysis"]["reports_scanned"] == 0


@pytest.mark.parametrize(
    "binding,reason",
    [
        ({"byPath": {"path": "../SameName.SemanticModel"}}, "report_binding_unverified"),
        (
            {"byConnection": {"connectionString": "Initial Catalog=SameName"}},
            "report_binding_unverified",
        ),
        (
            {"byConnection": {"connectionString": f"semanticmodelid={OTHER}"}},
            "report_binding_changed_or_conflicting",
        ),
        (
            {
                "byConnection": {
                    "connectionString": f"semanticmodelid={MODEL}",
                    "pbiModelDatabaseName": OTHER,
                }
            },
            "report_binding_changed_or_conflicting",
        ),
    ],
)
def test_report_rebound_or_unverifiable_between_inventory_and_retrieval(binding, reason):
    data = fixture()
    replace_part(
        data["responses"][-1]["body"], "definition.pbir", json.dumps({"datasetReference": binding})
    )
    result = run_fixture(data)
    assert result["reports"][0]["reason"] == reason
    assert result["analysis"]["reports_scanned"] == 0


def test_actual_parser_gap_is_separate_from_report_health():
    data = fixture()
    replace_part(
        data["responses"][-1]["body"],
        "definition/pages/Page1/visuals/v1/visual.json",
        "INVALID JSON SECRET",
    )
    result = run_fixture(data)
    assert result["status"] == "incomplete"
    assert result["report_health"]["issue_count"] > 0
    assert result["analysis"]["analysis_limitation_count"] > 0
    assert "existing_parser_analysis_limitations" in {
        r["code"] for r in result["analysis_limitations"]
    }
    assert "SECRET" not in json.dumps(result)


def jwt(service="fabric", **overrides):
    claims = {
        "tid": TENANT,
        "oid": OTHER,
        "exp": time.time() + 3600,
        "aud": probe.RESOURCES[service],
        "scp": "Report.ReadWrite.All SECRET",
    }
    claims.update(overrides)
    return (
        "header."
        + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        + ".signature"
    )


def test_credentials_use_same_tenant_and_subject_without_leaking_scopes(monkeypatch):
    monkeypatch.setenv("SMC_FABRIC_TOKEN", jwt())
    monkeypatch.setenv("SMC_POWERBI_TOKEN", jwt("powerbi"))
    _, observations = probe.authenticate()
    assert observations["fabric"][2] == ["Report.ReadWrite.All"]
    monkeypatch.setenv("SMC_POWERBI_TOKEN", jwt("powerbi", oid=MODEL))
    with pytest.raises(probe.ProbeError, match="credential_identity_mismatch"):
        probe.authenticate()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"exp": 0}, "token_expired"),
        ({"aud": "https://attacker.invalid"}, "token_audience_mismatch"),
    ],
)
def test_invalid_token_claims_fail_before_request(changes, reason):
    with pytest.raises(probe.ProbeError, match=reason):
        probe.token_claims(jwt(**changes), "fabric")


def cli_args(tmp_path, action="run"):
    args = [
        action,
        "--workspace-id",
        WORKSPACE,
        "--evidence",
        str(tmp_path / "evidence.json"),
        "--private-output",
        str(tmp_path / "private"),
    ]
    if action == "run":
        args += ["--tenant-id", TENANT, "--model-id", MODEL]
    return args


def test_actual_executable_fixture_smoke_and_private_output(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "semantic_model_cleaner.service_probe",
            *cli_args(tmp_path),
            "--fixture",
            str(FIXTURE),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fixture; live acceptance unverified" in result.stdout
    public = (tmp_path / "evidence.json").read_text()
    assert MODEL not in public
    private = json.loads((tmp_path / "private/identities.json").read_text())
    assert private["model_candidates"][0]["id"] == MODEL
    if os.name != "nt":
        assert (tmp_path / "private").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "private/identities.json").stat().st_mode & 0o777 == 0o600


def test_auth_unavailable_produces_precise_sanitized_blocker(tmp_path, monkeypatch):
    monkeypatch.delenv("SMC_FABRIC_TOKEN", raising=False)
    monkeypatch.delenv("SMC_POWERBI_TOKEN", raising=False)
    monkeypatch.setattr(probe.shutil, "which", lambda _: None)
    assert probe.main(cli_args(tmp_path, "inspect")) == 2
    result = json.loads((tmp_path / "evidence.json").read_text())
    assert result["requests"] == []
    assert result["analysis_limitations"][0]["code"] == "linux_sign_in_required"
    assert result["status"] == "incomplete"


def test_selected_tenant_mismatch_sends_no_requests(tmp_path):
    args = cli_args(tmp_path)
    args[args.index("--tenant-id") + 1] = OTHER
    assert probe.main(args + ["--fixture", str(FIXTURE)]) == 2
    result = json.loads((tmp_path / "evidence.json").read_text())
    assert result["requests"] == []
    assert result["analysis_limitations"][0]["code"] == "selected_tenant_mismatch"


def test_existing_output_not_overwritten(tmp_path):
    target = tmp_path / "evidence.json"
    target.write_text("retain concurrent output")
    with pytest.raises(SystemExit):
        probe.main(cli_args(tmp_path) + ["--fixture", str(FIXTURE)])
    assert target.read_text() == "retain concurrent output"


def test_missing_advertised_page_cannot_look_like_complete_empty_report():
    data = fixture()
    replace_part(
        data["responses"][-1]["body"], "definition/pages/pages.json", '{"pageOrder":["Missing"]}'
    )
    result = run_fixture(data)
    assert result["reports"][0]["reason"] == "incomplete_report_pages"
    assert result["selected_scope_complete"] is False
    assert result["analysis"]["reports_scanned"] == 0


@pytest.mark.parametrize("payload", ["{", '{"pageOrder":"Not a list"}', '{"pageOrder":[42]}'])
def test_malformed_page_inventory_is_explicit(payload):
    data = fixture()
    replace_part(data["responses"][-1]["body"], "definition/pages/pages.json", payload)
    result = run_fixture(data)
    assert result["reports"][0]["reason"] in {
        "incomplete_report_pages",
        "invalid_report_page_inventory",
    }
    assert result["selected_scope_complete"] is False


def test_payload_size_and_encoding_limits(tmp_path, monkeypatch):
    body = fixture()["responses"][2]["body"]
    monkeypatch.setattr(provider, "MAX_BYTES", 1)
    with pytest.raises(probe.ProbeError, match="definition_size_limit"):
        probe.unpack_definition(body, tmp_path, "model")
    monkeypatch.setattr(provider, "MAX_BYTES", 10000)
    body["definition"]["parts"][0]["payload"] = "not base64!"
    with pytest.raises(probe.ProbeError, match="invalid_definition_payload"):
        probe.unpack_definition(body, tmp_path, "model")
    body["definition"]["parts"][0]["payloadType"] = "ExternalUri"
    with pytest.raises(probe.ProbeError, match="unsupported_payload_type"):
        probe.unpack_definition(body, tmp_path, "model")
    assert list(tmp_path.iterdir()) == []


def test_live_transport_handles_http_denial_without_exposing_body(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError

    transport = probe.LiveTransport({"fabric": "SECRET TOKEN", "powerbi": "SECOND SECRET"})

    def denied(request, timeout):
        assert request.get_header("Authorization") == "Bearer SECRET TOKEN"
        assert timeout == 30
        raise HTTPError(
            request.full_url, 403, "SECRET MESSAGE", {}, BytesIO(b'{"message":"SECRET BODY"}')
        )

    monkeypatch.setattr(transport.opener, "open", denied)
    evidence = probe.Evidence("fixture")
    client = probe.Client(transport, evidence)
    with pytest.raises(probe.ProbeError, match="access_denied"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert "SECRET" not in json.dumps(evidence.data)


def test_http_redirect_handler_will_not_forward_authorization():
    assert (
        probe.NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid")
        is None
    )


def test_collection_limit_and_request_deadline_are_explicit(monkeypatch):
    monkeypatch.setattr(provider, "MAX_PAGES", 1)
    client, _, _ = client_for(
        [{"method": "GET", "url": MODELS_URL, "body": {"value": [], "continuationToken": "more"}}]
    )
    with pytest.raises(probe.ProbeError, match="pagination_limit"):
        list(client.items(MODELS_URL, "list_models", "workspace-1"))
    client.deadline = 0
    with pytest.raises(probe.ProbeError, match="request_budget_exceeded"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")


def test_failed_network_attempt_is_preserved_in_request_evidence():
    def unavailable(method, url):
        raise probe.ProbeError("network_unavailable")

    evidence = probe.Evidence("fixture")
    client = probe.Client(unavailable, evidence)
    with pytest.raises(probe.ProbeError, match="network_unavailable"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert evidence.data["requests"][0]["status"] is None
    assert evidence.data["requests"][0]["failure"] == "network_unavailable"
    assert "finished_at" in evidence.data["requests"][0]


@pytest.mark.parametrize("state,status,expected_exit", [("Inactive", 200, 2), (None, 403, 0)])
def test_actual_executable_capacity_preflight_contract(tmp_path, state, status, expected_exit):
    data = json.loads(FIXTURE.read_text())
    capacity = "abcdef12-abcd-4abc-8abc-abcdef123456"
    data["responses"][2] = {
        "method": "GET",
        "url": f"{probe.FABRIC}/workspaces/{WORKSPACE}",
        "body": {"id": WORKSPACE, "capacityId": capacity},
    }
    data["responses"].insert(3, {
        "method": "GET",
        "url": f"{probe.FABRIC}/capacities",
        "status": status,
        "body": {"value": [{"id": capacity.upper(), "state": state}], "message": "SECRET"},
    })
    path = tmp_path / "capacity-fixture.json"
    path.write_text(json.dumps(data))
    completed = subprocess.run(
        [sys.executable, "-m", "semantic_model_cleaner.service_probe",
         *cli_args(tmp_path), "--fixture", str(path)],
        text=True, capture_output=True, timeout=30,
    )
    assert completed.returncode == expected_exit, completed.stdout + completed.stderr
    public = (tmp_path / "evidence.json").read_text()
    result = json.loads(public)
    assert "SECRET" not in public
    assert all(value not in public for value in (TENANT, WORKSPACE, MODEL, REPORT, capacity))
    observation = next(row["capacity_preflight"] for row in result["requests"] if row.get("capacity_preflight"))
    assert observation == {"capacityState": state or "Unknown", "capacityObservation": "preflight"}
    if state == "Inactive":
        assert result["status"] == "incomplete"
        assert result["failure_diagnostics"] == observation
        assert any(row["code"] == "capacity_inactive" and "administrator" in row["hint"] for row in result["analysis_limitations"])
        assert all(row["method"] == "GET" for row in result["requests"])
    else:
        assert result["status"] == "bounded_probe_completed"
        assert sum(row["method"] == "POST" for row in result["requests"]) == 2
