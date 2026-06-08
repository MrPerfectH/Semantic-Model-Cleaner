#!/usr/bin/env python3
"""Report definition write helpers for PBIR artifacts."""

import json
import re
import shutil
from functools import cmp_to_key
from datetime import datetime
from pathlib import Path

from . import file_transaction, tmdl_writer


_DECLARED_SCHEMA_REQUIRED_FIELDS = (
    ("/definition/visualContainer/", ("$schema", "name", "position")),
    ("/definition/page/", ("$schema", "name", "displayName", "displayOption")),
    ("/definition/reportExtension/", ("$schema", "name")),
    ("/definition/bookmark/", ("$schema", "displayName", "explorationState", "name")),
    ("/definition/bookmarksMetadata/", ("$schema", "items")),
    ("/definition/pagesMetadata/", ("$schema",)),
    ("/definition/versionMetadata/", ("$schema", "version")),
    ("/definition/visualContainerMobileState/", ("$schema", "position")),
)


_REPORT_EXTENSION_TMDL_DATA_TYPES = {
    "Binary": "binary",
    "Boolean": "boolean",
    "Date": "dateTime",
    "DateTime": "dateTime",
    "Decimal": "decimal",
    "Double": "double",
    "Integer": "int64",
    "Text": "string",
    "Variant": "variant",
}


def _declared_report_required_fields(schema: str) -> tuple[str, ...] | None:
    match = re.search(r"/definition/report/(\d+)\.", schema)
    if not match:
        return None
    if match.group(1) == "1":
        return "$schema", "layoutOptimization", "themeCollection"
    return "$schema", "themeCollection"


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


def _declared_schema_errors(payload, json_file: Path) -> list[str]:
    if not isinstance(payload, dict):
        return ["PBIR JSON payload must be an object"]

    schema = str(payload.get("$schema", "") or "")
    if not schema:
        return []

    errors: list[str] = []
    report_required_fields = _declared_report_required_fields(schema)
    if report_required_fields:
        for field in report_required_fields:
            if field not in payload:
                errors.append(f"{json_file} declares {schema} but is missing required field '{field}'")
        return errors

    for schema_fragment, required_fields in _DECLARED_SCHEMA_REQUIRED_FIELDS:
        if schema_fragment not in schema:
            continue
        for field in required_fields:
            if field not in payload:
                errors.append(f"{json_file} declares {schema} but is missing required field '{field}'")
        break
    return errors


def validate_pbir_json_file(json_file: Path, payload=None) -> dict:
    """Offline PBIR validation baseline for changed JSON files."""
    try:
        if payload is None:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "errors": [{"file": str(json_file), "message": f"Invalid JSON: {exc}"}],
        }

    errors = _declared_schema_errors(payload, json_file)
    return {
        "ok": not errors,
        "errors": [{"file": str(json_file), "message": message} for message in errors],
    }


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
    validation = validate_pbir_json_file(report_extensions, payload)
    if not validation["ok"]:
        error = "; ".join(err["message"] for err in validation["errors"])
        raise ValueError(f"PBIR validation failed: {error}")
    report_extensions.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_measure(payload: dict, entity_name: str, measure_name: str) -> tuple[dict | None, dict | None]:
    for entity in payload.get("entities", []):
        if str(entity.get("name", "")).casefold() != entity_name.casefold():
            continue
        for measure in entity.get("measures", []):
            if str(measure.get("name", "")).casefold() == measure_name.casefold():
                return entity, measure
    return None, None


def _report_extension_string(measure: dict, field: str) -> str:
    value = measure.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return ""


def _report_extension_data_type(value: str) -> str:
    for report_value, tmdl_value in _REPORT_EXTENSION_TMDL_DATA_TYPES.items():
        if report_value.casefold() == value.casefold():
            return tmdl_value
    return ""


