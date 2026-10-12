"""Synthetic application flow tests. Live/native acceptance is a separate gate."""

from pathlib import Path
import threading
import time

import pytest
from flask.testing import FlaskClient

from semantic_model_cleaner import webapp
from semantic_model_cleaner.service_web import DeviceSignIn
from semantic_model_cleaner.service_provider import ProbeError

FIXTURE = Path(__file__).parent / "fixtures/service_probe/supported.json"
T, W, M = [f"00000000-0000-0000-0000-{i:012}" for i in range(1, 4)]


@pytest.fixture
def service_client(monkeypatch):
    monkeypatch.setitem(webapp.app.config, "SMC_SERVICE_FIXTURE", str(FIXTURE))
    client = webapp.app.test_client()
    client.delete("/api/service/jobs")
    yield client
    client.delete("/api/service/jobs")


def payload(client, **overrides):
    return dict(
        action="audit",
        tenant_id=T,
        workspace_id=W,
        model_id=M,
        report_workspace_ids=[W],
        revision=client.get("/api/service/state").json["revision"],
        **overrides,
    )


def wait_job(client, identity):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/api/service/jobs/" + identity).json
        if job["status"] not in {"running", "cancelling"}:
            return job
        time.sleep(0.01)
    raise AssertionError("service job did not finish")


def test_service_page_and_offline_entrypoints(service_client):
    page = service_client.get("/service")
    assert page.status_code == 200
    assert b"Synthetic fixture mode" in page.data
    assert b"Live service compatibility is unverified" in page.data
    for path in ["/", "/?ui=classic"]:
        assert b'href="/service"' in service_client.get(path).data
    assert b"smcFetch" in service_client.get("/static/service.js").data


def test_model_selection_run_and_export_do_not_replace_local_cleanup_state(
    service_client, monkeypatch
):
    sentinel = {"private_offline_result": "preserve"}
    monkeypatch.setitem(webapp._state, "last_results", sentinel)
    identity = service_client.get("/api/service/identity").json
    assert identity["status"] == "synthetic_fixture"
    models = service_client.post(
        "/api/service/models", json={"tenant_id": T, "workspace_id": W}
    ).json
    assert models["models"][0]["id"] == M
    started = service_client.post("/api/service/jobs", json=payload(service_client))
    assert started.status_code == 202
    job_id = started.json["id"]
    job = wait_job(service_client, job_id)
    assert job["status"] == "completed"
    assert job["result"]["analysis"]["summary"]["total_usage_refs"] == 1
    assert job["result"]["exit_code"] == 0
    assert webapp._state["last_results"] is sentinel
    summary = service_client.get(f"/api/service/jobs/{job_id}/export")
    assert summary.status_code == 200
    assert T.encode() not in summary.data and M.encode() not in summary.data
    private = service_client.get(f"/api/service/jobs/{job_id}/export?private=1").json
    assert private["target"]["model_id"] == M
    assert private["snapshot"]["cached"] is False
    assert summary.headers["Cache-Control"] == "no-store"
    service_client.delete("/api/service/jobs")
    assert service_client.get(f"/api/service/jobs/{job_id}/export").status_code == 404
    assert service_client.get(f"/api/service/jobs/{job_id}").status_code == 404


def test_stale_selection_and_wrong_tenant_are_rejected(service_client):
    old = payload(service_client)
    service_client.delete("/api/service/jobs")
    assert service_client.post("/api/service/jobs", json=old).status_code == 400
    data = payload(service_client)
    data["tenant_id"] = W
    started = service_client.post("/api/service/jobs", json=data)
    job = wait_job(service_client, started.json["id"])
    assert job["result"]["status"] == "failed"
    assert job["result"]["requests"] == []
    assert job["result"]["exit_code"] == 2


def test_service_api_requires_existing_local_request_boundary():
    client = FlaskClient(webapp.app)
    assert client.get("/api/service/state").status_code == 403
    assert client.post("/api/service/jobs", json={}).status_code == 403
    assert client.post("/api/service/sign-in", json={}).status_code == 403


