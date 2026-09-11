#!/usr/bin/env python3
"""Report definition write helpers for PBIR artifacts."""

import json
import re
import shutil
from functools import cmp_to_key
from datetime import datetime
from pathlib import Path

from . import file_transaction, tmdl_writer
from .reference_tokens import dax_references, rewrite_dax


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


def _migrate_single_measure_to_model(
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


def migrate_measure_to_model(
    *, model_path: Path, report_path: Path, entity_name: str, measure_name: str,
    target_table: str | None = None, target_name: str | None = None,
    dry_run: bool = False, include_dependencies: bool = False,
    allow_metadata_loss: bool = False,
) -> dict:
    """Preflight a dependency-closed promotion before any model/report mutation."""
    entity_name, measure_name = entity_name.strip(), measure_name.strip()
    if ((target_table or entity_name).casefold() != entity_name.casefold()
            or (target_name or measure_name).casefold() != measure_name.casefold()):
        return {"ok": False, "error": "Renaming during report-measure migration is not supported yet; target table/name must match the report measure."}
    try:
        _, payload = _load_report_extensions(report_path)
        extensions = {}
        for entity in payload.get("entities", []):
            for measure in entity.get("measures", []):
                key = (str(entity.get("name", "")).casefold(), str(measure.get("name", "")).casefold())
                if key in extensions:
                    return {"ok": False, "error": "Duplicate report extension measure identity"}
                extensions[key] = (str(entity.get("name", "")), measure)
        root = (entity_name.casefold(), measure_name.casefold())
        if root not in extensions:
            return {"ok": False, "error": f"Report measure '{entity_name}[{measure_name}]' was not found"}
        model_items = set()
        model_measures = set()
        for path in tmdl_writer._iter_tmdl_files(model_path):
            owner = ''
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith('table '):
                    owner = tmdl_writer._unquote_tmdl_name(line[6:]).casefold()
                match = re.match(r"^\t(measure|column)\s+(.+?)(?:\s*=.*)?$", line, re.I)
                if match:
                    key = (owner, tmdl_writer._unquote_tmdl_name(match.group(2)).casefold())
                    model_items.add(key)
                    if match.group(1).casefold() == 'measure':
                        model_measures.add(key)
        ordered, visiting, done = [], set(), set()
        blockers = []
        def visit(key):
            if key in visiting:
                blockers.append(f"Cyclic report extension dependency: {key[0]}[{key[1]}]")
                return
            if key in done:
                return
            visiting.add(key)
            table, measure = extensions[key]
            expression = str(measure.get('expression', '') or '')
            if not expression.strip():
                blockers.append(f"Empty expression: {table}[{measure.get('name')}]")
            # Declared dependency metadata supplements lexical references.
            refs = list(dax_references(expression))
            for ref in (measure.get('references') or {}).get('measures', []):
                if isinstance(ref, dict):
                    refs.append((ref.get('entity'), str(ref.get('name', ''))))
            for owner, name in refs:
                candidates = [k for k in extensions if k[1] == name.casefold()
                              and (owner is None or k[0] == owner.casefold())]
                if len(candidates) == 1:
                    visit(candidates[0])
                elif len(candidates) > 1:
                    blockers.append(f"Ambiguous report extension dependency: [{name}]")
                elif not any(k[1] == name.casefold() and (owner is None or k[0] == owner.casefold()) for k in model_items):
                    blockers.append(f"Unresolved dependency: {owner or ''}[{name}]")
            visiting.remove(key)
            done.add(key)
            ordered.append(key)
        visit(root)
        promotions = []
        promoted_names = [key[1] for key in ordered]
        if len(set(promoted_names)) != len(promoted_names):
            blockers.append("Multiple promoted measures would have the same semantic model name")
        for key in ordered:
            table, measure = extensions[key]
            name = str(measure.get('name', ''))
            if not tmdl_writer._find_tmdl_file(model_path, table):
                blockers.append(f"Target table does not exist: {table}")
            if any(existing[1] == name.casefold() for existing in model_measures):
                blockers.append(f"A semantic model measure already has the name '{name}'")
            kwargs, preserved, lost = _report_measure_promotion_metadata(measure)
            known = {'name', 'expression', 'references', 'dataType', 'dataCategory', 'description',
                     'displayFolder', 'formatString', 'hidden', 'annotations', 'measureTemplate'}
            lost += [{"field": field, "reason": "Unsupported report extension metadata"}
                     for field in measure if field not in known]
            semantic_loss = [entry for entry in lost if entry['field'] != 'measureTemplate']
            if semantic_loss and not allow_metadata_loss:
                blockers.append(f"Promotion would discard metadata for {table}[{name}]; review unpreserved_metadata")
            for field in ('data_type', 'data_category', 'display_folder', 'format_string'):
                if '\n' in str(kwargs.get(field, '')) or '\r' in str(kwargs.get(field, '')):
                    blockers.append(f"Unsupported multiline {field}: {table}[{name}]")
            promotions.append({"table": table, "name": name, "preserved_metadata": preserved,
                               "unpreserved_metadata": lost})
        dependencies = [entry for entry in promotions if (entry['table'].casefold(), entry['name'].casefold()) != root]
        if dependencies and not include_dependencies:
            blockers.append("Report-only dependencies must be promoted together; set include_dependencies after reviewing the plan")
        selected = next((entry for entry in promotions if (entry['table'].casefold(), entry['name'].casefold()) == root), {})
        plan = {"ok": not blockers, "dry_run": dry_run, "action": "migrate_report_measure",
                "promotions": promotions, "required_dependencies": dependencies, "blockers": blockers,
                "preserved_metadata": selected.get('preserved_metadata', []),
                "unpreserved_metadata": selected.get('unpreserved_metadata', [])}
        if blockers:
            return {**plan, "error": '; '.join(blockers), "written": False}
        if dry_run:
            return plan
        roots = [model_path / 'definition', report_path / 'definition']
        snapshot = file_transaction.snapshot_artifact_files(roots)
        results = []
        try:
            for entry in promotions:
                result = _migrate_single_measure_to_model(model_path=model_path, report_path=report_path,
                    entity_name=entry['table'], measure_name=entry['name'])
                if not result.get('ok'):
                    raise ValueError(result.get('error', 'Promotion failed'))
                results.append(result)
        except Exception as exc:
            rollback = file_transaction.restore_artifact_files(roots, snapshot)
            return {**plan, "ok": False, "error": str(exc), "rolled_back": rollback['ok'], "rollback": rollback}
        return {**results[-1], **plan, "results": results, "written": True}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {"ok": False, "error": str(exc), "written": False, "dry_run": dry_run}


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
    column_renames: list[dict] | None = None,
) -> tuple[dict[str, str], dict[tuple[str, str], tuple[str, str]], dict[tuple[str, str], tuple[str, str]]]:
    table_lookup: dict[str, str] = {}
    measure_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    column_lookup: dict[tuple[str, str], tuple[str, str]] = {}

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

    for rename in column_renames or []:
        table = str(rename.get("table", "") or "").strip()
        name = str(rename.get("name", "") or "").strip()
        target_name = str(rename.get("target_name", "") or "").strip()
        if not (table and name and target_name):
            continue
        # Target table defaults to the (possibly renamed) source table.
        target_table = str(rename.get("target_table", "") or "").strip()
        resolved_table = target_table or table_lookup.get(table.casefold(), table)
        column_lookup[(table.casefold(), name.casefold())] = (resolved_table, target_name)

    return table_lookup, measure_lookup, column_lookup


