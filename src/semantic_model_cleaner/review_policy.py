"""Versioned repository review decisions and naming previews.

Decisions only affect eligible CI warning triage. They are never consulted by
cleanup_policy or change_plan authorization and cannot grant deletion permission.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from . import analyzer

SCHEMA_VERSION = "1.0"
POLICY_FILENAME = ".smc-policy.json"
SUPPRESSIBLE_RULES = {"SMC004", "SMC005", "SMC009"}
DISPOSITIONS = {"keep", "accept", "defer", "note"}


class PolicyError(ValueError):
    pass


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def policy_digest(policy: dict) -> str:
    return _hash({key: value for key, value in policy.items() if key != "digest"})


def empty_policy() -> dict:
    return {"schema_version": SCHEMA_VERSION, "decisions": [], "naming_rules": []}


def _text(value, label: str, *, allow_empty=False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > 4000:
        raise PolicyError(f"{label} must be a {'possibly empty ' if allow_empty else 'nonempty '}string of at most 4000 characters.")
    if any(ord(char) < 32 for char in value):
        raise PolicyError(f"{label} must not contain control characters.")
    return value


def validate_policy(policy: dict) -> dict:
    """Return a normalized copy with digest; raise PolicyError on invalid schema."""
    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError("Policy schema_version must be 1.0.")
    if set(policy) - {"schema_version", "decisions", "naming_rules", "digest"}:
        raise PolicyError("Policy contains unknown fields.")
    result = empty_policy()
    for key in ("decisions", "naming_rules"):
        value = policy.get(key, [])
        if not isinstance(value, list) or len(value) > (10000 if key == "decisions" else 100):
            raise PolicyError(f"{key} must be an array within the supported size limit.")
        result[key] = json.loads(json.dumps(value))
    seen = set()
    required = {"id", "rule_id", "finding_fingerprint", "evidence_fingerprint", "scope_fingerprint", "disposition", "reason", "owner", "expires_on"}
    for decision in result["decisions"]:
        if not isinstance(decision, dict) or set(decision) != required:
            raise PolicyError("Each decision must contain exactly id, rule_id, finding_fingerprint, evidence_fingerprint, scope_fingerprint, disposition, reason, owner, expires_on.")
        for key in ("id", "rule_id", "reason", "owner"):
            _text(decision[key], f"decision.{key}")
        if decision["id"] in seen:
            raise PolicyError("Decision IDs must be unique.")
        seen.add(decision["id"])
        for key in ("finding_fingerprint", "evidence_fingerprint", "scope_fingerprint"):
            if not isinstance(decision[key], str) or not re.fullmatch(r"[0-9a-f]{64}", decision[key]):
                raise PolicyError(f"decision.{key} must be a SHA-256 hex fingerprint.")
        if not isinstance(decision["disposition"], str) or decision["disposition"] not in DISPOSITIONS:
            raise PolicyError("Decision disposition must be keep, accept, defer, or note.")
        try:
            expiry = date.fromisoformat(decision["expires_on"])
            if expiry.isoformat() != decision["expires_on"]:
                raise ValueError()
        except (TypeError, ValueError):
            raise PolicyError("Decision expires_on must be YYYY-MM-DD.") from None
        identity = (decision["finding_fingerprint"], decision["scope_fingerprint"], decision["evidence_fingerprint"])
        if identity in seen:
            raise PolicyError("Only one decision is allowed per finding, evidence and scope; update the existing decision.")
        seen.add(identity)
    seen_rules = set()
    allowed = {"id", "item_type", "table_pattern", "find", "replace", "prefix", "suffix", "case"}
    for rule in result["naming_rules"]:
        if not isinstance(rule, dict) or set(rule) - allowed or not {"id", "item_type"} <= set(rule):
            raise PolicyError("Naming rules require id/item_type and only documented transform fields.")
        _text(rule["id"], "naming rule id")
        if rule["id"] in seen_rules:
            raise PolicyError("Naming rule IDs must be unique.")
        seen_rules.add(rule["id"])
        if not isinstance(rule["item_type"], str) or rule["item_type"] not in {"Table", "Measure", "Column"}:
            raise PolicyError("Naming item_type must be Table, Measure, or Column.")
        defaults = {"table_pattern": "*", "find": "", "replace": "", "prefix": "", "suffix": "", "case": "preserve"}
        for key, value in defaults.items():
            rule.setdefault(key, value)
            _text(rule[key], f"naming.{key}", allow_empty=key in {"find", "replace", "prefix", "suffix"})
        if rule["case"] not in {"preserve", "snake", "pascal", "title"}:
            raise PolicyError("Naming case must be preserve, snake, pascal, or title.")
        if rule["replace"] and not rule["find"]:
            raise PolicyError("Naming replace requires a nonempty literal find value.")
        if not (rule["find"] or rule["prefix"] or rule["suffix"] or rule["case"] != "preserve"):
            raise PolicyError("Naming rule must specify a transform.")
    result["digest"] = policy_digest(result)
    return result


def _policy_path(workspace: Path, path: Path | str | None) -> Path:
    root = Path(workspace).resolve()
    target = (root / (path or POLICY_FILENAME)).resolve()
    if not target.is_relative_to(root):
        raise PolicyError("Repository policy must remain inside the project directory.")
    if target.suffix.casefold() != ".json":
        raise PolicyError("Repository policy must be a JSON file.")
    if any(parent.name.casefold().endswith((".semanticmodel", ".report")) for parent in target.parents):
        raise PolicyError("Repository policy must be outside Semantic Model and Report artifacts.")
    return target


def load_policy(workspace: Path, path: Path | str | None = None) -> dict:
    target = _policy_path(workspace, path)
    if not target.exists():
        return validate_policy(empty_policy())
    try:
        return validate_policy(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"Cannot load repository policy: {exc}") from exc


@contextmanager
def _lock(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise PolicyError("Another policy update is active. Retry after it completes; inspect a leftover lock after interruption.") from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_policy(workspace: Path, policy: dict, path: Path | str | None = None, expected_digest: str | None = None) -> dict:
    normalized = validate_policy(policy)
    target = _policy_path(workspace, path)
    with _lock(target):
        current = load_policy(workspace, path)
        if target.exists() and expected_digest is None:
            raise PolicyError("An existing policy requires expected_digest; reload before saving.")
        if expected_digest is not None and current["digest"] != expected_digest:
            raise PolicyError("Policy changed since it was loaded; reload before saving.")
        descriptor, temporary = tempfile.mkstemp(prefix=".smc-policy-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(normalized, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return normalized


def scope_fingerprint(scope: dict) -> str:
    return _hash({"model": scope.get("model"), "reports": sorted(scope.get("reports", []))})


def evidence_fingerprint(workspace: Path, finding: dict) -> str:
    path = Path(workspace) / finding.get("path", "")
    evidence = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return _hash({"finding": finding["fingerprint"], "source_content": evidence})


def annotate_findings(workspace: Path, findings: list[dict], scope: dict, policy: dict, *, today: date | None = None) -> list[dict]:
    """Return annotated copies; only eligible warning decisions suppress CI triage."""
    policy = validate_policy(policy)
    today = today or datetime.now(timezone.utc).date()
    scope_hash = scope_fingerprint(scope)
    result = []
    for finding in findings:
        row = dict(finding)
        row["evidence_fingerprint"] = evidence_fingerprint(workspace, row)
        row["scope_fingerprint"] = scope_hash
        row["review_decision"] = None
        candidates = [d for d in policy["decisions"] if d["finding_fingerprint"] == row["fingerprint"] and d["rule_id"] == row["rule_id"]]
        matched = [d for d in candidates if d["scope_fingerprint"] == scope_hash and d["evidence_fingerprint"] == row["evidence_fingerprint"]]
        row["review_status"] = "stale" if candidates and not matched else "unreviewed"
        if matched:
            decision = matched[0]
            row["review_decision"] = dict(decision)
            expired = date.fromisoformat(decision["expires_on"]) < today
            eligible = row["severity"] == "warning" and row["rule_id"] in SUPPRESSIBLE_RULES
            suppresses = not expired and eligible and decision["disposition"] != "note"
            row["review_status"] = "expired" if expired else "accepted" if suppresses else "noted"
            row["suppressed"] = bool(row.get("suppressed")) or suppresses
        result.append(row)
    return result


def add_decision(workspace: Path, finding: dict, scope: dict, *, disposition: str, reason: str,
                 owner: str, expires_on: str, path: Path | str | None = None) -> dict:
    policy = load_policy(workspace, path)
    digest = policy["digest"]
    # Rebuild canonical evidence from the explicit scope; do not persist a
    # fabricated or outdated client finding merely because its hashes are shaped
    # correctly. The current policy is used for custom-path naming findings too.
    from .ci import run_check
    root = Path(workspace).resolve()
    _, checked = run_check(root, model_path=root / scope.get("model", ""),
                          report_paths=[root / path for path in scope.get("reports", [])], policy=policy)
    current = next((row for row in checked.get("findings", []) if row["fingerprint"] == finding.get("fingerprint")), None)
    if checked.get("errors") or current is None or current["rule_id"] != finding.get("rule_id"):
        raise PolicyError("Finding is not present in the current scope; refresh review findings.")
    evidence = current["evidence_fingerprint"]
    if finding.get("evidence_fingerprint") != evidence or finding.get("scope_fingerprint") != scope_fingerprint(scope):
        raise PolicyError("Finding evidence or scope changed; refresh review findings before saving.")
    policy["decisions"] = [d for d in policy["decisions"] if not (
        d["finding_fingerprint"] == finding["fingerprint"] and d["scope_fingerprint"] == scope_fingerprint(scope))]
    policy["decisions"].append({"id": uuid.uuid4().hex, "rule_id": finding["rule_id"],
        "finding_fingerprint": finding["fingerprint"], "evidence_fingerprint": evidence,
        "scope_fingerprint": scope_fingerprint(scope), "disposition": disposition,
        "reason": reason, "owner": owner, "expires_on": expires_on})
    return save_policy(workspace, policy, path, expected_digest=digest)


def remove_decision(workspace: Path, decision_id: str, path: Path | str | None = None) -> dict:
    policy = load_policy(workspace, path)
    digest = policy["digest"]
    remaining = [d for d in policy["decisions"] if d["id"] != decision_id]
    if len(remaining) == len(policy["decisions"]):
        raise PolicyError("Decision ID was not found.")
    policy["decisions"] = remaining
    return save_policy(workspace, policy, path, expected_digest=digest)


def review_findings(workspace: Path, model_path: Path, report_paths: list[Path]) -> dict:
    """Canonical UI result: the same versioned envelope returned by smc check."""
    from .ci import run_check
    _, result = run_check(Path(workspace), model_path=Path(model_path), report_paths=report_paths)
    return result


def _transform(name: str, rule: dict) -> str:
    """Keep exact affixes once, applying case/replacement to the inner name.

    Literal replacement itself may be intentionally non-idempotent (a -> aa).
    Affixes are case-sensitive and are not included in case conversion.
    """
    value = name
    if rule["prefix"] and value.startswith(rule["prefix"]):
        value = value[len(rule["prefix"]):]
    if rule["suffix"] and value.endswith(rule["suffix"]):
        value = value[:-len(rule["suffix"])]
    value = value.replace(rule["find"], rule["replace"]) if rule["find"] else value
    if rule["case"] != "preserve":
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        words = [word for word in re.split(r"[\s_-]+", value) if word]
        if rule["case"] == "snake":
            value = "_".join(word.lower() for word in words)
        elif rule["case"] == "pascal":
            value = "".join(word[:1].upper() + word[1:].lower() for word in words)
        else:
            value = " ".join(word[:1].upper() + word[1:].lower() for word in words)
    return rule["prefix"] + value + rule["suffix"]


def naming_proposals(model_path: Path, policy: dict) -> dict:
    """Pure suggestion construction. No writers or project mutations."""
    policy = validate_policy(policy)
    items = analyzer.parse_model_items(Path(model_path))
    if not items:
        raise PolicyError("Naming rules require a nonempty TMDL semantic model.")
    objects = [("Table", table, table) for table in sorted({item.table for item in items})]
    objects += [("Measure" if item.item_type == "Measure" else "Column", item.table, item.name) for item in items]
    proposals, conflicts, final = [], [], []
    for item_type, table, name in objects:
        target, applied = name, []
        for rule in policy["naming_rules"]:
            if rule["item_type"] == item_type and fnmatch.fnmatchcase(table.casefold(), rule["table_pattern"].casefold()):
                updated = _transform(target, rule)
                if updated != target:
                    applied.append(rule["id"])
                    target = updated
        repeated = target
        for rule in policy["naming_rules"]:
            if rule["item_type"] == item_type and fnmatch.fnmatchcase(table.casefold(), rule["table_pattern"].casefold()):
                repeated = _transform(repeated, rule)
        if repeated != target:
            conflicts.append(f"Naming rules for {table}[{name}] do not stabilize after one pass; simplify overlapping replacements.")
        final.append((item_type, table, name, target))
        if target != name:
            proposals.append({"item_type": item_type, "table": table, "name": name, "target_name": target, "rule_ids": applied})
        if not target.strip() or target != target.strip() or len(target) > 512 or any(ord(c) < 32 for c in target):
            conflicts.append(f"Invalid target name for {table}[{name}].")
    groups = {}
    table_names = {name: target for kind, _, name, target in final if kind == "Table"}
    for kind, table, name, target in final:
        namespace = "tables" if kind == "Table" else "measures" if kind == "Measure" else "columns:" + table_names[table].casefold()
        key = (namespace, target.casefold())
        if key in groups:
            conflicts.append(f"Naming collision: {groups[key]} and {table}[{name}] would both be {target}.")
        groups[key] = f"{table}[{name}]"
    operation = {"kind": "rename", "table_renames": [], "measure_renames": [], "column_renames": []}
    for proposal in proposals:
        kind, table, name, target = (proposal[key] for key in ("item_type", "table", "name", "target_name"))
        if kind == "Table":
            operation["table_renames"].append({"table": name, "target_table": target})
        else:
            operation["measure_renames" if kind == "Measure" else "column_renames"].append({"table": table, "name": name, "target_name": target})
    return {"ok": not conflicts, "proposals": proposals, "conflicts": sorted(set(conflicts)),
            "operations": [operation] if proposals and not conflicts else []}


def naming_preview(workspace: Path, model_path: Path, report_paths: list[Path], policy: dict | None = None) -> dict:
    """Build an immutable existing change_plan preview, never apply it."""
    from .change_plan import create_plan
    result = naming_proposals(model_path, policy if policy is not None else load_policy(workspace))
    result["plan"] = None
    if not result["ok"] or not result["operations"]:
        return result
    for report in report_paths:
        binding = analyzer.report_binding_status(Path(report), Path(model_path))
        if binding["status"] not in analyzer.BOUND_REPORT_STATUSES:
            raise PolicyError(f"Naming preview requires bound report scope: {binding['status']}.")
    result["plan"] = create_plan(model_path, report_paths, result["operations"])
    return result
