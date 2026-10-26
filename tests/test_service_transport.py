"""Exercise urllib response parsing without credentials or live service calls."""

from http.client import IncompleteRead
from io import BytesIO
import json
from urllib.error import HTTPError
from urllib.response import addinfourl

import pytest

from semantic_model_cleaner import service_provider as provider

WORKSPACE = "00000000-0000-0000-0000-000000000002"
MODEL = "00000000-0000-0000-0000-000000000003"
OPERATION = "00000000-0000-0000-0000-000000000006"
MODELS_URL = f"{provider.FABRIC}/workspaces/{WORKSPACE}/semanticModels"
OP_URL = f"{provider.FABRIC}/operations/{OPERATION}"


def client_for(monkeypatch, responses):
    """Feed raw bytes through the real LiveTransport, including HTTPError."""
    transport = provider.LiveTransport({"fabric": "SECRET TOKEN", "powerbi": "SECRET POWERBI TOKEN"})
    pending = iter(responses)
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        status, headers, payload = next(pending)
        assert timeout == 30
        if status >= 300:
            raise HTTPError(request.full_url, status, "SECRET MESSAGE", headers, BytesIO(payload))
        return addinfourl(BytesIO(payload), headers, request.full_url, status)

    monkeypatch.setattr(transport.opener, "open", open_response)
    evidence = provider.Evidence("fixture")
    sleeps = []
    client = provider.Client(transport, evidence, sleep=sleeps.append)
    # These tests isolate LRO transport. Capacity uses the real transport in test_service_capacity.
    monkeypatch.setattr(client, "capacity_preflight", lambda workspace: "Unknown")
    return client, evidence, requests, sleeps