def _rewrite_query_ref(
    value: str,
    table_lookup: dict[str, str],
    measure_lookup: dict[tuple[str, str], tuple[str, str]],
    aliases: dict[str, dict],
    column_lookup: dict[tuple[str, str], tuple[str, str]] | None = None,
    updates: list[dict] | None = None,
) -> tuple[str, bool]:
    column_lookup = column_lookup or {}
    wrapper = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\((.+)\)", value)
    if wrapper:
        new_inner, changed = _rewrite_query_ref(wrapper.group(2), table_lookup, measure_lookup, aliases, column_lookup, updates)
        if changed:
            return f"{wrapper.group(1)}({new_inner})", True
        return value, False

    parts = _split_top_level_query_ref(value)
    if not parts:
        return value, False
    table_or_alias, name = parts
    alias = aliases.get(table_or_alias.casefold())
    if alias and alias.get("ambiguous"):
        if table_lookup or any(key[1] == name.casefold() for key in (*measure_lookup, *column_lookup)):
            raise ValueError(f"Cannot resolve query alias '{table_or_alias}' for '{value}'; propagation is ambiguous.")
        return value, False
    table = alias["original_entity"] if alias else table_or_alias
    target_table = table_lookup.get(table.casefold(), table)
    target_name = name
    measure_target = measure_lookup.get((table.casefold(), name.casefold()))
    column_target = column_lookup.get((table.casefold(), name.casefold()))
    if measure_target:
        target_table, target_name = measure_target
    elif column_target:
        target_table, target_name = column_target
    if target_table.casefold() == table.casefold():
        target_table = table_lookup.get(table.casefold(), table)
    if alias and updates is not None:
        _set_alias_target(alias, target_table, updates)
    output_table = table_or_alias if alias else target_table
    if output_table == table_or_alias and target_name == name:
        return value, False
    return f"{output_table}.{target_name}", True


