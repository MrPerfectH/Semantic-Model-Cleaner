"""Real transport preflight and redaction; no credentials or service access."""
import json
import subprocess

import pytest

from semantic_model_cleaner import service_provider as p
from test_service_transport import client_for as transport_client, WORKSPACE, MODEL, OP_URL

CAPACITY = "abcdef12-abcd-4abc-8abc-abcdef123456"
REQUEST = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
WORKSPACE_URL = f"{p.FABRIC}/workspaces/{WORKSPACE}"
CAPACITIES_URL = p.FABRIC + "/capacities"
DEFINITION = {"definition": {"parts": []}}


def response(body, status=200, headers=None):
    return status, headers or {}, json.dumps(body).encode()


def client_for(monkeypatch, responses):
    client, evidence, requests, sleeps = transport_client(monkeypatch, responses)
    # Restore the real preflight for these integration tests.
    monkeypatch.setattr(client, "capacity_preflight", p.Client.capacity_preflight.__get__(client))
    return client, evidence, requests, sleeps


def workspace(**extra):
    return response({"id": WORKSPACE, "capacityId": CAPACITY, **extra})


def capacities(state, **extra):
    return response({"value": [{"id": CAPACITY.upper(), "state": state}], **extra})


def retrieve(client):
    return client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")


@pytest.mark.parametrize("kind", ["semanticModels", "reports"])
def test_inactive_stops_before_any_export(monkeypatch, kind):
    client, evidence, requests, sleeps = client_for(monkeypatch, [workspace(), capacities("Inactive")])
    with pytest.raises(p.ProbeError, match="^capacity_inactive$") as error:
        client.definition(WORKSPACE, kind, MODEL, "selected")
    assert error.value.diagnostics == {"capacityState": "Inactive", "capacityObservation": "preflight"}
    assert [r.full_url for r in requests] == [WORKSPACE_URL, CAPACITIES_URL]
    assert all(r.get_method() == "GET" for r in requests)
    assert not sleeps
    assert CAPACITY not in json.dumps(evidence.data)


@pytest.mark.parametrize("state", ["Active", "Unknown", None, [], {}, "Suspended", "inactive"])
def test_active_or_unknown_retrieves_and_reuses_only_this_run(monkeypatch, state):
    client, evidence, requests, _ = client_for(monkeypatch, [workspace(), capacities(state), response(DEFINITION), response(DEFINITION)])
    assert retrieve(client) == DEFINITION
    assert retrieve(client) == DEFINITION
    assert len(requests) == 4
    assert client.capacity_observations[WORKSPACE] == ("Active" if state == "Active" else "Unknown")
    assert evidence.data["requests"][1]["capacity_preflight"]["capacityObservation"] == "preflight"


@pytest.mark.parametrize("status", [403, 404, 401, 429, 500])
@pytest.mark.parametrize("stage", ["workspace", "capacity"])
def test_invisible_capacity_is_optional_without_retries(monkeypatch, status, stage):
    rows = ([workspace()] if stage == "capacity" else []) + [response({"message": "SECRET"}, status), response(DEFINITION)]
    client, evidence, requests, sleeps = client_for(monkeypatch, rows)
    assert retrieve(client) == DEFINITION
    assert requests[-1].get_method() == "POST"
    assert len(requests) == len(rows)
    assert sleeps == []
    assert client.capacity_observations[WORKSPACE] == "Unknown"
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize("body", [{}, {"id": MODEL, "capacityId": CAPACITY}, {"id": WORKSPACE, "capacityId": "invalid"}, {"id": WORKSPACE, "capacityId": []}])
def test_workspace_must_confirm_exact_identity(monkeypatch, body):
    client, _, requests, _ = client_for(monkeypatch, [response(body), response(DEFINITION)])
    assert retrieve(client) == DEFINITION
    assert len(requests) == 2


def test_paginated_exact_match_and_conflict(monkeypatch):
    for last, expected in [("Inactive", "Inactive"), ("Active", "Unknown")]:
        rows = [workspace(), capacities("Inactive", continuationToken="page+two"), capacities(last)]
        if expected == "Unknown":
            rows.append(response(DEFINITION))
        client, _, requests, _ = client_for(monkeypatch, rows)
        if expected == "Inactive":
            with pytest.raises(p.ProbeError, match="capacity_inactive"):
                retrieve(client)
        else:
            assert retrieve(client) == DEFINITION
        assert requests[2].full_url == CAPACITIES_URL + "?continuationToken=page%2Btwo"
        assert client.capacity_observations[WORKSPACE] == expected