@pytest.mark.parametrize("payload", [b"", b"null", b"[]", b"invalid JSON", b'"SECRET BODY"'])
@pytest.mark.parametrize(
    "location",
    [
        OP_URL + "/result",
        OP_URL.replace("/v1/", "/") + "/result",
        "https://attacker.invalid/SECRET",
        provider.FABRIC + "/operations/00000000-0000-0000-0000-000000000099/result",
    ],
)
def test_lro_ignores_acceptance_body_and_uses_only_canonical_result(monkeypatch, payload, location):
    definition = {"definition": {"parts": []}}
    client, evidence, requests, sleeps = client_for(
        monkeypatch,
        [
            (202, {"Location": OP_URL, "Retry-After": "1"}, payload),
            (200, {"Location": location}, b'{"status":"Succeeded"}'),
            (200, {}, json.dumps(definition).encode()),
        ],
    )
    assert client.definition(WORKSPACE, "semanticModels", MODEL, "model-1") == definition
    assert [r.full_url for r in requests] == [
        f"{provider.FABRIC}/workspaces/{WORKSPACE}/semanticModels/{MODEL}/getDefinition?format=TMDL",
        OP_URL,
        OP_URL + "/result",
    ]
    assert requests[0].get_header("Content-type") == "application/json"
    assert [r["status"] for r in evidence.data["requests"]] == [202, 200, 200]
    assert sleeps == [1]
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_rejected"),
        (403, "access_denied"),
        (404, "not_found_or_inaccessible"),
    ],
)
@pytest.mark.parametrize("payload", [b'"SECRET BODY"', b"null", b"[]", b"invalid JSON"])
def test_error_body_does_not_mask_http_status(monkeypatch, status, code, payload):
    client, evidence, requests, _ = client_for(monkeypatch, [(status, {}, payload)])
    with pytest.raises(provider.ProbeError, match=f"^{code}$"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert len(requests) == 1
    assert evidence.data["requests"][0]["status"] == status
    assert evidence.data["requests"][0]["failure"] == code
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize(
    "payload,kind,code",
    [
        (b"null", "null", "invalid_response_shape"),
        (b"[]", "array", "invalid_response_shape"),
        (b'"SECRET BODY"', "string", "invalid_response_shape"),
        (b"42", "number", "invalid_response_shape"),
        (b"true", "boolean", "invalid_response_shape"),
        (b"SECRET invalid JSON", "invalid_json", "invalid_response_json"),
        (b"\xff", "invalid_json", "invalid_response_json"),
    ],
)
def test_malformed_success_preserves_safe_diagnostics(monkeypatch, payload, kind, code):
    client, evidence, _, _ = client_for(monkeypatch, [(200, {}, payload)])
    with pytest.raises(provider.ProbeError, match=f"^{code}$") as error:
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert error.value.status == 200
    assert error.value.body_kind == kind
    receipt = json.loads(json.dumps(evidence.data))["requests"][0]
    assert receipt["status"] == 200
    assert receipt["body_kind"] == kind
    assert receipt["failure"] == code
    assert set(receipt) == {
        "method",
        "operation",
        "owner",
        "status",
        "at",
        "finished_at",
        "body_kind",
        "failure",
    }
    assert "SECRET" not in json.dumps(evidence.data)


def test_rate_limit_non_object_body_retries_are_bounded(monkeypatch):
    client, evidence, requests, sleeps = client_for(
        monkeypatch, [(429, {"Retry-After": "1"}, b"null")] * 4
    )
    with pytest.raises(provider.ProbeError, match="^rate_limited$"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert len(requests) == 4
    assert sleeps == [1, 1, 1]
    assert [r["status"] for r in evidence.data["requests"]] == [429] * 4


def test_error_object_retains_fixed_safe_mapping(monkeypatch):
    client, evidence, _, _ = client_for(
        monkeypatch,
        [
            (400, {}, b'{"errorCode":"OperationNotSupportedForItem","message":"SECRET BODY"}'),
        ],
    )
    with pytest.raises(provider.ProbeError, match="^definition_not_supported_possible_encryption$"):
        client.request(
            "POST",
            f"{provider.FABRIC}/workspaces/{WORKSPACE}/semanticModels/{MODEL}/getDefinition",
            "get_definition",
            "model-1",
        )
    assert evidence.data["requests"][0]["status"] == 400
    assert "SECRET" not in json.dumps(evidence.data)


# Use alphabetic digits so canonicalization is observable, unlike the numeric fixture ID.
LRO_ID = "abcdef12-abcd-4abc-8abc-abcdef123456"
LRO_URL = f"{provider.FABRIC}/operations/{LRO_ID}"
REGIONAL_URL = f"https://wabi-west-europe-redirect.analysis.windows.net/v1/operations/{LRO_ID}"
GET_DEFINITION_URL = (
    f"{provider.FABRIC}/workspaces/{WORKSPACE}/semanticModels/{MODEL}/getDefinition?format=TMDL"
)


def assert_fabric_requests(requests, urls):
    assert [request.full_url for request in requests] == urls
    assert [request.get_method() for request in requests] == ["POST"] + ["GET"] * (len(urls) - 1)
    assert all(request.get_header("Authorization") == "Bearer SECRET TOKEN" for request in requests)


@pytest.mark.parametrize(
    "headers",
    [
        {"Location": REGIONAL_URL, "x-ms-operation-id": LRO_ID},
        {"x-ms-operation-id": LRO_ID},
        {"x-ms-operation-id": LRO_ID.upper()},
        {"Location": LRO_URL, "x-ms-operation-id": LRO_ID},
        {"Location": OP_URL, "x-ms-operation-id": LRO_ID},
        {"Location": "https://attacker.invalid/SECRET", "x-ms-operation-id": LRO_ID},
        {"Location": LRO_URL},
        {"Location": f"{provider.FABRIC}/operations/{LRO_ID.upper()}"},
    ],
    ids=["regional", "id-only", "uppercase-id", "matching", "conflicting", "hostile",
         "location-only", "uppercase-location-id"],
)
def test_initial_lro_identity_uses_canonical_fabric_requests(monkeypatch, headers):
    definition = {"definition": {"parts": []}}
    client, evidence, requests, sleeps = client_for(
        monkeypatch,
        [
            (202, {**headers, "Retry-After": "20"}, b"null"),
            (200, {"Location": "https://attacker.invalid/SECRET"}, b'{"status":"Succeeded"}'),
            (200, {}, json.dumps(definition).encode()),
        ],
    )
    assert client.definition(WORKSPACE, "semanticModels", MODEL, "model-1") == definition
    assert_fabric_requests(requests, [GET_DEFINITION_URL, LRO_URL, LRO_URL + "/result"])
    assert sleeps == [1] * 20
    assert [receipt["status"] for receipt in evidence.data["requests"]] == [202, 200, 200]
    assert "SECRET" not in json.dumps(evidence.data)
    assert "wabi" not in json.dumps(evidence.data)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Location": ""},
        {"Location": "https://attacker.invalid/SECRET"},
        {"Location": REGIONAL_URL},
        {"Location": OP_URL + "/result"},
        {"Location": OP_URL + "?SECRET"},
        {"Location": OP_URL + "#SECRET"},
        {"Location": OP_URL.replace("api.fabric", "SECRET@api.fabric")},
        {"Location": OP_URL.replace(".com/", ".com:443/")},
        {"Location": OP_URL.replace("/operations/", "/SECRET/../operations/")},
        {"Location": OP_URL.replace("/v1/", "/")},
        {"Location": "/v1/operations/" + OPERATION},
        {"Location": OP_URL + "\r\nSECRET: injected"},
        {"Location": provider.FABRIC + "/operations/" + "-" * 36},
        {"Location": OP_URL, "x-ms-operation-id": ""},
        {"Location": OP_URL, "x-ms-operation-id": "../../workspaces/SECRET"},
        {"Location": OP_URL, "x-ms-operation-id": "00000000-0000-0000-0000-00000000000G"},
        {"x-ms-operation-id": "../../workspaces/SECRET"},
    ],
)
def test_untrusted_initial_operation_identity_is_rejected(monkeypatch, headers):
    client, evidence, requests, sleeps = client_for(monkeypatch, [(202, headers, b"null")])
    with pytest.raises(provider.ProbeError, match="^invalid_operation_location$"):
        client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")
    assert_fabric_requests(requests, [GET_DEFINITION_URL])
    assert sleeps == []
    assert "SECRET" not in json.dumps(evidence.data)