def _report_measure_promotion_metadata(measure: dict) -> tuple[dict, list[str], list[dict[str, str]]]:
    create_kwargs: dict = {}
    preserved_metadata: list[str] = []
    unpreserved_metadata: list[dict[str, str]] = []

    if _report_extension_string(measure, "expression"):
        preserved_metadata.append("expression")

    report_data_type = _report_extension_string(measure, "dataType")
    if report_data_type:
        tmdl_data_type = _report_extension_data_type(report_data_type)
        if tmdl_data_type:
            create_kwargs["data_type"] = tmdl_data_type
            preserved_metadata.append("dataType")
        else:
            unpreserved_metadata.append({
                "field": "dataType",
                "reason": (
                    f"Report extension dataType '{report_data_type}' does not have a supported "
                    "TMDL measure dataType mapping."
                ),
            })

    for report_field, create_field in (
        ("dataCategory", "data_category"),
        ("description", "description"),
        ("displayFolder", "display_folder"),
        ("formatString", "format_string"),
    ):
        value = _report_extension_string(measure, report_field)
        if value:
            create_kwargs[create_field] = value
            preserved_metadata.append(report_field)

    if isinstance(measure.get("hidden"), bool):
        create_kwargs["hidden"] = measure["hidden"]
        preserved_metadata.append("hidden")

    annotations = measure.get("annotations")
    promoted_annotations = []
    if isinstance(annotations, list):
        for idx, annotation in enumerate(annotations):
            if not isinstance(annotation, dict):
                unpreserved_metadata.append({
                    "field": f"annotations[{idx}]",
                    "reason": "Report extension annotation is not an object.",
                })
                continue
            name = _report_extension_string(annotation, "name")
            value = _report_extension_string(annotation, "value")
            if not name or not value:
                unpreserved_metadata.append({
                    "field": f"annotations[{idx}]",
                    "reason": "Report extension annotation must include non-empty name and value strings.",
                })
                continue
            if "\n" in name or "\n" in value:
                unpreserved_metadata.append({
                    "field": f"annotations[{idx}]",
                    "reason": "Multiline report extension annotations are not promoted to TMDL.",
                })
                continue
            promoted_annotations.append({"name": name, "value": value})
    elif annotations is not None:
        unpreserved_metadata.append({
            "field": "annotations",
            "reason": "Report extension annotations must be an array.",
        })

    if promoted_annotations:
        create_kwargs["annotations"] = promoted_annotations
        preserved_metadata.append("annotations")

    if "measureTemplate" in measure:
        unpreserved_metadata.append({
            "field": "measureTemplate",
            "reason": "Report extension measure templates are creation metadata and do not have a TMDL measure equivalent.",
        })

    return create_kwargs, preserved_metadata, unpreserved_metadata


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

    metadata_kwargs, preserved_metadata, unpreserved_metadata = _report_measure_promotion_metadata(measure)
    transaction_roots = [model_path / "definition", report_path / "definition"]
    snapshot = file_transaction.snapshot_artifact_files(transaction_roots)
    try:
        create_result = tmdl_writer.create_measure(
            model_path=model_path,
            table=target_table,
            name=target_name,
            dax_expression=str(measure.get("expression", "") or ""),
            **metadata_kwargs,
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
    except Exception as exc:
        rollback = file_transaction.restore_artifact_files(transaction_roots, snapshot)
        return {
            "ok": False,
            "error": str(exc),
            "rolled_back": rollback["ok"],
            "rollback": rollback,
        }
    return {
        "ok": True,
        "action": "migrate_report_measure",
        "model_file": create_result.get("file"),
        "report_file": str(report_extensions),
        "table": entity_name,
        "name": measure_name,
        "updated_reference_count": updated_reference_count,
        "preserved_metadata": preserved_metadata,
        "unpreserved_metadata": unpreserved_metadata,
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
    aliases: dict[str, dict],
) -> tuple[str, bool]:
    wrapper = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\((.+)\)", value)
    if wrapper:
        new_inner, changed = _rewrite_query_ref(wrapper.group(2), table_lookup, measure_lookup, aliases)
        if changed:
            return f"{wrapper.group(1)}({new_inner})", True
        return value, False

    parts = _split_top_level_query_ref(value)
    if not parts:
        return value, False
    table_or_alias, name = parts
    alias = aliases.get(table_or_alias.casefold())
    table = str(alias.get("original_entity", alias["entity"])) if alias else table_or_alias
    target_table = table_lookup.get(table.casefold(), table)
    target_name = name
    measure_target = measure_lookup.get((table.casefold(), name.casefold()))
    if measure_target:
        target_table, target_name = measure_target
    output_table = table_or_alias if alias else target_table
    if output_table == table_or_alias and target_name == name:
        return value, False
    return f"{output_table}.{target_name}", True


def _rewrite_dax_table_refs(value: str, table_lookup: dict[str, str]) -> tuple[str, bool]:
    new_value = value
    for table, target_table in table_lookup.items():
        new_value, _ = tmdl_writer._rewrite_table_name_in_text(new_value, table, target_table)
    return new_value, new_value != value


def _collect_source_aliases(obj, path_parts: list[str] | None = None) -> dict[str, dict]:
    if path_parts is None:
        path_parts = []
    aliases: dict[str, dict] = {}
    if isinstance(obj, dict):
        from_entries = obj.get("From")
        if isinstance(from_entries, list):
            for idx, source in enumerate(from_entries):
                if not isinstance(source, dict):
                    continue
                alias_name = source.get("Name")
                entity = source.get("Entity")
                if isinstance(alias_name, str) and isinstance(entity, str):
                    aliases[alias_name.casefold()] = {
                        "name": alias_name,
                        "entity": entity,
                        "original_entity": entity,
                        "source": source,
                        "entity_path": path_parts + ["From", f"[{idx}]", "Entity"],
                    }
        for key, value in obj.items():
            aliases.update(_collect_source_aliases(value, path_parts + [key]))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            aliases.update(_collect_source_aliases(item, path_parts + [f"[{idx}]"]))
    return aliases


def _rewrite_model_refs_in_json(
    obj,
    table_lookup: dict[str, str],
    measure_lookup: dict[tuple[str, str], tuple[str, str]],
    updates: list[dict],
    path_parts: list[str] | None = None,
    aliases: dict[str, dict] | None = None,
) -> None:
    if path_parts is None:
        path_parts = []
    if aliases is None:
        aliases = {}

    if isinstance(obj, dict):
        local_aliases = dict(aliases)
        from_entries = obj.get("From")
        if isinstance(from_entries, list):
            for idx, source in enumerate(from_entries):
                if not isinstance(source, dict):
                    continue
                alias_name = source.get("Name")
                entity = source.get("Entity")
                if not (isinstance(alias_name, str) and isinstance(entity, str)):
                    continue
                target_table = table_lookup.get(entity.casefold(), entity)
                if target_table != entity:
                    source["Entity"] = target_table
                    updates.append({
                        "path": ".".join(path_parts + ["From", f"[{idx}]", "Entity"]),
                        "from": entity,
                        "to": target_table,
                        "kind": "From.Entity",
                    })
                alias_info = local_aliases.get(alias_name.casefold(), {})
                alias_info.update({
                    "name": alias_name,
                    "entity": source["Entity"],
                    "original_entity": alias_info.get("original_entity", entity),
                    "source": source,
                    "entity_path": path_parts + ["From", f"[{idx}]", "Entity"],
                })
                local_aliases[alias_name.casefold()] = alias_info

        measure = obj.get("Measure")
        if isinstance(measure, dict):
            prop = measure.get("Property")
            expr = measure.get("Expression", {})
            source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
            if isinstance(prop, str) and isinstance(source_ref, dict):
                entity = source_ref.get("Entity")
                source_alias = source_ref.get("Source")
                alias = local_aliases.get(source_alias.casefold()) if isinstance(source_alias, str) else None
                resolved_entity = entity if isinstance(entity, str) else (
                    str(alias.get("original_entity", alias["entity"])) if alias else None
                )
                if isinstance(resolved_entity, str):
                    target_table = table_lookup.get(resolved_entity.casefold(), resolved_entity)
                    target_name = prop
                    measure_target = measure_lookup.get((resolved_entity.casefold(), prop.casefold()))
                    if measure_target:
                        target_table, target_name = measure_target
                    if isinstance(entity, str) and target_table != entity:
                        source_ref["Entity"] = target_table
                        updates.append({
                            "path": ".".join(path_parts + ["Measure", "Expression", "SourceRef", "Entity"]),
                            "from": entity,
                            "to": target_table,
                            "kind": "Measure.SourceRef.Entity",
                        })
                    elif alias and target_table != alias["source"].get("Entity"):
                        old_entity = alias["source"].get("Entity")
                        alias["source"]["Entity"] = target_table
                        alias["entity"] = target_table
                        updates.append({
                            "path": ".".join(alias["entity_path"]),
                            "from": old_entity,
                            "to": target_table,
                            "kind": "From.Entity",
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
                source_alias = source_ref.get("Source")
                alias = local_aliases.get(source_alias.casefold()) if isinstance(source_alias, str) else None
                resolved_entity = entity if isinstance(entity, str) else (
                    str(alias.get("original_entity", alias["entity"])) if alias else None
                )
                target_table = table_lookup.get(str(resolved_entity).casefold(), resolved_entity) if isinstance(resolved_entity, str) else None
                if isinstance(entity, str) and target_table and target_table != entity:
                    source_ref["Entity"] = target_table
                    updates.append({
                        "path": ".".join(path_parts + [ref_type, "Expression", "SourceRef", "Entity"]),
                        "from": entity,
                        "to": target_table,
                        "kind": f"{ref_type}.SourceRef.Entity",
                    })
                elif alias and target_table and target_table != alias["source"].get("Entity"):
                    old_entity = alias["source"].get("Entity")
                    alias["source"]["Entity"] = target_table
                    alias["entity"] = target_table
                    updates.append({
                        "path": ".".join(alias["entity_path"]),
                        "from": old_entity,
                        "to": target_table,
                        "kind": "From.Entity",
                    })

        for key in ("queryRef", "metadata"):
            value = obj.get(key)
            if isinstance(value, str):
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup, local_aliases)
                if changed:
                    obj[key] = new_value
                    updates.append({
                        "path": ".".join(path_parts + [key]),
                        "from": value,
                        "to": new_value,
                        "kind": key,
                    })

        entity = obj.get("entity")
        if isinstance(entity, str) and isinstance(obj.get("name"), str):
            target_table = table_lookup.get(entity.casefold())
            if target_table and target_table != entity:
                obj["entity"] = target_table
                updates.append({
                    "path": ".".join(path_parts + ["entity"]),
                    "from": entity,
                    "to": target_table,
                    "kind": "entity",
                })

        entity_name = obj.get("name")
        if isinstance(entity_name, str) and isinstance(obj.get("measures"), list):
            target_table = table_lookup.get(entity_name.casefold())
            if target_table and target_table != entity_name:
                obj["name"] = target_table
                updates.append({
                    "path": ".".join(path_parts + ["name"]),
                    "from": entity_name,
                    "to": target_table,
                    "kind": "ReportExtension.EntityName",
                })

        for dax_key in ("expression",):
            value = obj.get(dax_key)
            if isinstance(value, str):
                new_value, changed = _rewrite_dax_table_refs(value, table_lookup)
                if changed:
                    obj[dax_key] = new_value
                    updates.append({
                        "path": ".".join(path_parts + [dax_key]),
                        "from": value,
                        "to": new_value,
                        "kind": "DAX.TableRef",
                    })

        query_refs = obj.get("queryRefs")
        if isinstance(query_refs, list):
            for idx, value in enumerate(query_refs):
                if not isinstance(value, str):
                    continue
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup, local_aliases)
                if changed:
                    query_refs[idx] = new_value
                    updates.append({
                        "path": ".".join(path_parts + ["queryRefs", f"[{idx}]"]),
                        "from": value,
                        "to": new_value,
                        "kind": "queryRefs",
                    })

        for key, value in obj.items():
            _rewrite_model_refs_in_json(value, table_lookup, measure_lookup, updates, path_parts + [key], local_aliases)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _rewrite_model_refs_in_json(item, table_lookup, measure_lookup, updates, path_parts + [f"[{idx}]"], aliases)


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
    pending_writes: list[tuple[Path, dict]] = []

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
            _rewrite_model_refs_in_json(
                payload,
                table_lookup,
                measure_lookup,
                updates,
                aliases=_collect_source_aliases(payload),
            )
            if not updates:
                continue

            validation = validate_pbir_json_file(json_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                    "warnings": warnings,
                }

            total_updates += len(updates)
            updated_files.append({
                "file": str(json_file),
                "report": report_path.name,
                "reference_count": len(updates),
                "updates": updates,
            })
            pending_writes.append((json_file, payload))

    if not dry_run and pending_writes:
        roots = [report_path / "definition" for report_path in report_paths]
        snapshot = file_transaction.snapshot_artifact_files(roots, suffixes=(".json",))
        try:
            for json_file, payload in pending_writes:
                json_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            rollback = file_transaction.restore_artifact_files(roots, snapshot, suffixes=(".json",))
            return {
                "ok": False,
                "error": f"PBIR write failed: {exc}",
                "rolled_back": rollback["ok"],
                "rollback": rollback,
                "updated_files": updated_files,
                "warnings": warnings,
            }

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


def _path_value(payload, path: str):
    cursor = payload
    for token in _path_tokens(path):
        if token.startswith("[") and token.endswith("]"):
            if not isinstance(cursor, list):
                return None
            idx = int(token[1:-1])
            if idx < 0 or idx >= len(cursor):
                return None
            cursor = cursor[idx]
        else:
            if not isinstance(cursor, dict) or token not in cursor:
                return None
            cursor = cursor[token]
    return cursor


def _delete_path(payload, path: str) -> bool:
    tokens = _path_tokens(path)
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
    if last.startswith("[") and last.endswith("]"):
        if not isinstance(cursor, list):
            return False
        idx = int(last[1:-1])
        if idx < 0 or idx >= len(cursor):
            return False
        cursor.pop(idx)
        return True
    if isinstance(cursor, dict) and last in cursor:
        del cursor[last]
        return True
    return False


def _compare_delete_paths_desc(left: str, right: str) -> int:
    """Order JSON deletes so list indexes are removed from highest to lowest."""
    left_tokens = _path_tokens(left)
    right_tokens = _path_tokens(right)
    for left_token, right_token in zip(left_tokens, right_tokens):
        left_is_idx = left_token.startswith("[") and left_token.endswith("]")
        right_is_idx = right_token.startswith("[") and right_token.endswith("]")
        if left_is_idx and right_is_idx:
            left_idx = int(left_token[1:-1])
            right_idx = int(right_token[1:-1])
            if left_idx != right_idx:
                return -1 if left_idx > right_idx else 1
        elif left_token != right_token:
            return -1 if left_token > right_token else 1
    if len(left_tokens) == len(right_tokens):
        return 0
    return -1 if len(left_tokens) > len(right_tokens) else 1


def _sorted_delete_paths(paths: set[str] | list[str]) -> list[str]:
    return sorted(paths, key=cmp_to_key(_compare_delete_paths_desc))


def _sort_report_issue_actions(entries: list[dict]) -> list[dict]:
    remove_entries = []
    other_entries = []
    for idx, entry in enumerate(entries):
        action = str(entry.get("action", "") or "").strip()
        if action == "remove":
            source_path = str(entry.get("source_path", "") or "").strip()
            remove_entries.append((_reference_removal_path(source_path), idx, entry))
        else:
            other_entries.append(entry)

    remove_entries.sort(key=cmp_to_key(lambda left, right: _compare_delete_paths_desc(left[0], right[0]) or left[1] - right[1]))
    return [entry for _, _, entry in remove_entries] + other_entries


def _reference_removal_path(source_path: str) -> str:
    if "filterConfig.filters." in source_path:
        match = re.search(r"(.*filterConfig\.filters\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".projections." in source_path:
        match = re.search(r"(.*\.projections(?:\.[^.]+)?\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".sortDefinition.sort." in source_path:
        match = re.search(r"(.*\.sortDefinition\.sort\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".selector.metadata" in source_path:
        match = re.search(r"(.*\.\[\d+\])\.selector\.metadata", source_path)
        if match:
            return match.group(1)
    if ".properties." in source_path:
        match = re.search(r"(.*\.properties\.[^.]+)", source_path)
        if match:
            return match.group(1)
    return source_path


def _formatting_rule_removal_path(source_path: str) -> str:
    match = re.search(r"(.*\.objects\.[^.]+\.\[\d+\])\.properties\.[^.]+", source_path)
    if match:
        return match.group(1)
    return _reference_removal_path(source_path)


def _reference_update_scope_path(source_path: str) -> str:
    if "filterConfig.filters." in source_path:
        match = re.search(r"(.*filterConfig\.filters\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".projections." in source_path:
        match = re.search(r"(.*\.projections(?:\.[^.]+)?\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".sortDefinition.sort." in source_path:
        match = re.search(r"(.*\.sortDefinition\.sort\.\[\d+\])", source_path)
        if match:
            return match.group(1)
    if ".properties." in source_path:
        match = re.search(r"(.*\.properties\.[^.]+)", source_path)
        if match:
            return match.group(1)
    return source_path


def _source_alias_entries(obj: dict) -> dict[str, dict]:
    aliases = {}
    from_clause = obj.get("From")
    if not isinstance(from_clause, list):
        return aliases
    for entry in from_clause:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        entity = entry.get("Entity")
        if isinstance(name, str) and isinstance(entity, str) and name and entity:
            aliases[name] = entry
    return aliases


def _source_ref_table(source_ref: dict, aliases: dict[str, dict]) -> str:
    if not isinstance(source_ref, dict):
        return ""
    entity = source_ref.get("Entity")
    if isinstance(entity, str) and entity:
        return entity
    source = source_ref.get("Source")
    alias_entry = aliases.get(source) if isinstance(source, str) else None
    entity = alias_entry.get("Entity") if isinstance(alias_entry, dict) else ""
    return entity if isinstance(entity, str) else ""


def _ref_object_matches(ref: dict, old_table: str, old_name: str, aliases: dict[str, dict] | None = None) -> bool:
    aliases = aliases or {}
    expr = ref.get("Expression", {})
    if isinstance(expr, dict) and "Hierarchy" in expr:
        expr = expr.get("Hierarchy", {}).get("Expression", {})
    source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
    prop = ref.get("Property", ref.get("Hierarchy", ""))
    return (
        isinstance(source_ref, dict)
        and _source_ref_table(source_ref, aliases).casefold() == old_table.casefold()
        and str(prop).casefold() == old_name.casefold()
    )


def _replace_ref_object(ref: dict, target_table: str, target_name: str, aliases: dict[str, dict] | None = None) -> int:
    aliases = aliases or {}
    expr = ref.get("Expression", {})
    if isinstance(expr, dict) and "Hierarchy" in expr:
        expr = expr.get("Hierarchy", {}).get("Expression", {})
    source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
    changed = 0
    if isinstance(source_ref, dict) and source_ref.get("Entity") != target_table:
        if "Entity" in source_ref:
            source_ref["Entity"] = target_table
            changed += 1
        elif isinstance(source_ref.get("Source"), str):
            alias_entry = aliases.get(source_ref.get("Source"))
            if isinstance(alias_entry, dict) and alias_entry.get("Entity") != target_table:
                alias_entry["Entity"] = target_table
                changed += 1
    if "Property" in ref and ref.get("Property") != target_name:
        ref["Property"] = target_name
        changed += 1
    if "Hierarchy" in ref and ref.get("Hierarchy") != target_name:
        ref["Hierarchy"] = target_name
        changed += 1
    return changed


def _replace_reference_in_obj(
    obj,
    old_table: str,
    old_name: str,
    target_table: str,
    target_name: str,
    aliases: dict[str, dict] | None = None,
) -> int:
    changed = 0
    if isinstance(obj, dict):
        local_aliases = dict(aliases or {})
        local_aliases.update(_source_alias_entries(obj))
        for ref_type in ("Column", "Measure", "HierarchyLevel"):
            ref = obj.get(ref_type)
            if isinstance(ref, dict) and _ref_object_matches(ref, old_table, old_name, local_aliases):
                changed += _replace_ref_object(ref, target_table, target_name, local_aliases)
        if _ref_object_matches(obj, old_table, old_name, local_aliases):
            changed += _replace_ref_object(obj, target_table, target_name, local_aliases)
        for value in obj.values():
            changed += _replace_reference_in_obj(value, old_table, old_name, target_table, target_name, local_aliases)
    elif isinstance(obj, list):
        for item in obj:
            changed += _replace_reference_in_obj(item, old_table, old_name, target_table, target_name, aliases)
    return changed


def _rewrite_exact_reference_strings(obj, old_table: str, old_name: str, target_table: str, target_name: str) -> int:
    changed = 0
    old_dot = f"{old_table}.{old_name}"
    target_dot = f"{target_table}.{target_name}"
    old_bracket = f"{old_table}[{old_name}]"
    target_bracket = f"{target_table}[{target_name}]"
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, str):
                new_value = value
                if value == old_dot:
                    new_value = target_dot
                elif value == old_bracket:
                    new_value = target_bracket
                else:
                    wrapper = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\((.+)\)", value)
                    if wrapper and wrapper.group(2) == old_dot:
                        new_value = f"{wrapper.group(1)}({target_dot})"
                if new_value != value:
                    obj[key] = new_value
                    changed += 1
            else:
                changed += _rewrite_exact_reference_strings(value, old_table, old_name, target_table, target_name)
    elif isinstance(obj, list):
        for idx, value in enumerate(list(obj)):
            if isinstance(value, str):
                if value == old_dot:
                    obj[idx] = target_dot
                    changed += 1
                elif value == old_bracket:
                    obj[idx] = target_bracket
                    changed += 1
            else:
                changed += _rewrite_exact_reference_strings(value, old_table, old_name, target_table, target_name)
    return changed


def _split_top_level_report_ref(value: str) -> tuple[str, str] | None:
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
            return (left, right) if left and right else None
    return None


def _report_refs(obj, path_parts: list[str] | None = None) -> list[dict]:
    if path_parts is None:
        path_parts = []
    refs = []
    if isinstance(obj, dict):
        for ref_type in ("Column", "Measure", "HierarchyLevel"):
            ref = obj.get(ref_type)
            if not isinstance(ref, dict):
                continue
            expr = ref.get("Expression", {})
            if isinstance(expr, dict) and "Hierarchy" in expr:
                expr = expr.get("Hierarchy", {}).get("Expression", {})
            source_ref = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
            prop = ref.get("Property", ref.get("Hierarchy", ""))
            entity = source_ref.get("Entity") if isinstance(source_ref, dict) else ""
            if entity and prop:
                refs.append({
                    "table": str(entity),
                    "name": str(prop),
                    "path": ".".join(path_parts + [ref_type]),
                })
        if "Aggregation" in obj and isinstance(obj["Aggregation"], dict):
            refs.extend(_report_refs(obj["Aggregation"], path_parts + ["Aggregation"]))
        metadata = obj.get("metadata")
        if isinstance(metadata, str):
            parts = _split_top_level_report_ref(metadata)
            if parts:
                refs.append({
                    "table": parts[0],
                    "name": parts[1],
                    "path": ".".join(path_parts + ["metadata"]),
                })
        for key, value in obj.items():
            if key in ("$schema",):
                continue
            refs.extend(_report_refs(value, path_parts + [key]))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            refs.extend(_report_refs(item, path_parts + [f"[{idx}]"]))
    return refs


def _remove_related_references(payload: dict, table: str, name: str, skip_paths: set[str]) -> tuple[int, list[str]]:
    if not table or not name:
        return 0, []
    remove_paths = []
    for ref in _report_refs(payload):
        if str(ref.get("table", "")).casefold() != table.casefold():
            continue
        if str(ref.get("name", "")).casefold() != name.casefold():
            continue
        remove_path = _reference_removal_path(str(ref.get("path", "")))
        if remove_path and remove_path not in skip_paths:
            remove_paths.append(remove_path)

    removed = []
    for remove_path in _sorted_delete_paths(set(remove_paths)):
        if _delete_path(payload, remove_path):
            removed.append(remove_path)
    return len(removed), removed


def apply_report_issue_actions(*, entries: list[dict]) -> dict:
    if not entries:
        return {"ok": False, "error": "No report issue actions were provided"}

    grouped: dict[Path, list[dict]] = {}
    for entry in entries:
        report_path = Path(str(entry.get("report_path", "") or "")).resolve()
        artifact_path = str(entry.get("artifact_path", "") or "").strip()
        if not report_path.exists():
            return {"ok": False, "error": f"Report path not found: {report_path}"}
        if not artifact_path:
            return {"ok": False, "error": "Each report issue action needs artifact_path"}
        target_file = (report_path / artifact_path).resolve()
        grouped.setdefault(target_file, []).append(entry)

    updated_files = []
    actions = []
    total_changed = 0
    warnings = []
    for target_file, file_entries in grouped.items():
        if not target_file.exists():
            return {"ok": False, "error": f"PBIR file not found: {target_file}"}
        payload = json.loads(target_file.read_text(encoding="utf-8"))
        file_changed = 0
        for entry in _sort_report_issue_actions(file_entries):
            action = str(entry.get("action", "") or "").strip()
            source_path = str(entry.get("source_path", "") or "").strip()
            table = str(entry.get("table", "") or "").strip()
            name = str(entry.get("name", "") or "").strip()
            if not source_path:
                warnings.append(f"Skipped action without source_path in {target_file}")
                continue
            if action == "remove":
                remove_path = _reference_removal_path(source_path)
                if _delete_path(payload, remove_path):
                    file_changed += 1
                    actions.append({"file": str(target_file), "action": action, "path": remove_path})
                    related_count, related_paths = _remove_related_references(payload, table, name, {remove_path})
                    if related_count:
                        file_changed += related_count
                        actions.append({
                            "file": str(target_file),
                            "action": "remove_related",
                            "from": f"{table}[{name}]",
                            "paths": related_paths,
                            "change_count": related_count,
                        })
                else:
                    warnings.append(f"Could not remove path {remove_path} in {target_file}")
            elif action == "replace":
                target_table = str(entry.get("target_table", "") or "").strip()
                target_name = str(entry.get("target_name", "") or "").strip()
                if not table or not name or not target_table or not target_name:
                    warnings.append(f"Skipped replacement with incomplete source/target in {target_file}")
                    continue
                scope_path = _reference_update_scope_path(source_path)
                target_obj = _path_value(payload, scope_path)
                changed = _replace_reference_in_obj(target_obj, table, name, target_table, target_name) if target_obj is not None else 0
                changed += _rewrite_exact_reference_strings(target_obj, table, name, target_table, target_name) if target_obj is not None else 0
                if changed:
                    file_changed += changed
                    actions.append({
                        "file": str(target_file),
                        "action": action,
                        "path": scope_path,
                        "from": f"{table}[{name}]",
                        "to": f"{target_table}[{target_name}]",
                        "change_count": changed,
                    })
                else:
                    warnings.append(f"No matching reference found at {source_path} in {target_file}")
            else:
                warnings.append(f"Skipped unsupported report issue action: {action}")

        if file_changed:
            target_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated_files.append(str(target_file))
            total_changed += file_changed

    return {
        "ok": True,
        "action": "apply_report_issue_actions",
        "updated_files": updated_files,
        "updated_file_count": len(updated_files),
        "updated_reference_count": total_changed,
        "actions": actions,
        "warnings": warnings,
    }


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


def _split_item_ref(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+)\[([^\]]+)\]", value.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _json_contains_item_ref(obj, table: str, name: str) -> bool:
    if isinstance(obj, dict):
        for ref_type in ("Column", "Measure", "Hierarchy"):
            inner = obj.get(ref_type)
            if isinstance(inner, dict):
                prop = inner.get("Property") or inner.get("Hierarchy")
                src = inner.get("Expression", {}).get("SourceRef", {})
                if isinstance(src, dict) and src.get("Entity") == table and prop == name:
                    return True
        return any(_json_contains_item_ref(value, table, name) for value in obj.values())
    if isinstance(obj, list):
        return any(_json_contains_item_ref(item, table, name) for item in obj)
    return False


def _remove_formatting_selector_entries(obj, stale_values: set[str], removed: list[dict], path_parts: list[str] | None = None) -> None:
    if path_parts is None:
        path_parts = []
    refs = [ref for ref in (_split_item_ref(value) for value in stale_values) if ref]
    if not refs:
        return
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, list):
                new_items = []
                for idx, item in enumerate(value):
                    selector = item.get("selector") if isinstance(item, dict) else None
                    if isinstance(selector, dict) and any(_json_contains_item_ref(selector, table, name) for table, name in refs):
                        removed.append({
                            "path": ".".join(path_parts + [key, f"[{idx}]"]),
                            "selector_value": "",
                        })
                        continue
                    _remove_formatting_selector_entries(item, stale_values, removed, path_parts + [key, f"[{idx}]"])
                    new_items.append(item)
                obj[key] = new_items
            else:
                _remove_formatting_selector_entries(value, stale_values, removed, path_parts + [key])
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _remove_formatting_selector_entries(item, stale_values, removed, path_parts + [f"[{idx}]"])


def _remove_formatting_rule_entries(obj, stale_values: set[str], removed: list[dict], path_parts: list[str] | None = None) -> None:
    if path_parts is None:
        path_parts = []
    refs = [ref for ref in (_split_item_ref(value) for value in stale_values) if ref]
    if not refs:
        return
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, list):
                new_items = []
                for idx, item in enumerate(value):
                    properties = item.get("properties") if isinstance(item, dict) else None
                    if isinstance(properties, dict) and any(_json_contains_item_ref(properties, table, name) for table, name in refs):
                        removed.append({
                            "path": ".".join(path_parts + [key, f"[{idx}]"]),
                            "selector_value": "",
                        })
                        continue
                    _remove_formatting_rule_entries(item, stale_values, removed, path_parts + [key, f"[{idx}]"])
                    new_items.append(item)
                obj[key] = new_items
            else:
                _remove_formatting_rule_entries(value, stale_values, removed, path_parts + [key])
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _remove_formatting_rule_entries(item, stale_values, removed, path_parts + [f"[{idx}]"])


def cleanup_stale_metadata_selectors(*, entries: list[dict], dry_run: bool = False) -> dict:
    if not entries:
        return {"ok": False, "error": "No stale selector entries were provided"}

    selector_grouped: dict[Path, set[str]] = {}
    formatting_selector_grouped: dict[Path, set[str]] = {}
    formatting_rule_grouped: dict[Path, set[str]] = {}
    path_entries: dict[Path, set[str]] = {}
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
            path_entries.setdefault(target_file, set()).add(m.group(1))
        elif stale_kind == "visual_formatting_selector_entry":
            if selector_value:
                formatting_selector_grouped.setdefault(target_file, set()).add(selector_value)
            else:
                if ".selector." not in source_path:
                    return {"ok": False, "error": "Formatting selector cleanup requires source_path for the selector entry"}
                prefix_path = source_path.split(".selector.", 1)[0]
                if not prefix_path:
                    return {"ok": False, "error": f"Could not resolve formatting selector path: {source_path}"}
                path_entries.setdefault(target_file, set()).add(prefix_path)
        elif stale_kind == "formatting_rule_reference":
            if not selector_value:
                return {"ok": False, "error": "Formatting rule cleanup requires selector_value"}
            formatting_rule_grouped.setdefault(target_file, set()).add(selector_value)
        elif stale_kind == "exact_reference" or entry.get("action") == "remove":
            if not source_path:
                return {"ok": False, "error": "Exact cleanup requires source_path"}
            path_entries.setdefault(target_file, set()).add(_reference_removal_path(source_path))
        else:
            if not selector_value:
                return {"ok": False, "error": "Visual stale cleanup requires selector_value"}
            selector_grouped.setdefault(target_file, set()).add(selector_value)

    updated_files = []
    removed_entries = []
    pending_payloads: dict[Path, dict] = {}
    changed_files: set[Path] = set()

    def load_pending_payload(target_file: Path) -> tuple[dict | None, dict | None]:
        if target_file in pending_payloads:
            return pending_payloads[target_file], None
        if not target_file.exists():
            return None, {"ok": False, "error": f"PBIR file not found: {target_file}"}
        try:
            payload = json.loads(target_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return None, {"ok": False, "error": f"Invalid JSON in {target_file}: {exc}"}
        pending_payloads[target_file] = payload
        return payload, None

    for target_file, entry_paths in path_entries.items():
        payload, error = load_pending_payload(target_file)
        if error:
            return error
        removed_for_file = []
        for delete_path in _sorted_delete_paths(entry_paths):
            if _delete_path(payload, delete_path):
                removed_for_file.append({
                    "path": delete_path,
                    "selector_value": "",
                })
        if removed_for_file:
            validation = validate_pbir_json_file(target_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                }
            changed_files.add(target_file)
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

    for target_file, stale_values in selector_grouped.items():
        payload, error = load_pending_payload(target_file)
        if error:
            return error
        live_query_refs = _collect_query_refs(payload.get("visual", {}).get("query", {}).get("queryState", {}))
        removed_for_file: list[dict] = []
        _remove_stale_selector_entries(payload, stale_values, live_query_refs, removed_for_file)
        if removed_for_file:
            validation = validate_pbir_json_file(target_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                }
            changed_files.add(target_file)
            updated_files.append(str(target_file))
            removed_entries.extend(
                {
                    "file": str(target_file),
                    "path": item["path"],
                    "selector_value": item["selector_value"],
                }
                for item in removed_for_file
            )

    for target_file, stale_values in formatting_selector_grouped.items():
        payload, error = load_pending_payload(target_file)
        if error:
            return error
        removed_for_file: list[dict] = []
        _remove_formatting_selector_entries(payload, stale_values, removed_for_file)
        if removed_for_file:
            validation = validate_pbir_json_file(target_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                }
            changed_files.add(target_file)
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

    for target_file, stale_values in formatting_rule_grouped.items():
        payload, error = load_pending_payload(target_file)
        if error:
            return error
        removed_for_file: list[dict] = []
        _remove_formatting_rule_entries(payload, stale_values, removed_for_file)
        if removed_for_file:
            validation = validate_pbir_json_file(target_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                }
            changed_files.add(target_file)
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

    if changed_files and not dry_run:
        target_files = list(changed_files)
        snapshot = file_transaction.snapshot_artifact_files(target_files, suffixes=(".json",))
        try:
            for target_file in target_files:
                target_file.write_text(
                    json.dumps(pending_payloads[target_file], indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        except OSError as exc:
            rollback = file_transaction.restore_artifact_files(target_files, snapshot, suffixes=(".json",))
            return {
                "ok": False,
                "error": f"PBIR write failed: {exc}",
                "rolled_back": rollback["ok"],
                "rollback": rollback,
                "updated_files": updated_files,
                "removed_count": len(removed_entries),
                "removed_entries": removed_entries,
            }

    return {
        "ok": True,
        "action": "cleanup_stale_metadata_selectors",
        "dry_run": dry_run,
        "updated_files": updated_files,
        "removed_count": len(removed_entries),
        "removed_entries": removed_entries,
    }
