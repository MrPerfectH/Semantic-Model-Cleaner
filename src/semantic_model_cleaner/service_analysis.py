"""Read-only service snapshots and projections over the existing analyzer."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from . import analyzer
from .service_provider import (
    ProbeError,
    error_hint,
    limitation,
    now,
    unpack_definition,
    verify_report_binding,
)


@dataclass
class Snapshot:
    root: Path
    model: Path | None
    reports: list[Path]
    result: dict


def add_gap(result, code, owner):
    result["analysis_limitations"].append(limitation(code, owner))
    result["selected_scope_complete"] = False
    result["status"] = "incomplete"


@contextmanager
def snapshot(provider):
    result = provider.discover()
    result.update(
        command="service audit",
        snapshot={
            "id": uuid4().hex,
            "cached": False,
            "started_at": now(),
            "storage": "private temporary directory; deleted after operation",
            "transactionally_consistent": False,
        },
        model_definition=None,
    )
    with tempfile.TemporaryDirectory(prefix="smc-service-snapshot-") as temporary:
        root = Path(temporary)
        state = Snapshot(root, None, [], result)
        if result["status"] != "failed":
            try:
                provider.progress("Retrieving published Semantic Model")
                target = provider.target
                model = root / "Published.SemanticModel"
                info = unpack_definition(
                    provider.client.definition(
                        target.workspace_id, "semanticModels", target.model_id, "selected_model"
                    ),
                    model,
                    "model",
                )
                result["model_definition"] = {
                    **info,
                    "tenant_id": target.tenant_id,
                    "workspace_id": target.workspace_id,
                    "model_id": target.model_id,
                    "cached": False,
                }
                state.model = model
                for row in result["reports"]:
                    if row["connection"] != "exact_model_id":
                        continue
                    try:
                        provider.progress(
                            "Retrieving Report definitions",
                            len(state.reports),
                            result["known_connected_report_count"],
                        )
                        path = root / f"{row['workspace_id']}_{row['report_id']}.Report"
                        body = provider.client.definition(
                            row["workspace_id"], "reports", row["report_id"], "connected_report"
                        )
                        row["retrieved_at"] = now()
                        row["definition"] = {
                            **unpack_definition(body, path, "report"),
                            "cached": False,
                        }
                        verify_report_binding(path, target.model_id)
                        row["status"] = "retrieved"
                        row["_snapshot_path"] = str(path)
                        state.reports.append(path)
                    except ProbeError as exc:
                        row["status"] = (
                            "inaccessible"
                            if str(exc) in {"access_denied", "not_found_or_inaccessible"}
                            else "not_analyzed"
                        )
                        row["reason"] = str(exc)
                        add_gap(result, str(exc), row["report_id"])
            except ProbeError as exc:
                result.update(status="failed", selected_scope_complete=False)
                result["errors"].append({"code": str(exc), "message": error_hint(str(exc))})
                result["analysis_limitations"].append(limitation(str(exc), "selected_model"))
        try:
            yield state
        finally:
            finalize_coverage(result)
            for row in result["reports"]:
                row.pop("_snapshot_path", None)
            result["snapshot"]["finished_at"] = now()
            result["finished_at"] = now()
            result["requests"] = provider.evidence.data["requests"]


def finalize_coverage(result):
    """Keep every service projection's limitation units/IDs coherent at publication."""
    result["analysis_limitations"] = list(
        {gap["id"]: gap for gap in result["analysis_limitations"]}.values()
    )
    shared_ids = [gap["id"] for gap in result["analysis_limitations"] if gap["scope"] == "shared"]
    if "analysis" not in result:
        return
    result["coverage"] = {
        "complete": False,
        "selected_scope_complete": result["selected_scope_complete"],
        "limitations": result["analysis_limitations"],
    }
    for key in ("analysis", "candidate_analysis"):
        analysis = result.get(key)
        if not analysis:
            continue
        analysis["coverage"] = result["coverage"]
        analysis["analysisLimitations"] = result["analysis_limitations"]
        for item in analysis["items"]:
            if item["status"] == "No Use Found In Scope":
                item["analysisLimitationIds"] = list(
                    dict.fromkeys([*item["analysisLimitationIds"], *shared_ids])
                )
                if item["removalRisk"] == "Safe":
                    item["removalRisk"] = "Review"
        analysis["analysisLimitationSummary"] = {
            "distinct_count": len(result["analysis_limitations"]),
            "shared_count": len(shared_ids),
            "targeted_count": len(result["analysis_limitations"]) - len(shared_ids),
            "affected_item_count": sum(
                bool(item["analysisLimitationIds"]) for item in analysis["items"]
            ),
        }


