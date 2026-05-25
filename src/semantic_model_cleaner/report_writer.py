#!/usr/bin/env python3
"""Report definition write helpers for PBIR artifacts."""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import tmdl_writer


def create_backup(report_path: Path) -> Path:
    """Create a timestamped copy of the .Report directory."""
    for attempt in range(100):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{attempt}" if attempt else ""
        backup_dir = report_path.parent / f"{report_path.name}_backup_{ts}{suffix}"
        try:
            shutil.copytree(report_path, backup_dir)
            return backup_dir
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create a unique backup for {report_path}")


def _report_extensions_path(report_path: Path) -> Path:
    return report_path / "definition" / "reportExtensions.json"


def _load_report_extensions(report_path: Path) -> tuple[Path, dict]:
    report_extensions = _report_extensions_path(report_path)
    if not report_extensions.exists():
        return report_extensions, {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json",
            "name": "extension",
            "entities": [],
        }
    return report_extensions, json.loads(report_extensions.read_text(encoding="utf-8"))


def _save_report_extensions(report_extensions: Path, payload: dict) -> None:
    payload.setdefault("$schema", "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json")
    payload.setdefault("name", "extension")
    payload["entities"] = payload.get("entities", [])
    report_extensions.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_measure(payload: dict, entity_name: str, measure_name: str) -> tuple[dict | None, dict | None]:
    for entity in payload.get("entities", []):
        if str(entity.get("name", "")).casefold() != entity_name.casefold():
            continue
        for measure in entity.get("measures", []):
            if str(measure.get("name", "")).casefold() == measure_name.casefold():
                return entity, measure
    return None, None


def migrate_measure_to_model(
    *,
    model_path: Path,
    report_path: Path,
    entity_name: str,
    measure_name: str,
    target_table: str | None = None,
    target_name: str | None = None,
) -> dict:
    """Promote a report extension measure into the semantic model.

    This currently supports same-name promotion, which is the safe case for PBIR
    report-extension measures because report visuals already reference the
    entity/name pair. Once the extension definition is removed, those references
    resolve to the semantic model measure.
    """
    target_table = (target_table or entity_name).strip()
    target_name = (target_name or measure_name).strip()
    entity_name = entity_name.strip()
    measure_name = measure_name.strip()

    if not entity_name or not measure_name:
        return {"ok": False, "error": "Entity name and measure name are required"}

    if target_table.casefold() != entity_name.casefold() or target_name.casefold() != measure_name.casefold():
        return {
            "ok": False,
            "error": "Renaming during report-measure migration is not supported yet; target table/name must match the report measure.",
        }

    report_extensions, payload = _load_report_extensions(report_path)
    entity, measure = _find_measure(payload, entity_name, measure_name)
    if entity is None or measure is None:
        return {"ok": False, "error": f"Report measure '{entity_name}[{measure_name}]' was not found"}

    create_result = tmdl_writer.create_measure(
        model_path=model_path,
        table=target_table,
        name=target_name,
        dax_expression=str(measure.get("expression", "") or ""),
        display_folder=str(measure.get("displayFolder", "") or ""),
        format_string=str(measure.get("formatString", "") or ""),
        hidden=bool(measure.get("hidden", False)),
    )
    if not create_result.get("ok"):
        return create_result

    updated_reference_count = 0
    for current_entity in payload.get("entities", []):
        measures = current_entity.get("measures", [])
        if not isinstance(measures, list):
            continue
        for current_measure in measures:
            references = current_measure.get("references", {})
            if not isinstance(references, dict):
                continue
            reference_measures = references.get("measures", [])
            if not isinstance(reference_measures, list):
                continue
            for ref in reference_measures:
                if not isinstance(ref, dict):
                    continue
                if (
                    str(ref.get("entity", "")).casefold() == entity_name.casefold()
                    and str(ref.get("name", "")).casefold() == measure_name.casefold()
                ):
                    if ref.get("schema"):
                        updated_reference_count += 1
                    ref.pop("schema", None)

    entity_measures = entity.get("measures", [])
    entity["measures"] = [
        item for item in entity_measures
        if str(item.get("name", "")).casefold() != measure_name.casefold()
    ]
    payload["entities"] = [
        item for item in payload.get("entities", [])
        if item.get("measures") or str(item.get("name", "")).casefold() != entity_name.casefold()
    ]

    _save_report_extensions(report_extensions, payload)
    return {
        "ok": True,
        "action": "migrate_report_measure",
        "model_file": create_result.get("file"),
        "report_file": str(report_extensions),
        "table": entity_name,
        "name": measure_name,
        "updated_reference_count": updated_reference_count,
    }


