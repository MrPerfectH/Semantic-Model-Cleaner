"""Install a wheel with resolved dependencies in a fresh venv outside checkout.

The probe uses the installed smc and smc-web console scripts. It checks the
read-only CI contract for exit codes 0/1/2, baseline adoption without model or
report writes, and the packaged web UI/assets over loopback HTTP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def _run(command: list[str], *, cwd: Path, env: dict, expected: int = 0) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode != expected:
        raise RuntimeError(
            f"Expected exit {expected}, got {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _artifact_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _write_check_fixture(root: Path) -> None:
    tables = root / "M.SemanticModel/definition/tables"
    tables.mkdir(parents=True)
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tmeasure Broken = [Missing]\n\tcolumn Spare\n", encoding="utf-8"
    )
    report = root / "R.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": "../M.SemanticModel"}}}), encoding="utf-8"
    )


def _wait_for_web(base: str, process: subprocess.Popen, timeout: float = 30) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"smc-web exited early with {process.returncode}")
        try:
            with opener.open(base + "/?ui=v2", timeout=3) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.15)
    raise RuntimeError("smc-web did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--base-python", default=sys.executable, help="Interpreter used to create the clean venv")
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        parser.error(f"Wheel not found: {wheel}")

    with tempfile.TemporaryDirectory(prefix="smc-wheel-consumer-") as temporary:
        root = Path(temporary).resolve()
        venv = root / "fresh environment"
        subprocess.run([args.base_python, "-m", "venv", str(venv)], check=True, cwd=root)
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        smc = scripts / ("smc.exe" if os.name == "nt" else "smc")
        smc_web = scripts / ("smc-web.exe" if os.name == "nt" else "smc-web")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("SMC_RELEASE_CHANNEL", None)
        env["SMC_USER_DIR"] = str(root / "user state")

        # Do not use --no-deps: this is the clean-user dependency resolution gate.
        _run([str(python), "-m", "pip", "install", str(wheel)], cwd=root, env=env)
        identity = _run(
            [str(python), "-c",
             "import json, pathlib, semantic_model_cleaner as s; "
             "print(json.dumps({'path': str(pathlib.Path(s.__file__).resolve()), "
             "'version': s.__version__, 'channel': s.__release_channel__}))"],
            cwd=root, env=env,
        )
        installed = json.loads(identity.stdout)
        if (
            not Path(installed["path"]).is_relative_to(venv)
            or installed["version"] != "0.4.0b1"
            or installed["channel"] != "beta"
        ):
            raise RuntimeError(f"Unexpected installed wheel identity: {installed}")
        if not smc.is_file() or not smc_web.is_file():
            raise RuntimeError("Wheel did not install the smc and smc-web entry points")

        project = root / "repository with spaces"
        _write_check_fixture(project)
        before = _artifact_digest(project)
        violation = _run([str(smc), "check", str(project), "--format", "json"], cwd=root, env=env, expected=1)
        if json.loads(violation.stdout)["schema_version"] != "1.0":
            raise RuntimeError("smc check did not return the versioned JSON contract")
        baseline = root / "reviewed baseline.json"
        _run([str(smc), "check", str(project), "--write-baseline", str(baseline)], cwd=root, env=env, expected=1)
        passed = _run(
            [str(smc), "check", str(project), "--baseline", str(baseline), "--format", "json"],
            cwd=root, env=env, expected=0,
        )
        if not json.loads(passed.stdout)["ok"]:
            raise RuntimeError("Reviewed baseline did not produce exit 0")
        invalid = root / "invalid empty input"
        invalid.mkdir()
        _run([str(smc), "check", str(invalid), "--format", "json"], cwd=root, env=env, expected=2)
        if _artifact_digest(project) != before:
            raise RuntimeError("smc check or baseline creation modified the input repository")

        port = _free_port()
        log = root / "smc-web.log"
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [str(smc_web), str(project), "--host", "127.0.0.1", "--port", str(port)],
                cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, text=True,
            )
        try:
            html = _wait_for_web(f"http://127.0.0.1:{port}", process)
            if b"Semantic Model Cleaner" not in html or b"0.4.0b1" not in html or b"beta-badge" not in html:
                raise RuntimeError("Installed smc-web did not serve the public-beta UI")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for asset in ("detail-workspace.js", "analysis-jobs.js", "schema-evidence.js"):
                with opener.open(f"http://127.0.0.1:{port}/static/{asset}", timeout=5) as response:
                    if not response.read():
                        raise RuntimeError(f"Installed wheel did not serve {asset}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        print(
            "Fresh-wheel smoke passed: resolved runtime dependencies, installed beta identity, "
            "real smc/smc-web entry points, check exits 0/1/2, reviewed baseline, no metadata "
            "writes, loopback UI and packaged assets."
        )


if __name__ == "__main__":
    main()