@pytest.mark.parametrize("next_url", [
    "https://attacker.invalid/SECRET", CAPACITIES_URL + "/../workspaces", CAPACITIES_URL + "#SECRET",
    CAPACITIES_URL.replace(".com/", ".com:443/"), CAPACITIES_URL.replace("api.fabric", "user@api.fabric"),
    CAPACITIES_URL + "?other=secret", CAPACITIES_URL + "?continuationToken=a&continuationToken=b",
    CAPACITIES_URL + "\n", CAPACITIES_URL, [],
])
def test_unsafe_pagination_discards_even_inactive_match(monkeypatch, next_url):
    client, _, requests, _ = client_for(monkeypatch, [workspace(), capacities("Inactive", continuationUri=next_url), response(DEFINITION)])
    assert retrieve(client) == DEFINITION
    assert len(requests) == 3
    assert requests[-1].get_method() == "POST"
    assert client.capacity_observations[WORKSPACE] == "Unknown"


def test_capacity_pages_are_finite_and_absence_is_unknown(monkeypatch):
    rows = [workspace()] + [capacities("Inactive", continuationToken=str(i)) for i in range(p.CAPACITY_MAX_PAGES)] + [response(DEFINITION)]
    client, _, requests, _ = client_for(monkeypatch, rows)
    assert retrieve(client) == DEFINITION
    assert len(requests) == 7
    client, _, requests, _ = client_for(monkeypatch, [workspace(), response({"value": [{"id": MODEL, "state": "Inactive"}]}), response(DEFINITION)])
    assert retrieve(client) == DEFINITION


@pytest.mark.parametrize("error", [
    {"errorCode": "UnknownError", "isRetriable": False, "requestId": REQUEST, "message": "SECRET", "workspaceId": WORKSPACE},
    {"errorCode": "SECRET" * 1000, "isRetriable": "false", "requestId": "SECRET"},
    {"errorCode": [], "isRetriable": 1, "RequestId": REQUEST.upper()},
    None, [], "SECRET",
])
def test_terminal_error_details_survive_public_projection_without_prose(monkeypatch, error):
    client, evidence, requests, _ = client_for(monkeypatch, [workspace(), capacities("Active"), response({}, 202, {"x-ms-operation-id": OP_URL.rsplit('/', 1)[1]}), response({"status": "Failed", "error": error}, headers={"RequestId": REQUEST})])
    with pytest.raises(p.ProbeError, match="^definition_operation_failed$") as raised:
        retrieve(client)
    details = raised.value.diagnostics
    assert details["capacityState"] == "Active"
    assert details["capacityObservation"] == "preflight"
    assert details["responseRequestId"] == REQUEST
    if isinstance(error, dict) and error.get("isRetriable") is False:
        assert details["isRetriable"] is False
        assert details["errorCode"] == "UnknownError"
        assert details["requestId"] == REQUEST
    else:
        assert "isRetriable" not in details
    result = p.new_result("audit", p.Target(MODEL, WORKSPACE, MODEL, (WORKSPACE,)), "fixture")
    result["requests"] = evidence.data["requests"]
    result["requests"].append({"failure": "definition_operation_failed", "diagnostics": {"errorCode": "SECRET", "isRetriable": [], "requestId": WORKSPACE + "/SECRET", "capacityState": {}}})
    public = p.public_summary(result)
    assert public["operation_diagnostics"][0] == details
    assert public["operation_diagnostics"][1] == {"errorCode": "Other"}
    serialized = json.dumps(public)
    for forbidden in ("SECRET", WORKSPACE, MODEL, CAPACITY, "https://", "message"):
        assert forbidden not in serialized
    assert len(requests) == 4  # No after-failure retry or state probe.


@pytest.mark.parametrize("value", [None, [], {}, 1, True, "not-a-uuid", REQUEST + "\n", "{" + REQUEST + "}"])
def test_invalid_request_id_types_are_omitted(value):
    assert p.safe_diagnostics({"requestId": value, "responseRequestId": value}) == {}


@pytest.mark.parametrize("aadsts,expected", [("70043", "sign_in_expired"), ("700082", "sign_in_expired"), ("50076", "sign_in_interaction_required"), ("700430", "linux_sign_in_required"), ("1234", "linux_sign_in_required")])
def test_cli_failure_is_actionable_and_never_echoes_stderr(monkeypatch, capsys, aadsts, expected):
    monkeypatch.delenv("SMC_FABRIC_TOKEN", raising=False)
    monkeypatch.delenv("SMC_POWERBI_TOKEN", raising=False)
    monkeypatch.setattr(p.shutil, "which", lambda _: "/safe/az")
    def fail(*args, **kwargs):
        assert kwargs["capture_output"] is True
        raise subprocess.CalledProcessError(1, ["SECRET"], stderr=f"AADSTS{aadsts}: SECRET account tenant config path")
    monkeypatch.setattr(p.subprocess, "run", fail)
    with pytest.raises(p.ProbeError, match=f"^{expected}$") as raised:
        p.authenticate()
    assert raised.value.__suppress_context__
    assert "SECRET" not in p.error_hint(expected)
    assert capsys.readouterr() == ("", "")
    if aadsts == "50076":
        assert "expired" not in p.error_hint(expected).lower()


def test_legacy_hint_does_not_promise_conversion():
    hint = p.error_hint("unsupported_legacy_report")
    assert "PBIR-Legacy" in hint and "not guaranteed" in hint
    assert "incomplete" in hint