def _split_top_level_query_ref(value: str) -> tuple[str, str] | None:
    depth_paren = 0
    depth_bracket = 0
    for idx, ch in enumerate(value):
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket = max(0, depth_bracket - 1)
        elif ch == "." and depth_paren == 0 and depth_bracket == 0:
            left = value[:idx].strip()
            right = value[idx + 1:].strip()
            if left and right:
                return left, right
            return None
    return None


def _move_lookup(moves: list[dict]) -> dict[tuple[str, str], str]:
    lookup = {}
    for move in moves:
        table = str(move.get("table", "") or "").strip()
        name = str(move.get("name", "") or "").strip()
        target_table = str(move.get("target_table", "") or "").strip()
        if table and name and target_table:
            lookup[(table.casefold(), name.casefold())] = target_table
    return lookup


def _reference_lookup(
    *,
    moves: list[dict] | None = None,
    table_renames: list[dict] | None = None,
    measure_renames: list[dict] | None = None,
) -> tuple[dict[str, str], dict[tuple[str, str], tuple[str, str]]]:
    table_lookup: dict[str, str] = {}
    measure_lookup: dict[tuple[str, str], tuple[str, str]] = {}

    for rename in table_renames or []:
        table = str(rename.get("table", "") or "").strip()
        target_table = str(rename.get("target_table", "") or "").strip()
        if table and target_table:
            table_lookup[table.casefold()] = target_table

    for move in moves or []:
        table = str(move.get("table", "") or "").strip()
        name = str(move.get("name", "") or "").strip()
        target_table = str(move.get("target_table", "") or "").strip()
        if table and name and target_table:
            measure_lookup[(table.casefold(), name.casefold())] = (target_table, name)

    for rename in measure_renames or []:
        table = str(rename.get("table", "") or "").strip()
        name = str(rename.get("name", "") or "").strip()
        target_name = str(rename.get("target_name", "") or "").strip()
        if table and name and target_name:
            resolved_table = table_lookup.get(table.casefold(), table)
            measure_lookup[(table.casefold(), name.casefold())] = (resolved_table, target_name)

    return table_lookup, measure_lookup


def _rewrite_query_ref(
    value: str,
    table_lookup: dict[str, str],
    measure_lookup: dict[tuple[str, str], tuple[str, str]],
) -> tuple[str, bool]:
    parts = _split_top_level_query_ref(value)
    if not parts:
        return value, False
    table, name = parts
    target_table = table_lookup.get(table.casefold(), table)
    target_name = name
    measure_target = measure_lookup.get((table.casefold(), name.casefold()))
    if measure_target:
        target_table, target_name = measure_target
    if target_table == table and target_name == name:
        return value, False
    return f"{target_table}.{target_name}", True


def _rewrite_model_refs_in_json(
    obj,
    table_lookup: dict[str, str],
    measure_lookup: dict[tuple[str, str], tuple[str, str]],
    updates: list[dict],
    path_parts: list[str] | None = None,
) -> None:
    if path_parts is None:
        path_parts = []

    if isinstance(obj, dict):
        measure = obj.get("Measure")
        if isinstance(measure, dict):
            prop = measure.get("Property")
            expr = measure.get("Expression", {})
            source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
            if isinstance(prop, str) and isinstance(source_ref, dict):
                entity = source_ref.get("Entity")
                if isinstance(entity, str):
                    target_table = table_lookup.get(entity.casefold(), entity)
                    target_name = prop
                    measure_target = measure_lookup.get((entity.casefold(), prop.casefold()))
                    if measure_target:
                        target_table, target_name = measure_target
                    if target_table != entity:
                        source_ref["Entity"] = target_table
                        updates.append({
                            "path": ".".join(path_parts + ["Measure", "Expression", "SourceRef", "Entity"]),
                            "from": entity,
                            "to": target_table,
                            "kind": "Measure.SourceRef.Entity",
                        })
                    if target_name != prop:
                        measure["Property"] = target_name
                        updates.append({
                            "path": ".".join(path_parts + ["Measure", "Property"]),
                            "from": prop,
                            "to": target_name,
                            "kind": "Measure.Property",
                        })

        for ref_type in ("Column", "HierarchyLevel"):
            ref = obj.get(ref_type)
            if not isinstance(ref, dict):
                continue
            expr = ref.get("Expression", {})
            if ref_type == "HierarchyLevel" and isinstance(expr, dict):
                expr = expr.get("Hierarchy", {}).get("Expression", {})
            source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
            if isinstance(source_ref, dict):
                entity = source_ref.get("Entity")
                target_table = table_lookup.get(str(entity).casefold(), entity) if isinstance(entity, str) else None
                if isinstance(entity, str) and target_table and target_table != entity:
                    source_ref["Entity"] = target_table
                    updates.append({
                        "path": ".".join(path_parts + [ref_type, "Expression", "SourceRef", "Entity"]),
                        "from": entity,
                        "to": target_table,
                        "kind": f"{ref_type}.SourceRef.Entity",
                    })

        for key in ("queryRef", "metadata"):
            value = obj.get(key)
            if isinstance(value, str):
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup)
                if changed:
                    obj[key] = new_value
                    updates.append({
                        "path": ".".join(path_parts + [key]),
                        "from": value,
                        "to": new_value,
                        "kind": key,
                    })

        query_refs = obj.get("queryRefs")
        if isinstance(query_refs, list):
            for idx, value in enumerate(query_refs):
                if not isinstance(value, str):
                    continue
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup)
                if changed:
                    query_refs[idx] = new_value
                    updates.append({
                        "path": ".".join(path_parts + ["queryRefs", f"[{idx}]"]),
                        "from": value,
                        "to": new_value,
                        "kind": "queryRefs",
                    })

        for key, value in obj.items():
            _rewrite_model_refs_in_json(value, table_lookup, measure_lookup, updates, path_parts + [key])
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _rewrite_model_refs_in_json(item, table_lookup, measure_lookup, updates, path_parts + [f"[{idx}]"])


