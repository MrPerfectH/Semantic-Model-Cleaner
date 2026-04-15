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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = report_path.parent / f"{report_path.name}_backup_{ts}"
    shutil.copytree(report_path, backup_dir)
    return backup_dir


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