def _rewrite_dax_table_refs(value: str, table_lookup: dict[str, str]) -> tuple[str, bool]:
    new_value = value
    for table, target_table in table_lookup.items():
        new_value, _ = rewrite_dax(new_value, tables={table.casefold(): target_table})
    return new_value, new_value != value


def _collect_source_aliases(obj, path_parts, bindings) -> dict[str, dict] | None:
    """Read one query namespace, including its PBIR envelope, before mutation.

    Query-state projections and visual selectors use the visual's main query.
    Filter queries and sibling commands establish their own namespaces; they
    must never be flattened into a file-wide alias dictionary.
    """
    if not isinstance(obj, dict):
        return None
    aliases: dict[str, dict] = {}
    if "From" in obj:
        for idx, source in enumerate(obj["From"] if isinstance(obj["From"], list) else []):
            if not isinstance(source, dict) or not isinstance(source.get("Name"), str):
                continue
            alias_name = source["Name"]
            if id(source) not in bindings:
                bindings[id(source)] = {
                    "name": alias_name,
                    "original_entity": source.get("Entity"),
                    "source": source,
                    "entity_path": path_parts + ["From", f"[{idx}]", "Entity"],
                    "ambiguous": not isinstance(source.get("Entity"), str) or not source["Entity"].strip(),
                }
            alias_key = alias_name.casefold()
            aliases[alias_key] = ({"ambiguous": True} if alias_key in aliases else bindings[id(source)])
        return aliases
    for key in ("query", "SemanticQueryDataShapeCommand", "Query", "prototypeQuery", "filter"):
        nested = _collect_source_aliases(obj.get(key), path_parts + [key], bindings)
        if nested is not None:
            return nested
    return None


def _source_alias_scopes(obj) -> dict[int, dict[str, dict]]:
    """Snapshot original bindings once so later edits cannot change resolution."""
    scopes: dict[int, dict[str, dict]] = {}
    bindings: dict[int, dict] = {}

    def visit(value, path, inherited):
        if isinstance(value, dict):
            local = _collect_source_aliases(value, path, bindings)
            aliases = inherited if local is None else local
            scopes[id(value)] = aliases
            for key, child in value.items():
                visit(child, path + [key], aliases)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                visit(child, path + [f"[{idx}]"], inherited)

    visit(obj, [], {})
    # An alias seen only in another query is not a table-name fallback. Preserve
    # this distinction for queryRef/metadata strings outside a resolvable scope.
    unavailable = {binding["name"].casefold(): {"ambiguous": True} for binding in bindings.values()}
    for node, aliases in scopes.items():
        scopes[node] = {**unavailable, **aliases}
    return scopes


def _reference_source_ref(reference: dict, ref_type: str) -> dict:
    """Treat every missing/malformed source shape as unresolved, never skipped."""
    path = ("Expression", "Hierarchy", "Expression", "SourceRef") if ref_type == "HierarchyLevel" else ("Expression", "SourceRef")
    value = reference
    for key in path:
        if not isinstance(value, dict):
            return {}
        value = value.get(key)
    return value if isinstance(value, dict) else {}


def _resolve_reference_source(source_ref, prop, aliases, table_lookup, object_lookup, path):
    entity = source_ref.get("Entity")
    if isinstance(entity, str) and entity.strip():
        return entity, None
    source_alias = source_ref.get("Source")
    alias = aliases.get(source_alias.casefold()) if isinstance(source_alias, str) else None
    if alias and not alias.get("ambiguous"):
        return alias["original_entity"], alias
    moving_objects = any(target[0].casefold() != key[0] for key, target in object_lookup.items())
    if (table_lookup or (prop is None and moving_objects)
            or (isinstance(prop, str) and any(key[1] == prop.casefold() for key in object_lookup))):
        raise ValueError(
            f"Cannot resolve query alias '{source_alias}' at {'.'.join(path)} for '{prop}'; "
            "required reference propagation is ambiguous or unresolved."
        )
    return None, None


