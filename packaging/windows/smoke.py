"""Browser-level verification for an extracted Windows public-beta package.

The ZIP is treated as a user download: it is checksum-verified, extracted to a
path containing spaces and non-ASCII characters, and launched with a PATH that
does not expose Python. The browser then exercises packaged assets, the bundled
demo, exports, and a reviewed plan/apply/verify/restore cycle on disposable data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zipfile


ASSETS_BY_LAYOUT = {
    "v2": (
        "detail-workspace.js",
        "detail-workspace.css",
        "analysis-jobs.js",
        "policy-workspace.js",
        "schema-evidence.js",
    ),
    "classic": (
        "classic-plans.js",
        "classic-plans.css",
        "analysis-jobs.js",
        "policy-workspace.js",
        "schema-evidence.js",
    ),
}
EXPECTED_CHANNEL = "beta"


def _schema_smoke(request, model_paths: list[str], report_paths: list[str], timeout: float) -> dict:
    """Exercise the packaged schema registry through its real analysis endpoint."""
    report = Path(report_paths[0])
    visual = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
        "name": "PackagingSmoke",
        "position": {"x": 0, "y": 0, "height": 100, "width": 200},
        "visual": {"visualType": "card"},
    }
    for name, visual_type in (("PackagingValid", "card"), ("PackagingInvalid", 42)):
        path = report / "definition/pages/PackagingSmoke/visuals" / name / "visual.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = json.loads(json.dumps(visual))
        document["name"] = name
        document["visual"]["visualType"] = visual_type
        path.write_text(json.dumps(document), encoding="utf-8")
    (report / "definition/packaging-unknown.json").write_text(
        json.dumps({"$schema": "https://packaging-smoke.invalid/schema.json"}), encoding="utf-8"
    )
    response = json.loads(request("/api/analysis-jobs", {
        "model_paths": model_paths, "report_paths": report_paths,
    }))
    identity = response["job"]["id"]
    deadline = time.monotonic() + timeout
    while True:
        job = json.loads(request("/api/analysis-jobs/" + identity))["job"]
        if job["status"] == "completed":
            break
        if job["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"Packaged schema analysis {job['status']}: {job.get('error', '')}")
        if time.monotonic() >= deadline:
            raise RuntimeError("Packaged schema analysis timed out")
        time.sleep(0.1)
    validation = job["result"]["schemaValidation"]
    records = validation["files"]
    valid = next(record for record in records if record["path"].endswith("/PackagingValid/visual.json"))
    invalid = next(record for record in records if record["path"].endswith("/PackagingInvalid/visual.json"))
    unknown = next(record for record in records if record["path"].endswith("/packaging-unknown.json"))
    if valid["status"] != "valid":
        raise RuntimeError(f"Transitive schema fixture did not validate: {valid}")
    if invalid["status"] != "invalid" or not any(
        error["path"] == "/visual/visualType" and error["keyword"] == "type"
        for error in invalid["errors"]
    ):
        raise RuntimeError(f"Transitive schema error was not detected: {invalid}")
    if unknown["status"] != "not_validated" or unknown["reason"] != "unknown_schema":
        raise RuntimeError("Unknown schema was incorrectly accepted or fetched")
    if not validation["bundle"]["schema_count"] or validation["bundle"]["network_access"] is not False:
        raise RuntimeError("Missing offline schema bundle metadata")
    return validation["bundle"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_checksum(archive: Path, checksum: Path) -> str:
    expected = checksum.read_text(encoding="ascii").strip().split()[0].lower()
    actual = _sha256(archive)
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
        raise RuntimeError(f"SHA-256 mismatch for {archive.name}: expected {expected}, got {actual}")
    return actual


def _minimal_windows_path() -> str:
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return os.pathsep.join(str(path) for path in (windows / "System32", windows))


def _wait_for_url(log_path: Path, process: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Launcher exited early with code {process.returncode}")
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        match = re.search(r"URL\s*:\s*(http://127\.0\.0\.1:(\d+))", text)
        if match:
            return match.group(1)
        time.sleep(0.15)
    raise RuntimeError("Desktop launcher did not report its loopback URL")


def _browser_json(page, path: str, body: dict | None = None) -> dict:
    result = page.evaluate(
        """async ({path, body}) => {
          const response = await fetch(path, body === null ? undefined : {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
          });
          const text = await response.text();
          return {status: response.status, body: JSON.parse(text)};
        }""",
        {"path": path, "body": body},
    )
    if result["status"] >= 400:
        raise RuntimeError(f"{path} returned {result['status']}: {result['body']}")
    return result["body"]


def _require_completed_analysis(payload: dict) -> dict:
    job = payload.get("job") if isinstance(payload, dict) else None
    if not isinstance(job, dict):
        raise RuntimeError(f"Analysis status did not contain a job: {payload}")
    if job.get("status") != "completed":
        raise RuntimeError(
            f"Browser analysis ended with {job.get('status', 'unknown')}: {job.get('error', '')}"
        )
    result = job.get("result")
    if not isinstance(result, dict) or result.get("error") or not result.get("items"):
        raise RuntimeError(f"Completed browser analysis did not contain usable results: {result}")
    return job


def _run_browser_analysis(page, trigger: str, timeout: float) -> dict:
    timeout_ms = int(timeout * 1000)
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and response.url.rstrip("/").endswith("/api/analysis-jobs")
        ),
        timeout=timeout_ms,
    ) as started:
        page.locator(trigger).click()
    start_response = started.value
    if not start_response.ok:
        raise RuntimeError(
            f"Could not start browser analysis: HTTP {start_response.status} {start_response.text()}"
        )
    start_payload = start_response.json()
    job = start_payload.get("job", {})
    identity = job.get("id")
    if not identity:
        raise RuntimeError(f"Analysis start response did not contain a job ID: {start_payload}")

    page.locator(f"{trigger}:not([disabled])").wait_for(timeout=timeout_ms)
    final_response = page.request.get(
        start_response.url.rstrip("/") + "/" + identity,
        timeout=timeout_ms,
    )
    if not final_response.ok:
        raise RuntimeError(
            f"Could not read final analysis status: HTTP {final_response.status} {final_response.text()}"
        )
    return _require_completed_analysis(final_response.json())


def _url_request(base: str):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path: str, body: dict | None = None) -> bytes:
        data = None if body is None else json.dumps(body).encode()
        headers = {} if data is None else {"Content-Type": "application/json"}
        req = urllib.request.Request(base + path, data=data, headers=headers)
        with opener.open(req, timeout=10) as response:
            return response.read()

    return request


def run_smoke(*, archive: Path, checksum: Path, evidence_dir: Path, timeout: float) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install playwright and its Chromium browser before Windows verification") from exc

    archive = archive.resolve()
    checksum = checksum.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    archive_hash = _verify_checksum(archive, checksum)
    shutil.copy2(checksum, evidence_dir / checksum.name)
    (evidence_dir / f"{archive.name}.verified.sha256").write_text(
        f"{archive_hash}  {archive.name}\n", encoding="ascii"
    )

    root = Path(tempfile.gettempdir()) / f"Semantic Model Cleaner β verification {uuid.uuid4().hex}"
    root.mkdir(parents=True)
    log_path = root / "launcher.log"
    process = None
    occupied = None
    report: dict = {"archive": archive.name, "sha256": archive_hash, "checks": []}
    try:
        extracted = root / "downloaded package"
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        executable = extracted / "Semantic Model Cleaner.exe"
        manifest_path = extracted / "release.json"
        if not executable.is_file() or not manifest_path.is_file():
            raise RuntimeError("Extracted ZIP is missing the executable or release.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        version = manifest.get("version", "")
        expected_archive = f"semantic-model-cleaner-windows-x64-{version}.zip"
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+b\d+", version)
            or manifest.get("release_channel") != EXPECTED_CHANNEL
            or archive.name != expected_archive
        ):
            raise RuntimeError(f"Unexpected packaged release identity: {manifest}")
        report["release"] = manifest

        workspace = root / "empty workspace Zażółć"
        workspace.mkdir()
        user_dir = root / "user data Łódź"
        env = os.environ.copy()
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        env.pop("SMC_RELEASE_CHANNEL", None)
        env["SMC_USER_DIR"] = str(user_dir)
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = _minimal_windows_path()
        if "python" in env["PATH"].lower():
            raise RuntimeError("Verification PATH unexpectedly exposes Python")

        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 5001))
        occupied.listen(1)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(executable), str(workspace), "--host", "127.0.0.1", "--port", "5001", "--no-open-browser"],
                cwd=workspace,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        base = _wait_for_url(log_path, process, timeout)
        if base.endswith(":5001"):
            raise RuntimeError("Launcher did not fall back from the occupied preferred port")
        report["url"] = base
        report["python_free_path"] = env["PATH"]
        report["checks"].extend(["checksum", "release identity", "occupied-port fallback", "Python-free child PATH"])

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            console_messages: list[str] = []
            page_errors: list[str] = []
            page.on("console", lambda message: console_messages.append(f"{message.type}: {message.text}"))
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            try:
                page.goto(base + "/?ui=v2", wait_until="networkidle", timeout=30_000)
                if page.title() != "Semantic Model Cleaner":
                    raise RuntimeError(f"Unexpected page title: {page.title()}")
                page.locator(".beta-badge").wait_for(state="visible")
                if version not in page.locator(".build-stamp").inner_text():
                    raise RuntimeError("Packaged UI does not show the beta version")
                for layout, assets in ASSETS_BY_LAYOUT.items():
                    page.goto(base + "/?ui=" + layout, wait_until="networkidle")
                    content = page.content()
                    for asset in assets:
                        response = page.request.get(base + "/static/" + asset)
                        if asset not in content or not response.ok or not response.body():
                            raise RuntimeError(f"Missing packaged {layout} asset: {asset}")
                report["checks"].append("v2/classic UI and packaged assets")

                page.goto(base + "/?ui=v2", wait_until="networkidle")
                demo_job = _run_browser_analysis(page, "#btnLoadDemo", timeout)
                page.locator("#summarySection:not(.hidden)").wait_for(timeout=30_000)
                page.locator("#demoStatus").wait_for(state="visible")
                page.screenshot(path=evidence_dir / "01-demo-analysis.png", full_page=True)
                browser_state = page.evaluate(
                    "() => ({models: chosenModels, reports: chosenReports, itemCount: allItems.length})"
                )
                if len(browser_state["models"]) != 1 or not browser_state["reports"] or not browser_state["itemCount"]:
                    raise RuntimeError(f"Browser demo analysis returned incomplete state: {browser_state}")
                if len(demo_job["result"]["items"]) != browser_state["itemCount"]:
                    raise RuntimeError("Browser UI item count does not match the completed demo analysis job")
                model_path = Path(browser_state["models"][0]["path"])
                report_paths = [entry["path"] for entry in browser_state["reports"]]
                if not model_path.resolve().is_relative_to(user_dir.resolve()):
                    raise RuntimeError("Demo copy escaped the disposable non-ASCII user directory")
                source_file = model_path / "definition/tables/Sales.tmdl"
                original_hash = _sha256(source_file)
                report["checks"].append("browser demo analysis in spaces/non-ASCII paths")

                export = page.request.get(base + "/api/export?format=json")
                if not export.ok or not json.loads(export.body()).get("items"):
                    raise RuntimeError("Browser JSON export failed after demo analysis")
                report["checks"].append("browser JSON export")

                plan = _browser_json(page, "/api/plans", {
                    "model_path": str(model_path),
                    "report_paths": report_paths,
                    "operations": [{
                        "kind": "actions",
                        "actions": [{
                            "action": "hide", "table": "Sales", "name": "Revenue", "item_type": "Measure",
                        }],
                    }],
                })["plan"]
                if not plan.get("changes") or not plan["changes"][0].get("diff"):
                    raise RuntimeError("Reviewed plan did not contain an exact file diff")
                preview_hash = _sha256(source_file)
                if preview_hash != original_hash:
                    raise RuntimeError("Reviewed plan preview modified source bytes before apply")
                plan_id = plan["id"]
                applied = _browser_json(page, f"/api/plans/{plan_id}/apply", {})
                if not applied.get("ok") or _sha256(source_file) == original_hash:
                    raise RuntimeError("Reviewed plan did not apply its model change")
                applied_hash = _sha256(source_file)
                verified = _browser_json(page, f"/api/plans/{plan_id}/verify", {})
                if not verified.get("ok"):
                    raise RuntimeError(f"Applied plan did not verify: {verified}")
                page.screenshot(path=evidence_dir / "02-reviewed-plan-applied.png", full_page=True)
                restored = _browser_json(page, f"/api/plans/{plan_id}/restore", {})
                if not restored.get("ok") or _sha256(source_file) != original_hash:
                    raise RuntimeError("Plan restore did not recover the original model bytes")
                report["reviewed_plan"] = {
                    "id": plan_id,
                    "changed_paths": [change["path"] for change in plan["changes"]],
                    "original_sha256": original_hash,
                    "preview_sha256": preview_hash,
                    "applied_sha256": applied_hash,
                    "apply_status": applied.get("receipt", {}).get("status"),
                    "verify_state": verified.get("state"),
                    "restore_status": restored.get("receipt", {}).get("status"),
                    "restored_sha256": _sha256(source_file),
                }
                report["checks"].append("browser reviewed plan/apply/verify/restore with byte-exact recovery")

                restored_job = _run_browser_analysis(page, "#btnAnalyze", timeout)
                if len(restored_job["result"]["items"]) != browser_state["itemCount"]:
                    raise RuntimeError("Restored browser analysis returned an unexpected item count")
                page.screenshot(path=evidence_dir / "03-restored-and-reanalyzed.png", full_page=True)
                report["checks"].append("browser re-analysis after restore")

                bundle = _schema_smoke(_url_request(base), [str(model_path)], report_paths, timeout)
                report["schema_count"] = bundle["schema_count"]
                report["checks"].append("offline schema validation")
                if page_errors:
                    raise RuntimeError("Browser JavaScript exceptions: " + " | ".join(page_errors))
            except Exception:
                try:
                    page.screenshot(path=evidence_dir / "failure.png", full_page=True)
                except Exception:
                    pass
                raise
            finally:
                (evidence_dir / "browser-console.log").write_text("\n".join(console_messages), encoding="utf-8")
                (evidence_dir / "browser-page-errors.log").write_text("\n".join(page_errors), encoding="utf-8")
                browser.close()
        report["ok"] = True
        print("Windows public-beta smoke passed: " + ", ".join(report["checks"]))
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if occupied is not None:
            occupied.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
        if log_path.exists():
            shutil.copy2(log_path, evidence_dir / "launcher.log")
        (evidence_dir / "verification.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path, dest="archive", help="Downloaded Windows ZIP")
    parser.add_argument("--sha256", required=True, type=Path, help="Downloaded SHA-256 sidecar")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="Directory for logs and screenshots")
    parser.add_argument("--timeout", type=float, default=45, help="Server readiness timeout in seconds")
    args = parser.parse_args()
    run_smoke(
        archive=args.archive,
        checksum=args.sha256,
        evidence_dir=args.evidence_dir,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
