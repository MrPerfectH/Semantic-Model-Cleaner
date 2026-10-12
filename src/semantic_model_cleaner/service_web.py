"""Isolated experimental service UI. Never publishes into offline cleanup state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

from flask import Blueprint, jsonify, render_template, request, Response

from .analysis_jobs import AnalysisJobs
from .service_cli import execute
from .service_provider import (
    ProbeError,
    ServiceProvider,
    authenticate,
    error_hint,
    guid,
    public_summary,
    result_exit,
)


class DeviceSignIn:
    """Explicit user-initiated existing Azure CLI login; no app registrations/consent grants."""

    def __init__(self):
        self.lock = threading.RLock()
        self.state = {"status": "idle"}
        self.process = None
        self.cancelled = threading.Event()

    def get(self):
        with self.lock:
            return dict(self.state)

    def cancel(self):
        with self.lock:
            self.cancelled.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.state = {"status": "cancelled"}
        return self.get()

    def start(self, tenant):
        tenant = guid(tenant)
        if not shutil.which("az"):
            raise ProbeError("linux_sign_in_required")
        with self.lock:
            if self.state["status"] in {"starting", "waiting"}:
                raise ProbeError("sign_in_already_running")
            self.state = {"status": "starting", "tenant_id": tenant}
            self.cancelled = threading.Event()
            event = self.cancelled

        def worker():
            process = None
            try:
                process = subprocess.Popen(
                    [
                        "az",
                        "login",
                        "--tenant",
                        tenant,
                        "--use-device-code",
                        "--allow-no-subscriptions",
                        "--output",
                        "none",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                with self.lock:
                    self.process = process
                    if event.is_set():
                        process.terminate()

                def read_prompt():
                    # Only the fixed login URL and short challenge are surfaced. Never raw CLI output.
                    for line in process.stderr:
                        match = re.search(r"enter the code\s+([A-Z0-9]{6,12})", line, re.IGNORECASE)
                        if match:
                            with self.lock:
                                if not event.is_set() and self.state["status"] in {
                                    "starting",
                                    "waiting",
                                }:
                                    self.state = {
                                        "status": "waiting",
                                        "tenant_id": tenant,
                                        "verification_uri": "https://microsoft.com/devicelogin",
                                        "user_code": match.group(1),
                                    }

                reader = threading.Thread(target=read_prompt, daemon=True)
                reader.start()
                deadline = time.monotonic() + 600
                while process.poll() is None:
                    if event.is_set() or time.monotonic() > deadline:
                        process.terminate()
                        raise ProbeError("sign_in_cancelled_or_expired")
                    time.sleep(0.2)
                if process.returncode:
                    raise ProbeError("sign_in_failed")
                _, claims = authenticate()
                if claims["fabric"][0] != tenant:
                    raise ProbeError("selected_tenant_mismatch")
                with self.lock:
                    if not event.is_set():
                        self.state = {
                            "status": "ready",
                            "tenant_id": tenant,
                            "workspace_access": "not_yet_checked",
                        }
            except Exception:
                with self.lock:
                    if not event.is_set():
                        self.state = {
                            "status": "failed",
                            "code": "sign_in_failed",
                            "message": "Local sign-in did not complete with the required API tokens. Check the existing approved client and permissions; no target was changed.",
                        }
            finally:
                if process:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if process.stderr:
                        process.stderr.close()

        threading.Thread(target=worker, name="smc-service-signin", daemon=True).start()
        return self.get()


def install_service_routes(app, local_context):
    blueprint = Blueprint("service_validation", __name__)
    jobs, sign_in = AnalysisJobs(), DeviceSignIn()
    lock = threading.RLock()
    state = {"revision": 0, "job_id": None}

    def fixture():
        # Test mode is chosen by the server process, never by a browser request.
        return app.config.get("SMC_SERVICE_FIXTURE") or os.environ.get("SMC_SERVICE_FIXTURE")

    def failure(exc, status=400):
        code = str(exc) if isinstance(exc, ProbeError) else "invalid_service_input"
        return jsonify(ok=False, code=code, error=error_hint(code), experimental=True), status

    @blueprint.get("/service")
    def page():
        context = local_context()
        return render_template(
            "service.html",
            local_request_token=app.config["SMC_LOCAL_TOKEN"],
            candidate=context.get("candidate", ""),
            repository=context.get("repository", ""),
            fixture_mode=bool(fixture()),
        )

    @blueprint.get("/api/service/state")
    def service_state():
        with lock:
            return jsonify(
                experimental=True,
                fixture_mode=bool(fixture()),
                revision=state["revision"],
                sign_in=sign_in.get(),
                azure_cli_available=bool(shutil.which("az")),
            )

    @blueprint.get("/api/service/identity")
    def identity():
        try:
            if fixture():
                data = json.loads(Path(fixture()).read_text())
                return jsonify(
                    tenant_id=guid(data["tenant_id"]),
                    status="synthetic_fixture",
                    workspace_access="not_yet_checked",
                )
            _, claims = authenticate()
            return jsonify(
                tenant_id=claims["fabric"][0],
                status="credential_claim_only",
                workspace_access="not_yet_checked",
            )
        except (ProbeError, OSError, ValueError, KeyError) as exc:
            return failure(exc)

    @blueprint.route("/api/service/sign-in", methods=["POST", "GET", "DELETE"])
    def login():
        try:
            if request.method == "GET":
                return jsonify(sign_in.get())
            if request.method == "DELETE":
                return jsonify(sign_in.cancel())
            if fixture():
                raise ProbeError("fixture_mode_has_no_live_sign_in")
            return jsonify(sign_in.start((request.get_json(silent=True) or {}).get("tenant_id")))
        except (ProbeError, TypeError, AttributeError) as exc:
            return failure(exc)

    @blueprint.post("/api/service/models")
    def models():
        try:
            data = request.get_json(silent=True) or {}
            selection = SimpleNamespace(
                tenant_id=guid(data.get("tenant_id")), workspace_id=guid(data.get("workspace_id"))
            )
            provider = ServiceProvider(selection, fixture=fixture())
            values = provider.models()
            return jsonify(
                models=values,
                tenant_id=selection.tenant_id,
                workspace_id=selection.workspace_id,
                access="synthetic_fixture" if fixture() else "authenticated_workspace_access",
            )
        except (ProbeError, ValueError, TypeError, AttributeError) as exc:
            return failure(exc)

    @blueprint.route("/api/service/jobs", methods=["POST", "DELETE"])
    def service_jobs():
        try:
            with lock:
                if request.method == "DELETE":
                    with jobs.invalidate():
                        state["revision"] += 1
                        state["job_id"] = None
                    return jsonify(revision=state["revision"], status="invalidated")
                data = request.get_json(silent=True) or {}
                if data.get("revision") != state["revision"]:
                    raise ProbeError("service_selection_changed")
                if data.get("action") not in {"discover", "audit", "validate", "compare"}:
                    raise ProbeError("invalid_service_action")
                from .service_provider import Target

                target = Target(
                    data.get("tenant_id"),
                    data.get("workspace_id"),
                    data.get("model_id"),
                    tuple(data.get("report_workspace_ids", [])),
                )
                args = SimpleNamespace(
                    action=data["action"],
                    tenant_id=target.tenant_id,
                    workspace_id=target.workspace_id,
                    model_id=target.model_id,
                    report_workspace_id=target.report_workspace_ids,
                    fixture=fixture(),
                    candidate=Path(data["candidate"]) if data.get("candidate") else None,
                    repository=Path(data["repository"]) if data.get("repository") else None,
                    local_model=Path(data["local_model"]) if data.get("local_model") else None,
                    mapping=Path(data["mapping"]) if data.get("mapping") else None,
                )

                def run(progress):
                    result = execute(args, progress=progress)
                    result["exit_code"] = result_exit(result)
                    return result

                job = jobs.start(run)
                state["job_id"] = job["id"]
                return jsonify(job), 202
        except (ProbeError, ValueError, TypeError, AttributeError) as exc:
            return failure(exc, 409 if isinstance(exc, ValueError) else 400)

    @blueprint.route("/api/service/jobs/<identity>", methods=["GET", "DELETE"])
    def service_job(identity):
        with lock:
            if identity != state["job_id"]:
                return jsonify(error="Service result expired after selection changed."), 404
            try:
                value = jobs.cancel(identity) if request.method == "DELETE" else jobs.get(identity)
                if value.get("error"):
                    value["error"] = (
                        "Service operation failed. Check the selected target, local paths and existing sign-in."
                    )
                return jsonify(value)
            except KeyError:
                return jsonify(error="Service result expired."), 404

    @blueprint.get("/api/service/jobs/<identity>/export")
    def export(identity):
        with lock:
            if identity != state["job_id"]:
                return jsonify(error="Service result expired after selection changed."), 404
            job = jobs.get(identity)
            if job["status"] != "completed":
                return jsonify(error="No completed service result is available."), 409
            result = job["result"]
            private = request.args.get("private") == "1"
            payload = result if private else public_summary(result)
            return Response(
                json.dumps(payload, indent=2),
                mimetype="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="service-'
                    + ("private-result" if private else "sanitized-summary")
                    + '.json"',
                    "Cache-Control": "no-store",
                },
            )

    @blueprint.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(blueprint)
    return jobs