def _set_alias_target(alias, target_table, updates):
    """A shared source can only move if every reference still needs one table."""
    previous = alias.get("required_entity")
    if previous is not None and previous.casefold() != target_table.casefold():
        raise ValueError(
            f"Cannot propagate aliased references through shared query source '{alias['name']}': "
            f"its items require both '{previous}' and '{target_table}'."
        )
    alias["required_entity"] = target_table
    old_entity = alias["source"].get("Entity")
    if old_entity != target_table:
        alias["source"]["Entity"] = target_table
        updates.append({"path": ".".join(alias["entity_path"]), "from": old_entity,
                        "to": target_table, "kind": "From.Entity"})


def _rewrite_model_refs_in_json(
    obj,
    table_lookup: dict[str, str],
    measure_lookup: dict[tuple[str, str], tuple[str, str]],
    updates: list[dict],
    path_parts: list[str] | None = None,
    aliases: dict[str, dict] | None = None,
    column_lookup: dict[tuple[str, str], tuple[str, str]] | None = None,
    warnings: list[str] | None = None,
    alias_scopes: dict[int, dict[str, dict]] | None = None,
    processed_sources: set[int] | None = None,
) -> None:
    if path_parts is None:
        path_parts = []
    if aliases is None:
        aliases = {}
    if column_lookup is None:
        column_lookup = {}
    if warnings is None:
        warnings = []
    if alias_scopes is None:
        alias_scopes = _source_alias_scopes(obj)
    if processed_sources is None:
        processed_sources = set()

    if isinstance(obj, dict):
        local_aliases = alias_scopes.get(id(obj), {})
        from_entries = obj.get("From")
        if isinstance(from_entries, list):
            for idx, source in enumerate(from_entries):
                if not isinstance(source, dict):
                    continue
                alias_name = source.get("Name")
                entity = source.get("Entity")
                if not (isinstance(alias_name, str) and isinstance(entity, str)):
                    continue
                binding = local_aliases.get(alias_name.casefold(), {})
                original_entity = binding.get("original_entity", entity)
                target_table = binding.get("required_entity", table_lookup.get(original_entity.casefold(), original_entity))
                if target_table != entity:
                    source["Entity"] = target_table
                    updates.append({
                        "path": ".".join(path_parts + ["From", f"[{idx}]", "Entity"]),
                        "from": entity,
                        "to": target_table,
                        "kind": "From.Entity",
                    })

        measure = obj.get("Measure")
        if isinstance(measure, dict):
            prop = measure.get("Property")
            source_ref = _reference_source_ref(measure, "Measure")
            if isinstance(prop, str):
                processed_sources.add(id(source_ref))
                entity = source_ref.get("Entity")
                resolved_entity, alias = _resolve_reference_source(
                    source_ref, prop, local_aliases, table_lookup, measure_lookup, path_parts,
                )
                if isinstance(resolved_entity, str):
                    target_table = table_lookup.get(resolved_entity.casefold(), resolved_entity)
                    target_name = prop
                    measure_target = measure_lookup.get((resolved_entity.casefold(), prop.casefold()))
                    if measure_target:
                        target_table, target_name = measure_target
                        if target_table.casefold() == resolved_entity.casefold():
                            target_table = table_lookup.get(resolved_entity.casefold(), resolved_entity)
                    if isinstance(entity, str) and target_table != entity:
                        source_ref["Entity"] = target_table
                        updates.append({
                            "path": ".".join(path_parts + ["Measure", "Expression", "SourceRef", "Entity"]),
                            "from": entity,
                            "to": target_table,
                            "kind": "Measure.SourceRef.Entity",
                        })
                    elif alias:
                        _set_alias_target(alias, target_table, updates)
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
            source_ref = _reference_source_ref(ref, ref_type)
            prop = ref.get("Property")
            if isinstance(source_ref, dict):
                processed_sources.add(id(source_ref))
                entity = source_ref.get("Entity")
                resolved_entity, alias = _resolve_reference_source(
                    source_ref, prop, local_aliases, table_lookup, column_lookup, path_parts,
                )
                table_move_target = table_lookup.get(str(resolved_entity).casefold(), resolved_entity) if isinstance(resolved_entity, str) else None
                target_table = table_move_target
                target_name = prop if isinstance(prop, str) else None
                # A column rename can also move the column to a different table.
                if isinstance(resolved_entity, str) and isinstance(prop, str):
                    column_target = column_lookup.get((resolved_entity.casefold(), prop.casefold()))
                    if column_target:
                        target_table, target_name = column_target
                        if target_table.casefold() == resolved_entity.casefold():
                            target_table = table_lookup.get(resolved_entity.casefold(), resolved_entity)
                if isinstance(entity, str) and target_table and target_table != entity:
                    source_ref["Entity"] = target_table
                    updates.append({
                        "path": ".".join(path_parts + [ref_type, "Expression", "SourceRef", "Entity"]),
                        "from": entity,
                        "to": target_table,
                        "kind": f"{ref_type}.SourceRef.Entity",
                    })
                elif alias and target_table:
                    _set_alias_target(alias, target_table, updates)
                if isinstance(prop, str) and isinstance(target_name, str) and target_name != prop:
                    ref["Property"] = target_name
                    updates.append({
                        "path": ".".join(path_parts + [ref_type, "Property"]),
                        "from": prop,
                        "to": target_name,
                        "kind": f"{ref_type}.Property",
                    })

        source_ref = obj.get("SourceRef")
        if isinstance(source_ref, dict) and id(source_ref) not in processed_sources:
            # A source used by an expression other than the item being moved
            # still requires the original table. Do not repoint it implicitly.
            resolved_entity, alias = _resolve_reference_source(
                source_ref, None, local_aliases, table_lookup,
                {**measure_lookup, **column_lookup}, path_parts,
            )
            if isinstance(resolved_entity, str):
                target_table = table_lookup.get(resolved_entity.casefold(), resolved_entity)
                if alias:
                    _set_alias_target(alias, target_table, updates)
                elif target_table != resolved_entity:
                    raise ValueError(
                        f"Cannot propagate an unsupported SourceRef expression at {'.'.join(path_parts)}; "
                        "review its semantic binding before renaming the table."
                    )

        for key in ("queryRef", "metadata"):
            value = obj.get(key)
            if isinstance(value, str):
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup, local_aliases, column_lookup, updates)
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
                new_value, expression_updates = rewrite_dax(value, tables=table_lookup,
                    objects={**measure_lookup, **column_lookup})
                changed = bool(expression_updates) and new_value != value
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
                new_value, changed = _rewrite_query_ref(value, table_lookup, measure_lookup, local_aliases, column_lookup, updates)
                if changed:
                    query_refs[idx] = new_value
                    updates.append({
                        "path": ".".join(path_parts + ["queryRefs", f"[{idx}]"]),
                        "from": value,
                        "to": new_value,
                        "kind": "queryRefs",
                    })

        for key, value in obj.items():
            _rewrite_model_refs_in_json(value, table_lookup, measure_lookup, updates, path_parts + [key], local_aliases, column_lookup, warnings, alias_scopes, processed_sources)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _rewrite_model_refs_in_json(item, table_lookup, measure_lookup, updates, path_parts + [f"[{idx}]"], aliases, column_lookup, warnings, alias_scopes, processed_sources)


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
    column_renames: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Rewrite selected PBIR report JSON references for model moves/renames."""
    if not report_paths:
        return {"ok": False, "error": "No selected report paths were provided"}
    table_lookup, measure_lookup, column_lookup = _reference_lookup(
        moves=moves,
        table_renames=table_renames,
        measure_renames=measure_renames,
        column_renames=column_renames,
    )
    if not table_lookup and not measure_lookup and not column_lookup:
        return {"ok": False, "error": "No valid model reference changes were provided"}

    updated_files = []
    warnings = []
    total_updates = 0
    pending_writes: list[tuple[Path, dict]] = []

    for report_path in report_paths:
        definition_dir = report_path / "definition"
        if not report_path.exists():
            return {"ok": False, "error": f"Report path not found: {report_path}", "written": False}
        if not definition_dir.exists():
            return {"ok": False, "error": f"Report definition folder not found: {definition_dir}", "written": False}

        for json_file in sorted(definition_dir.rglob("*.json")):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"ok": False, "error": f"Cannot read selected PBIR JSON file {json_file}: {exc}", "written": False}

            updates: list[dict] = []
            try:
                _rewrite_model_refs_in_json(
                    payload, table_lookup, measure_lookup, updates,
                    column_lookup=column_lookup, warnings=warnings,
                )
            except ValueError as exc:
                return {"ok": False, "error": f"Cannot rewrite {json_file}: {exc}",
                        "written": False, "warnings": warnings}
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
        # Serialize every payload up front so a non-OSError (e.g. a non-serializable
        # value) cannot fire mid-write and leave reports half-rewritten — the write
        # loop below can then only fail with OSError, which the transaction handles.
        serialized_writes = [
            (json_file, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            for json_file, payload in pending_writes
        ]
        roots = [report_path / "definition" for report_path in report_paths]
        snapshot = file_transaction.snapshot_artifact_files(roots, suffixes=(".json",))
        try:
            for json_file, text in serialized_writes:
                json_file.write_text(text, encoding="utf-8")
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


def _report_action_target(entry: dict) -> Path:
    """Resolve an exact report-local artifact before loading or editing any bytes."""
    raw_report = str(entry.get('report_path', '') or '').strip()
    report = Path(raw_report)
    artifact = Path(str(entry.get('artifact_path', '') or '').strip())
    if not raw_report or not report.is_absolute():
        raise ValueError('Each report action needs an absolute report_path')
    if not report.is_dir():
        raise ValueError(f'Report path not found: {report}')
    if not entry.get('artifact_path') or artifact == Path('.'):
        raise ValueError('Each report action needs artifact_path')
    if artifact.is_absolute() or '..' in artifact.parts:
        raise ValueError('Report action artifact must stay inside its selected report')
    target = (report / artifact).resolve()
    if not target.is_relative_to(report.resolve()):
        raise ValueError('Report action artifact must stay inside its selected report')
    return target


def apply_report_issue_actions(*, entries: list[dict], dry_run: bool = False) -> dict:
    if not entries:
        return {"ok": False, "error": "No report issue actions were provided"}

    grouped: dict[Path, list[dict]] = {}
    for entry in entries:
        try:
            target_file = _report_action_target(entry)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        grouped.setdefault(target_file, []).append(entry)

    updated_files = []
    actions = []
    total_changed = 0
    warnings = []
    pending_payloads: dict[Path, dict] = {}
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
            validation = validate_pbir_json_file(target_file, payload)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": "PBIR validation failed",
                    "validation_errors": validation["errors"],
                }
            pending_payloads[target_file] = payload
            updated_files.append(str(target_file))
            total_changed += file_changed

    if pending_payloads and not dry_run:
        target_files = list(pending_payloads)
        # Serialize every payload up front so a non-OSError (e.g. a non-serializable
        # value) cannot fire mid-write and leave reports half-rewritten — the write
        # loop below can then only fail with OSError, which the transaction handles.
        serialized_writes = [
            (target_file, json.dumps(pending_payloads[target_file], indent=2, ensure_ascii=False) + "\n")
            for target_file in target_files
        ]
        snapshot = file_transaction.snapshot_artifact_files(target_files, suffixes=(".json",))
        try:
            for target_file, text in serialized_writes:
                target_file.write_text(text, encoding="utf-8")
        except OSError as exc:
            rollback = file_transaction.restore_artifact_files(target_files, snapshot, suffixes=(".json",))
            return {
                "ok": False,
                "error": f"PBIR write failed: {exc}",
                "rolled_back": rollback["ok"],
                "rollback": rollback,
                "updated_files": updated_files,
                "updated_reference_count": total_changed,
                "actions": actions,
                "warnings": warnings,
            }

    return {
        "ok": True,
        "action": "apply_report_issue_actions",
        "dry_run": dry_run,
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
        try:
            target_file = _report_action_target(entry)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        selector_value = str(entry.get("selector_value", "") or "").strip()
        source_path = str(entry.get("source_path", "") or "").strip()
        stale_kind = str(entry.get("stale_kind", "") or "").strip()
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
        # Serialize every payload up front so a non-OSError (e.g. a non-serializable
        # value) cannot fire mid-write and leave reports half-rewritten — the write
        # loop below can then only fail with OSError, which the transaction handles.
        serialized_writes = [
            (target_file, json.dumps(pending_payloads[target_file], indent=2, ensure_ascii=False) + "\n")
            for target_file in target_files
        ]
        snapshot = file_transaction.snapshot_artifact_files(target_files, suffixes=(".json",))
        try:
            for target_file, text in serialized_writes:
                target_file.write_text(text, encoding="utf-8")
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