def rewrite_measure_table_references(
    *,
    report_paths: list[Path],
    moves: list[dict],
    dry_run: bool = False,
) -> dict:
    """Rewrite selected PBIR report JSON references after model measures move tables."""
    return rewrite_model_reference_changes(report_paths=report_paths, moves=moves, dry_run=dry_run)


def rewrite_model_reference_changes(
    *,
    report_paths: list[Path],
    moves: list[dict] | None = None,
    table_renames: list[dict] | None = None,
    measure_renames: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Rewrite selected PBIR report JSON references for model moves/renames."""
    if not report_paths:
        return {"ok": False, "error": "No selected report paths were provided"}
    table_lookup, measure_lookup = _reference_lookup(
        moves=moves,
        table_renames=table_renames,
        measure_renames=measure_renames,
    )
    if not table_lookup and not measure_lookup:
        return {"ok": False, "error": "No valid model reference changes were provided"}

    updated_files = []
    warnings = []
    total_updates = 0

    for report_path in report_paths:
        definition_dir = report_path / "definition"
        if not report_path.exists():
            warnings.append(f"Report path not found: {report_path}")
            continue
        if not definition_dir.exists():
            warnings.append(f"Report definition folder not found: {definition_dir}")
            continue

        for json_file in sorted(definition_dir.rglob("*.json")):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                warnings.append(f"Skipped invalid JSON file: {json_file}")
                continue

            updates: list[dict] = []
            _rewrite_model_refs_in_json(payload, table_lookup, measure_lookup, updates)
            if not updates:
                continue

            total_updates += len(updates)
            updated_files.append({
                "file": str(json_file),
                "report": report_path.name,
                "reference_count": len(updates),
                "updates": updates,
            })
            if not dry_run:
                json_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "action": "rewrite_model_reference_changes",
        "dry_run": dry_run,
        "report_count": len(report_paths),
        "updated_file_count": len(updated_files),
        "updated_reference_count": total_updates,
        "updated_files": updated_files,
        "warnings": warnings,
    }


def _collect_query_refs(obj) -> set[str]:
    refs: set[str] = set()
    if isinstance(obj, dict):
        query_ref = obj.get("queryRef")
        if isinstance(query_ref, str) and query_ref:
            refs.add(query_ref)
        query_refs = obj.get("queryRefs")
        if isinstance(query_refs, list):
            refs |= {value for value in query_refs if isinstance(value, str) and value}
        for value in obj.values():
            refs |= _collect_query_refs(value)
    elif isinstance(obj, list):
        for item in obj:
            refs |= _collect_query_refs(item)
    return refs


def _path_tokens(path: str) -> list[str]:
    return [part for part in path.split(".") if part]


def _remove_path_index_entry(payload, prefix_path: str) -> bool:
    tokens = _path_tokens(prefix_path)
    if not tokens:
        return False
    cursor = payload
    for token in tokens[:-1]:
        if token.startswith("[") and token.endswith("]"):
            if not isinstance(cursor, list):
                return False
            idx = int(token[1:-1])
            if idx < 0 or idx >= len(cursor):
                return False
            cursor = cursor[idx]
        else:
            if not isinstance(cursor, dict) or token not in cursor:
                return False
            cursor = cursor[token]
    last = tokens[-1]
    if not (last.startswith("[") and last.endswith("]")):
        return False
    if not isinstance(cursor, list):
        return False
    idx = int(last[1:-1])
    if idx < 0 or idx >= len(cursor):
        return False
    cursor.pop(idx)
    return True


def _path_trailing_index(path: str) -> int:
    m = re.search(r"\[(\d+)\]$", path)
    return int(m.group(1)) if m else -1


def _remove_stale_selector_entries(obj, stale_values: set[str], live_query_refs: set[str], removed: list[dict], path_parts: list[str] | None = None) -> None:
    if path_parts is None:
        path_parts = []
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, list):
                new_items = []
                for idx, item in enumerate(value):
                    selector_value = None
                    if isinstance(item, dict):
                        selector = item.get("selector", {})
                        if isinstance(selector, dict):
                            metadata = selector.get("metadata")
                            if isinstance(metadata, str):
                                selector_value = metadata
                    if selector_value and selector_value in stale_values and selector_value not in live_query_refs:
                        removed.append({
                            "path": ".".join(path_parts + [key, f"[{idx}]"]),
                            "selector_value": selector_value,
                        })
                        continue
                    _remove_stale_selector_entries(item, stale_values, live_query_refs, removed, path_parts + [key, f"[{idx}]"])
                    new_items.append(item)
                obj[key] = new_items
            else:
                _remove_stale_selector_entries(value, stale_values, live_query_refs, removed, path_parts + [key])
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _remove_stale_selector_entries(item, stale_values, live_query_refs, removed, path_parts + [f"[{idx}]"])


def cleanup_stale_metadata_selectors(*, entries: list[dict]) -> dict:
    if not entries:
        return {"ok": False, "error": "No stale selector entries were provided"}

    selector_grouped: dict[Path, set[str]] = {}
    bookmark_entries: dict[Path, set[str]] = {}
    for entry in entries:
        report_path = Path(str(entry.get("report_path", "") or "")).resolve()
        artifact_path = str(entry.get("artifact_path", "") or "").strip()
        selector_value = str(entry.get("selector_value", "") or "").strip()
        source_path = str(entry.get("source_path", "") or "").strip()
        stale_kind = str(entry.get("stale_kind", "") or "").strip()
        if not report_path.exists():
            return {"ok": False, "error": f"Report path not found: {report_path}"}
        if not artifact_path:
            return {"ok": False, "error": "Each stale selector entry needs artifact_path"}
        target_file = (report_path / artifact_path).resolve()
        if stale_kind == "bookmark_projection_entry":
            if ".singleVisual.projections." not in source_path:
                return {"ok": False, "error": "Bookmark stale cleanup requires source_path for the projection entry"}
            m = re.search(r"(.*\.singleVisual\.projections\.[^.]+\.\[\d+\])", source_path)
            if not m:
                return {"ok": False, "error": f"Could not resolve bookmark projection path: {source_path}"}
            bookmark_entries.setdefault(target_file, set()).add(m.group(1))
        else:
            if not selector_value:
                return {"ok": False, "error": "Visual stale cleanup requires selector_value"}
            selector_grouped.setdefault(target_file, set()).add(selector_value)

    updated_files = []
    removed_entries = []
    for target_file, stale_values in selector_grouped.items():
        if not target_file.exists():
            return {"ok": False, "error": f"PBIR file not found: {target_file}"}
        payload = json.loads(target_file.read_text(encoding="utf-8"))
        live_query_refs = _collect_query_refs(payload.get("visual", {}).get("query", {}).get("queryState", {}))
        removed_for_file: list[dict] = []
        _remove_stale_selector_entries(payload, stale_values, live_query_refs, removed_for_file)
        if removed_for_file:
            target_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated_files.append(str(target_file))
            removed_entries.extend(
                {
                    "file": str(target_file),
                    "path": item["path"],
                    "selector_value": item["selector_value"],
                }
                for item in removed_for_file
            )

    for target_file, entry_paths in bookmark_entries.items():
        if not target_file.exists():
            return {"ok": False, "error": f"PBIR file not found: {target_file}"}
        payload = json.loads(target_file.read_text(encoding="utf-8"))
        removed_for_file = []
        for prefix_path in sorted(entry_paths, key=_path_trailing_index, reverse=True):
            if _remove_path_index_entry(payload, prefix_path):
                removed_for_file.append({
                    "path": prefix_path,
                    "selector_value": "",
                })
        if removed_for_file:
            target_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if str(target_file) not in updated_files:
                updated_files.append(str(target_file))
            removed_entries.extend(
                {
                    "file": str(target_file),
                    "path": item["path"],
                    "selector_value": item["selector_value"],
                }
                for item in removed_for_file
            )

    return {
        "ok": True,
        "action": "cleanup_stale_metadata_selectors",
        "updated_files": updated_files,
        "removed_count": len(removed_entries),
        "removed_entries": removed_entries,
    }
