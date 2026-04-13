#!/usr/bin/env python3
"""Report definition write helpers for PBIR artifacts."""

import json
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