def test_redirect_response_fails_without_following_location(monkeypatch):
    client, evidence, requests, _ = client_for(
        monkeypatch,
        [
            (302, {"Location": "https://attacker.invalid/SECRET"}, b"{}"),
        ],
    )
    with pytest.raises(provider.ProbeError, match="^api_request_failed$"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert len(requests) == 1
    assert evidence.data["requests"][0]["status"] == 302
    assert (
        provider.NoRedirect().redirect_request(
            requests[0], None, 302, "", {}, "https://attacker.invalid"
        )
        is None
    )


def test_response_size_limit_still_applies_to_202(monkeypatch):
    monkeypatch.setattr(provider, "MAX_BYTES", 2)
    client, evidence, _, _ = client_for(monkeypatch, [(202, {}, b"oversized")])
    with pytest.raises(provider.ProbeError, match="^response_size_limit$"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert evidence.data["requests"][0]["status"] == 202


def test_public_summary_keeps_only_allowlisted_response_diagnostics(monkeypatch):
    client, evidence, _, _ = client_for(monkeypatch, [(200, {}, b"null")])
    with pytest.raises(provider.ProbeError):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    result = provider.new_result(
        "analyze",
        provider.Target("00000000-0000-0000-0000-000000000001", WORKSPACE, MODEL, (WORKSPACE,)),
        "fixture",
    )
    result["requests"] = evidence.data["requests"] + [
        {"status": 200, "body_kind": "SECRET BODY", "url": "SECRET URL"},
    ]
    summary = provider.public_summary(result)
    assert summary["response_diagnostics"] == [{"status": 200, "body_kind": "null"}]
    assert "SECRET" not in json.dumps(summary)


def test_body_read_failure_preserves_known_status_without_message(monkeypatch):
    class BrokenBody(BytesIO):
        def read(self, size=-1):
            raise OSError("SECRET BODY READ FAILURE")

    transport = provider.LiveTransport({"fabric": "SECRET TOKEN"})
    monkeypatch.setattr(
        transport.opener,
        "open",
        lambda request, timeout: addinfourl(BrokenBody(), {}, request.full_url, 200),
    )
    evidence = provider.Evidence("fixture")
    client = provider.Client(transport, evidence)
    with pytest.raises(provider.ProbeError, match="^network_unavailable$"):
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert evidence.data["requests"][0]["status"] == 200
    assert evidence.data["requests"][0]["failure"] == "network_unavailable"
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize("initial_payload", [b"null", b"[]", b"invalid JSON"])
@pytest.mark.parametrize("state", ["Running", "NotStarted"])
def test_lro_preserves_202_polling_object(monkeypatch, initial_payload, state):
    definition = {"definition": {"parts": []}}
    client, evidence, requests, sleeps = client_for(
        monkeypatch,
        [
            (202, {"Location": REGIONAL_URL, "x-ms-operation-id": OPERATION, "Retry-After": "1"}, initial_payload),
            (202, {"Retry-After": "1"}, json.dumps({"status": state}).encode()),
            (200, {}, b'{"status":"Succeeded"}'),
            (200, {}, json.dumps(definition).encode()),
        ],
    )
    assert client.definition(WORKSPACE, "semanticModels", MODEL, "model-1") == definition
    assert_fabric_requests(requests, [GET_DEFINITION_URL, OP_URL, OP_URL, OP_URL + "/result"])
    assert [receipt["status"] for receipt in evidence.data["requests"]] == [202, 202, 200, 200]
    assert sleeps == [1, 1]
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize("status", [200, 202, 403])
def test_incomplete_read_preserves_known_status_without_partial_body(monkeypatch, status):
    class IncompleteBody(BytesIO):
        def read(self, size=-1):
            assert size == provider.MAX_BYTES + 1
            raise IncompleteRead(b"SECRET PARTIAL BODY", 123)

    transport = provider.LiveTransport({"fabric": "SECRET TOKEN"})
    monkeypatch.setattr(
        transport.opener,
        "open",
        lambda request, timeout: addinfourl(IncompleteBody(), {}, request.full_url, status),
    )
    evidence = provider.Evidence("fixture")
    client = provider.Client(transport, evidence)
    with pytest.raises(provider.ProbeError, match="^network_unavailable$") as error:
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert error.value.status == status
    assert error.value.body_kind is None
    assert error.value.__suppress_context__
    assert len(evidence.data["requests"]) == 1
    assert evidence.data["requests"][0]["status"] == status
    assert evidence.data["requests"][0]["failure"] == "network_unavailable"
    assert "SECRET" not in json.dumps(evidence.data)


@pytest.mark.parametrize("status", [200, 202, 403])
def test_deeply_nested_json_fails_closed_with_known_status(monkeypatch, status):
    payload = b'{"SECRET":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}"
    client, evidence, requests, sleeps = client_for(monkeypatch, [(status, {}, payload)])
    with pytest.raises(provider.ProbeError, match="^invalid_response_json$") as error:
        client.request("GET", MODELS_URL, "list_models", "workspace-1")
    assert error.value.status == status
    assert error.value.body_kind == "invalid_json"
    assert error.value.__suppress_context__
    assert len(requests) == 1
    assert sleeps == []
    receipt = evidence.data["requests"][0]
    assert receipt["status"] == status
    assert receipt["body_kind"] == "invalid_json"
    assert receipt["failure"] == "invalid_response_json"
    result = provider.new_result(
        "analyze",
        provider.Target("00000000-0000-0000-0000-000000000001", WORKSPACE, MODEL, (WORKSPACE,)),
        "fixture",
    )
    result["requests"] = evidence.data["requests"]
    summary = provider.public_summary(result)
    assert summary["response_diagnostics"] == [{"status": status, "body_kind": "invalid_json"}]
    assert "SECRET" not in json.dumps(evidence.data)
    assert "SECRET" not in json.dumps(summary)


def test_canonical_poll_failed_operation_stays_failed(monkeypatch):
    client, evidence, requests, sleeps = client_for(
        monkeypatch,
        [
            (202, {"Location": REGIONAL_URL, "x-ms-operation-id": LRO_ID}, b"null"),
            (200, {}, b'{"status":"Failed","error":{"errorCode":"UnknownError"}}'),
        ],
    )
    with pytest.raises(provider.ProbeError, match="^definition_operation_failed$"):
        client.definition(WORKSPACE, "semanticModels", MODEL, "model-1")
    assert_fabric_requests(requests, [GET_DEFINITION_URL, LRO_URL])
    assert sleeps == [1]
    assert [receipt["status"] for receipt in evidence.data["requests"]] == [202, 200]