def test_cancellation_discards_result_and_target_switch_clears_it(service_client, monkeypatch):
    from semantic_model_cleaner import service_web

    entered = threading.Event()
    release = threading.Event()

    def slow(args, progress):
        entered.set()
        release.wait(2)
        progress("request finished")
        raise AssertionError("cancelled result must not publish")

    monkeypatch.setattr(service_web, "execute", slow)
    started = service_client.post("/api/service/jobs", json=payload(service_client))
    job_id = started.json["id"]
    assert entered.wait(1)
    cancelled = service_client.delete("/api/service/jobs/" + job_id)
    assert cancelled.json["status"] == "cancelling"
    release.set()
    assert wait_job(service_client, job_id)["status"] == "cancelled"
    assert service_client.get(f"/api/service/jobs/{job_id}/export").status_code == 409


def test_fixture_cannot_be_chosen_by_browser_and_signin_unavailable(service_client, monkeypatch):
    monkeypatch.setitem(webapp.app.config, "SMC_SERVICE_FIXTURE", None)
    monkeypatch.delenv("SMC_SERVICE_FIXTURE", raising=False)
    monkeypatch.delenv("SMC_FABRIC_TOKEN", raising=False)
    monkeypatch.delenv("SMC_POWERBI_TOKEN", raising=False)
    from semantic_model_cleaner import service_web

    monkeypatch.setattr(service_web.shutil, "which", lambda _: None)
    response = service_client.post("/api/service/sign-in", json={"tenant_id": T})
    assert response.json["code"] == "linux_sign_in_required"
    data = payload(service_client)
    data["fixture"] = str(FIXTURE)
    job = wait_job(service_client, service_client.post("/api/service/jobs", json=data).json["id"])
    assert job["result"]["evidence_kind"] == "live"
    assert job["result"]["errors"][0]["code"] == "linux_sign_in_required"
    with pytest.raises(ProbeError):
        DeviceSignIn().start(T)


def test_app_candidate_matches_cli_supported_snapshot(service_client, tmp_path):
    from semantic_model_cleaner.service_analysis import validate_candidate
    from semantic_model_cleaner.service_provider import ServiceProvider, Target

    model = tmp_path / "Candidate.SemanticModel"
    (model / "definition/tables").mkdir(parents=True)
    (model / "definition/model.tmdl").write_text("model Model\n")
    (model / "definition/tables/Sales.tmdl").write_text("table Sales\n\tmeasure Renamed = 1\n")
    data = payload(service_client)
    data.update(action="validate", candidate=str(model))
    job = wait_job(service_client, service_client.post("/api/service/jobs", json=data).json["id"])
    expected = validate_candidate(ServiceProvider(Target(T, W, M, (W,)), fixture=FIXTURE), model)
    normalize = lambda rows: [{k: v for k, v in row.items() if k != "reportPath"} for row in rows]
    assert normalize(job["result"]["comparison"]["introduced"]) == normalize(
        expected["comparison"]["introduced"]
    )
    assert (
        job["result"]["comparison"]["report_definition_hashes"]
        == expected["comparison"]["report_definition_hashes"]
    )
    assert job["result"]["exit_code"] == 1
    assert job["result"]["candidate"]["unchanged_after_run"] is True


def test_explicit_device_signin_success_and_cancellation_are_local_only(monkeypatch):
    import io
    from semantic_model_cleaner import service_web

    monkeypatch.setattr(service_web.shutil, "which", lambda _: "/approved/az")
    calls = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            calls.append(command)
            self.stderr = io.StringIO("To sign in, enter the code FIXTURE88\n")
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(service_web.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(service_web, "authenticate", lambda: ({}, {"fabric": (T,)}))
    signin = DeviceSignIn()
    signin.start(T)
    deadline = time.monotonic() + 2
    while signin.get()["status"] != "ready" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert signin.get()["status"] == "ready"
    assert "user_code" not in signin.get()
    assert calls == [
        [
            "az",
            "login",
            "--tenant",
            T,
            "--use-device-code",
            "--allow-no-subscriptions",
            "--output",
            "none",
        ]
    ]
    assert signin.cancel()["status"] == "cancelled"
    assert "user_code" not in signin.get()