def analyze_snapshot(state, model, provider):
    """Return detailed supported analysis, with durable source identities/locations."""
    raw = analyzer.analyze(
        state.root,
        model_paths=[model],
        report_paths=state.reports,
        allow_model_only=True,
        progress=provider.progress,
    )
    rows = {
        row.get("_snapshot_path"): row
        for row in state.result["reports"]
        if row.get("_snapshot_path")
    }
    # The existing JSON formatter preserves report-extension and dependency semantics.
    exported = json.loads(analyzer.format_json_output(raw))
    findings = []
    for issue in exported["reportIssues"]:
        row = rows.get(issue.get("reportPath"))
        findings.append(
            {
                **issue,
                **(
                    {
                        "report_id": row["report_id"],
                        "workspace_id": row["workspace_id"],
                        "service_url": row["service_url"],
                    }
                    if row
                    else {}
                ),
            }
        )
    exported["reportIssues"] = findings

    # Temporary local paths are not durable provenance. Retain artifact-relative paths.
    def durable(value):
        if isinstance(value, dict):
            return {key: durable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [durable(item) for item in value]
        if isinstance(value, str):
            return value.replace(str(state.root), "snapshot://" + state.result["snapshot"]["id"])
        return value

    exported = durable(exported)
    for item in exported["items"]:
        if not analyzer.is_used_status(item["status"]):
            if item["removalRisk"] == "Safe":
                item["removalRisk"] = "Review"
            item["reviewTriggers"] = list(
                dict.fromkeys(
                    [
                        *item["reviewTriggers"],
                        "Service discovery is bounded; no global non-use or cleanup safety is established.",
                    ]
                )
            )
            item["reviewBasis"] = "evidence"
            if item["status"] == "NOT USED":
                item["status"] = "No Use Found In Scope"
    return exported


def audit_state(state, provider):
    result = state.result
    if state.model is None:
        return result
    try:
        provider.progress("Analyzing published model and Reports")
        analysis = analyze_snapshot(state, state.model, provider)
        result["analysis"] = analysis
        result["report_health"] = {
            "checked": bool(state.reports),
            "findings": analysis["reportIssues"],
        }
        for row in result["reports"]:
            if row["status"] == "retrieved":
                row["status"] = "analyzed"
        for gap in analysis["analysisLimitations"]:
            result["analysis_limitations"].append({**gap, "code": "parser_analysis_limitation"})
        if not analysis["coverage"]["complete"]:
            result["selected_scope_complete"] = False
        if not state.reports:
            add_gap(result, "no_supported_connected_report_analyzed", "selected_scope")
        result["analysis_limitations"].append(
            limitation(
                "bounded_service_scope",
                "selected_scope",
                unchecked="Consumers outside the selected accessible workspaces, indirect models and other consumer types remain unknown.",
            )
        )
        # Coverage used for cleanup always stays incomplete. The independent scoped flag
        # concerns supported metadata validation, not consumer or deployment completeness.
        result["coverage"] = {
            "complete": False,
            "selected_scope_complete": result["selected_scope_complete"],
            "limitations": result["analysis_limitations"],
        }
        analysis["parser_coverage"] = analysis["coverage"]
        analysis["coverage"] = result["coverage"]
        analysis["analysisLimitations"] = result["analysis_limitations"]
        boundary_id = result["analysis_limitations"][-1]["id"]
        for item in analysis["items"]:
            if item["status"] == "No Use Found In Scope":
                item["analysisLimitationIds"] = list(
                    dict.fromkeys([*item["analysisLimitationIds"], boundary_id])
                )
        analysis["analysisLimitationSummary"] = {
            "distinct_count": len(result["analysis_limitations"]),
            "shared_count": sum(g["scope"] == "shared" for g in result["analysis_limitations"]),
            "targeted_count": sum(g["scope"] != "shared" for g in result["analysis_limitations"]),
            "affected_item_count": sum(bool(i["analysisLimitationIds"]) for i in analysis["items"]),
        }
        result["status"] = (
            "complete_within_selected_scope" if result["selected_scope_complete"] else "incomplete"
        )
    except ProbeError:
        raise
    except Exception as exc:
        # Cancellation must propagate to the job manager without publishing stale results.
        from .analysis_jobs import AnalysisCancelled

        if isinstance(exc, AnalysisCancelled):
            raise
        result["status"] = "failed"
        result["selected_scope_complete"] = False
        result["errors"].append(
            {
                "code": "existing_analysis_failed",
                "message": "The supported analyzer could not read this snapshot. No result is safe for cleanup.",
            }
        )
        result["analysis_limitations"].append(
            limitation("existing_analysis_failed", "selected_model")
        )
    return result


def audit(provider, *, repository=None, local_model=None, mapping=None):
    with snapshot(provider) as state:
        result = audit_state(state, provider)
        attach_repository(state, provider, repository, local_model, mapping)
        return result


def attach_repository(state, provider, repository, local_model, mapping):
    if repository is None:
        return
    from .service_repository import compare_repository

    try:
        if local_model is None:
            raise ProbeError("repository_local_model_required")
        compare_repository(state, provider, repository, local_model, mapping)
    except ProbeError as exc:
        add_gap(state.result, str(exc), "local_repository")
    if state.result.get("coverage"):
        state.result["coverage"]["selected_scope_complete"] = state.result[
            "selected_scope_complete"
        ]


def tree_digest(root, *, copy_to=None):
    """Hash exact source bytes; optionally snapshot them without following symlinks."""
    import hashlib
    from .service_provider import MAX_BYTES

    root = Path(root)
    if root.is_symlink() or not root.is_dir() or not (root / "definition/model.tmdl").is_file():
        raise ProbeError("candidate_requires_exact_tmdl_model_directory")
    digest, total = hashlib.sha256(), 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProbeError("candidate_symlinks_not_supported")
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise ProbeError("candidate_size_limit")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0" + data + b"\0")
        if copy_to:
            destination = copy_to / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    return digest.hexdigest()


def finding_key(finding):
    """Same retrieved Report location/reference, independent of model snapshot paths."""
    return tuple(
        finding.get(key, "")
        for key in (
            "workspace_id",
            "report_id",
            "issueType",
            "page",
            "visualId",
            "context",
            "table",
            "name",
            "refType",
            "artifactKind",
            "sourcePath",
            "selectorValue",
        )
    )


def validate_candidate(provider, candidate, *, repository=None, local_model=None, mapping=None):
    with snapshot(provider) as state:
        result = audit_state(state, provider)
        result["command"] = "service validate"
        result["validation_limits"] = [
            "Static metadata reference validation does not prove expression semantics, relationship behavior, DAX execution, rendering or data correctness.",
            "The local candidate is explicitly compared with this deployment; no environment equivalence is inferred.",
        ]
        if "analysis" not in result:
            return result
        try:
            provider.progress("Snapshotting local TMDL candidate")
            copied = state.root / "Candidate.SemanticModel"
            candidate = Path(candidate)
            digest = tree_digest(candidate, copy_to=copied)
            result["candidate"] = {
                "source_kind": "local_candidate",
                "path": str(candidate.absolute()),
                "sha256": digest,
                "captured_at": now(),
                "unchanged_after_run": None,
            }
            candidate_analysis = analyze_snapshot(state, copied, provider)
            baseline_findings = result["report_health"]["findings"]
            candidate_findings = candidate_analysis["reportIssues"]
            baseline = {finding_key(f): f for f in baseline_findings}
            proposed = {finding_key(f): f for f in candidate_findings}
            result["comparison"] = {
                "pre_existing": [proposed[k] for k in proposed.keys() & baseline.keys()],
                "introduced": [proposed[k] for k in proposed.keys() - baseline.keys()],
                "resolved": [baseline[k] for k in baseline.keys() - proposed.keys()],
                "published_baseline_findings": baseline_findings,
                "same_report_snapshot": True,
                "report_definition_hashes": [
                    row["definition"]["sha256"]
                    for row in result["reports"]
                    if row.get("_snapshot_path")
                ],
                "static_reference_check_only": True,
            }
            # Sort for deterministic exports regardless of hash randomization.
            for category in ("pre_existing", "introduced", "resolved"):
                result["comparison"][category].sort(key=lambda f: repr(finding_key(f)))
            result["report_health"] = {
                "checked": bool(state.reports),
                "findings": candidate_findings,
            }
            if not candidate_analysis["coverage"]["complete"]:
                result["selected_scope_complete"] = False
            for gap in candidate_analysis["analysisLimitations"]:
                result["analysis_limitations"].append(
                    {
                        **gap,
                        "id": "candidate:" + gap["id"],
                        "code": "candidate_parser_analysis_limitation",
                    }
                )
            result["candidate"]["unchanged_after_run"] = tree_digest(candidate) == digest
            if not result["candidate"]["unchanged_after_run"]:
                add_gap(result, "candidate_changed_during_validation", "local_candidate")
            candidate_analysis["parser_coverage"] = candidate_analysis["coverage"]
            candidate_analysis["coverage"] = {
                "complete": False,
                "limitations": result["analysis_limitations"],
            }
            result["candidate_analysis"] = candidate_analysis
            result["coverage"]["selected_scope_complete"] = result["selected_scope_complete"]
            result["status"] = (
                "complete_within_selected_scope"
                if result["selected_scope_complete"]
                else "incomplete"
            )
        except (ProbeError, OSError) as exc:
            code = str(exc) if isinstance(exc, ProbeError) else "candidate_unreadable"
            add_gap(result, code, "local_candidate")
            result["errors"].append(
                {
                    "code": code,
                    "message": "Choose an exact readable TMDL candidate directory. Local files were not changed.",
                }
            )
        except Exception as exc:
            from .analysis_jobs import AnalysisCancelled

            if isinstance(exc, AnalysisCancelled):
                raise
            add_gap(result, "candidate_analysis_failed", "local_candidate")
        attach_repository(state, provider, repository, local_model or candidate, mapping)
        return result
