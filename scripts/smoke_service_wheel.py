"""Exercise experimental service CLI and HTTP flows from an installed wheel.

All service responses are synthetic. This cannot satisfy live/native acceptance.
Use --root NEW_DIRECTORY to retain the isolated install for manual browser checks.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from smoke_wheel import _artifact_digest, _free_port, _run, _wait_for_web

T, W, M, R = [f"00000000-0000-0000-0000-{i:012}" for i in range(1, 5)]


def exercise(wheel: Path, root: Path) -> None:
    subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True)
    scripts = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    python, smc, web = [str(scripts / (name + suffix)) for name in ("python", "smc", "smc-web")]
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "PYTHONPATH",
            "PYTHONHOME",
            "SMC_FABRIC_TOKEN",
            "SMC_POWERBI_TOKEN",
            "SMC_SERVICE_FIXTURE",
        }
    }
    env["SMC_USER_DIR"] = str(root / "user-state")
    _run([python, "-m", "pip", "install", str(wheel)], cwd=root, env=env)
    installed = _run(
        [python, "-c", "import semantic_model_cleaner.service_provider as p; print(p.__file__)"],
        cwd=root,
        env=env,
    ).stdout.strip()
    assert Path(installed).is_relative_to(root / "venv"), installed
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/service_probe/supported.json"
    data = json.loads(source.read_text())
    fixture = root / "supported.json"
    fixture.write_text(json.dumps(data))
    project = root / "project with spaces"
    model = project / "Candidate.SemanticModel"
    report = project / "R.Report"
    for directory, response in [(model, data["responses"][2]), (report, data["responses"][3])]:
        for part in response["body"]["definition"]["parts"]:
            path = directory / part["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(part["payload"]))
    (report / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../Candidate.SemanticModel"}}})
    )
    mapping = root / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target": {"tenant_id": T, "workspace_id": W, "model_id": M},
                "reports": [{"local_report": "R.Report", "workspace_id": W, "report_id": R}],
            }
        )
    )
    before = _artifact_digest(project)
    common = ["--tenant-id", T, "--workspace-id", W, "--model-id", M, "--report-workspace-id", W]

    def cli(action, extra=(), expected=0, transcript=fixture):
        return json.loads(
            _run(
                [smc, "service", action, *common, "--fixture", str(transcript), *extra],
                cwd=root,
                env=env,
                expected=expected,
            ).stdout
        )

    assert cli("discover")["known_connected_report_count"] == 1
    audited = cli("audit")
    assert audited["analysis"]["summary"]["total_usage_refs"] == 1
    assert not audited["global_completeness"] and not audited["cleanup_available"]
    assert cli("validate", ["--candidate", str(model)])["comparison"]["introduced"] == []
    compared = cli(
        "compare",
        ["--repository", str(project), "--local-model", str(model), "--mapping", str(mapping)],
    )
    assert (
        compared["repository_comparison"]["matched"][0]["definition_comparison"]["status"]
        == "equal_content_bytes"
    )
    assert _artifact_digest(project) == before
    # This deliberate fixture edit creates candidate-induced breakage, not a tool mutation.
    table = model / "definition/tables/Sales.tmdl"
    table.write_text("table Sales\n\tmeasure Renamed = 1\n")
    changed = _artifact_digest(project)
    candidate = cli("validate", ["--candidate", str(model)], expected=1)
    assert len(candidate["comparison"]["introduced"]) == 1
    denied = root / "denied.json"
    data["responses"][-1].update(status=403, body={})
    denied.write_text(json.dumps(data))
    partial = cli("audit", expected=2, transcript=denied)
    assert partial["report_health"]["checked"] is False
    assert partial["reports"][0]["status"] == "inaccessible"
    public = cli("audit", ["--public"])
    assert all(identity not in json.dumps(public) for identity in (T, W, M, R))
    assert _artifact_digest(project) == changed

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env["SMC_SERVICE_FIXTURE"] = str(fixture)
    with (root / "installed-web.log").open("w") as log:
        process = subprocess.Popen(
            [web, "--port", str(port)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT
        )
    try:
        _wait_for_web(base, process)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for path in ("/service", "/static/service.js", "/static/service.css"):
            with opener.open(base + path, timeout=5) as response:
                assert response.read()
        with opener.open(base + "/api/session", timeout=5) as response:
            token = json.loads(response.read())["token"]

        def api(path, method="GET", payload=None):
            request = urllib.request.Request(
                base + "/api/service/" + path,
                method=method,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"X-SMC-Token": token, "Content-Type": "application/json"},
            )
            with opener.open(request, timeout=5) as response:
                return json.loads(response.read())

        assert api("identity")["status"] == "synthetic_fixture"
        assert api("models", "POST", {"tenant_id": T, "workspace_id": W})["models"][0]["id"] == M
        selection = {
            "action": "validate",
            "tenant_id": T,
            "workspace_id": W,
            "model_id": M,
            "report_workspace_ids": [W],
            "candidate": str(model),
            "revision": api("state")["revision"],
        }
        job_id = api("jobs", "POST", selection)["id"]
        deadline = time.monotonic() + 15
        while True:
            job = api("jobs/" + job_id)
            if job["status"] not in {"running", "cancelling"}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Installed service job timed out")
            time.sleep(0.05)
        assert job["status"] == "completed" and job["result"]["exit_code"] == 1
        assert (
            job["result"]["comparison"]["report_definition_hashes"]
            == candidate["comparison"]["report_definition_hashes"]
        )
        assert len(job["result"]["comparison"]["introduced"]) == 1
        exported = api(f"jobs/{job_id}/export")
        assert all(identity not in json.dumps(exported) for identity in (T, W, M, R))
        assert api(f"jobs/{job_id}/export?private=1")["target"]["model_id"] == M
        api("jobs", "DELETE")
        try:
            api(f"jobs/{job_id}/export")
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("Expired service result was exported")
        assert _artifact_digest(project) == changed
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    print(
        "Installed service wheel smoke passed: four CLI workflows, exits 0/1/2, real analyzer, read-only source hashes, partial access, sanitized export, packaged HTTP/UI assets, CLI/API candidate agreement and expired exports. FIXTURE ONLY; live/native acceptance unverified."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    if args.root:
        root = args.root.resolve()
        root.mkdir(parents=True, exist_ok=False)
        exercise(wheel, root)
    else:
        with tempfile.TemporaryDirectory(prefix="smc-service-wheel-") as temporary:
            exercise(wheel, Path(temporary))


if __name__ == "__main__":
    main()
