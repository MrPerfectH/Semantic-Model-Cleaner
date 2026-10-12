"""Explicit deployment mappings and byte-comparable Report definitions (#120)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import analyzer
from .service_provider import ProbeError, guid, limitation, verify_report_binding


def comparable_report_digest(root):
    """Exact relative-path + byte equality of enhanced PBIR content/resources.

    Excludes definition.pbir (connection), .platform (logical identity), caches,
    diagram layout and unrelated files. Equality is not runtime equivalence.
    """
    digest = hashlib.sha256()
    files = []
    for directory in ("definition", "StaticResources"):
        base = root / directory
        if base.is_symlink():
            raise ProbeError("repository_symlinks_not_supported")
        if base.exists():
            for path in base.rglob("*"):
                if path.is_symlink():
                    raise ProbeError("repository_symlinks_not_supported")
                if path.is_file():
                    files.append(path)
    if not (root / "definition/report.json").is_file():
        raise ProbeError("repository_report_format_unsupported")
    total = 0
    for path in sorted(files):
        with path.open("rb") as stream:
            data = stream.read(64 * 1024 * 1024 - total + 1)
        total += len(data)
        if total > 64 * 1024 * 1024:
            raise ProbeError("repository_report_size_limit")
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def load_mapping(path, target, repository):
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = {key: getattr(target, key) for key in ("tenant_id", "workspace_id", "model_id")}
        if data.get("schema_version") != 1 or data.get("target") != expected:
            raise ProbeError("repository_mapping_target_mismatch")
        mappings, identities = {}, set()
        for row in data["reports"]:
            relative = Path(row["local_report"])
            local = repository / relative
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or local.is_symlink()
                or not local.resolve().is_relative_to(repository)
            ):
                raise ProbeError("repository_mapping_path_invalid")
            identity = (guid(row["workspace_id"]), guid(row["report_id"]))
            if str(local.resolve()) in mappings or identity in identities:
                raise ProbeError("repository_mapping_ambiguous")
            mappings[str(local.resolve())] = identity
            identities.add(identity)
        return mappings
    except (ValueError, KeyError, TypeError, OSError):
        raise ProbeError("repository_mapping_invalid") from None


def compare_repository(state, provider, repository, local_model, mapping=None):
    repository = Path(repository)
    if repository.is_symlink() or not repository.is_dir():
        raise ProbeError("repository_directory_required")
    repository = repository.resolve()
    local_model = Path(local_model).resolve()
    if not local_model.is_dir():
        raise ProbeError("repository_local_model_required")
    mappings = load_mapping(mapping, provider.target, repository)
    inventory = {
        (r["workspace_id"], r["report_id"]): r
        for r in state.result["reports"]
        if r["connection"] == "exact_model_id"
    }
    comparison = {
        "matched": [],
        "additional_published": [],
        "local_only": [],
        "unresolved": [],
        "excluded_local": [],
        "definition_comparison_rule": "enhanced-pbir-content-bytes/v1",
        "limitations": [
            "Additional means additional within inspected scope. Local-only means a mapped identity was not observed in that scope; it does not mean globally unpublished.",
            "Identity and definition equality are independent. Names and .platform logical IDs are never deployment identities.",
        ],
    }
    matched = set()
    inspected_paths = set()
    for report in analyzer.discover_reports([repository]):
        provider.progress("Comparing repository Reports")
        inspected_paths.add(str(report.resolve()))
        row = {
            "local_report": str(report.relative_to(repository)),
            "name": report.name,
            "identity_evidence": None,
            "definition_comparison": {"status": "not_checked"},
        }
        try:
            if report.is_symlink():
                raise ProbeError("repository_symlinks_not_supported")
            definition = json.loads((report / "definition.pbir").read_text(encoding="utf-8-sig"))
            reference = definition["datasetReference"]
            if "byPath" in reference and "byConnection" not in reference:
                if (report / reference["byPath"]["path"]).resolve() != local_model:
                    row["reason"] = "connected_to_other_local_model"
                    comparison["excluded_local"].append(row)
                    continue
            else:
                verify_report_binding(report, provider.target.model_id)
            identity = mappings.get(str(report.resolve()))
            if identity is None:
                row["reason"] = "no_explicit_deployment_identity"
                comparison["unresolved"].append(row)
                continue
            row.update(
                workspace_id=identity[0],
                report_id=identity[1],
                identity_evidence="explicit_target_bound_mapping",
            )
            remote = inventory.get(identity)
            if remote:
                matched.add(identity)
                if remote.get("_snapshot_path"):
                    local_hash = comparable_report_digest(report)
                    service_hash = comparable_report_digest(Path(remote["_snapshot_path"]))
                    row["definition_comparison"] = {
                        "status": "equal_content_bytes"
                        if local_hash == service_hash
                        else "different_content_bytes",
                        "local_sha256": local_hash,
                        "service_sha256": service_hash,
                        "connection_excluded": True,
                        "runtime_equivalence": "not_established",
                    }
                comparison["matched"].append(row)
            else:
                observed = next(
                    (
                        r
                        for r in state.result["reports"]
                        if (r["workspace_id"], r["report_id"]) == identity
                    ),
                    None,
                )
                if observed is not None:
                    row["reason"] = "mapped_report_connection_not_confirmed_for_target"
                    comparison["unresolved"].append(row)
                    continue
                ws = next(
                    (w for w in state.result["workspaces"] if w["workspace_id"] == identity[0]),
                    None,
                )
                if ws and ws["status"] in {"empty", "enumerated"}:
                    row["reason"] = "mapped_identity_not_observed_connected_in_scope"
                    comparison["local_only"].append(row)
                else:
                    row["reason"] = "mapped_workspace_not_fully_inspected"
                    comparison["unresolved"].append(row)
        except (ProbeError, ValueError, KeyError, OSError, TypeError) as exc:
            row["reason"] = (
                str(exc) if isinstance(exc, ProbeError) else "local_report_binding_unreadable"
            )
            comparison["unresolved"].append(row)
    for local in mappings.keys() - inspected_paths:
        comparison["unresolved"].append(
            {
                "local_report": str(Path(local).relative_to(repository)),
                "reason": "mapped_local_report_missing",
            }
        )
    for identity, remote in inventory.items():
        if identity not in matched:
            comparison["additional_published"].append(
                {
                    "workspace_id": identity[0],
                    "report_id": identity[1],
                    "name": remote["name"],
                    "service_url": remote["service_url"],
                    "status": remote["status"],
                    "identity_evidence": "no_confirmed_repository_identity_match_in_scope",
                }
            )
    if comparison["unresolved"]:
        state.result["analysis_limitations"].append(
            limitation("repository_identity_unresolved", "local_repository")
        )
        state.result["selected_scope_complete"] = False
        state.result["status"] = "incomplete"
    state.result["repository_comparison"] = comparison
    return comparison
