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
