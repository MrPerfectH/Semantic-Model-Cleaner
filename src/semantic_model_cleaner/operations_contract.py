"""Offline input schema for agents; semantic and freshness checks still run in plans."""
import json
import sys

from jsonschema import Draft202012Validator

from . import __version__
from .cli_contract import ArgumentParser, emit_json

VERSION = "1.0"
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}


def _obj(properties, required):
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def _array(items):
    return {"type": "array", "items": items, "minItems": 1}


def schema():
    """Return a standalone JSON Schema with no remote references."""
    item = {"table": TEXT, "name": TEXT}
    source = {"source_file": TEXT}
    action = _obj({**item, **source,
        "action": {"enum": ["hide", "unhide", "delete", "move_to_folder", "move_to_table_group"]},
        "item_type": {"enum": ["Measure", "Column", "Calculated Column", "Table"]},
        "folder": {"type": "string"}, "table_group": {"type": "string"}},
        ["action", "table", "name", "item_type"])
    action["allOf"] = [
        {"if": {"properties": {"action": {"const": "move_to_folder"}}},
         "then": {"required": ["folder"]}},
        {"if": {"properties": {"action": {"const": "move_to_table_group"}}},
         "then": {"required": ["table_group"], "properties": {"item_type": {"const": "Table"}}}},
    ]
    renames = {
        "table_renames": _array(_obj({"table": TEXT, "target_table": TEXT}, ["table", "target_table"])),
        "measure_renames": _array(_obj({**item, **source, "target_name": TEXT}, ["table", "name", "target_name"])),
        "column_renames": _array(_obj({**item, **source, "target_name": TEXT}, ["table", "name", "target_name"])),
    }
    target = {"report_path": TEXT, "artifact_path": TEXT, "source_path": TEXT}
    issue = _obj({**target, **item, "action": {"enum": ["remove", "replace"]},
                  "target_table": TEXT, "target_name": TEXT},
                 ["report_path", "artifact_path", "source_path", "action"])
    issue["allOf"] = [{"if": {"properties": {"action": {"const": "replace"}}},
                       "then": {"required": ["table", "name", "target_table", "target_name"]}}]
    stale = _obj({**target, "selector_value": TEXT,
        "stale_kind": {"enum": ["", "bookmark_projection_entry", "visual_formatting_selector_entry",
                                "formatting_rule_reference", "exact_reference"]},
        "action": {"const": "remove"}}, ["report_path", "artifact_path"])
    stale["anyOf"] = [{"required": ["source_path"]}, {"required": ["selector_value"]}]
    definitions = {}

    def operation(kind, properties, required):
        definitions[kind] = _obj({"kind": {"const": kind}, "report_paths": _array(TEXT),
                                  **properties}, ["kind", *required])

    operation("actions", {"actions": _array(action)}, ["actions"])
    for kind in ("rename", "report_repair"):
        operation(kind, renames, [])
        definitions[kind]["anyOf"] = [{"required": [key]} for key in renames]
    operation("move", {"moves": _array(_obj({**item, **source, "target_table": TEXT},
                                            ["table", "name", "target_table"]))}, ["moves"])
    operation("promote", {**item, "report_path": TEXT, "target_table": TEXT, "target_name": TEXT,
        "include_dependencies": {"type": "boolean"}, "allow_metadata_loss": {"type": "boolean"}},
        ["table", "name"])
    operation("dax", {**item, **source, "dax_expression": TEXT,
        "item_type": {"enum": ["Measure", "Calculated Column"]}},
        ["table", "name", "item_type", "dax_expression"])
    operation("clean_stale", {"entries": _array(stale)}, ["entries"])
    operation("report_issues", {"entries": _array(issue)}, ["entries"])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Semantic Model Cleaner operations 1.0", "$defs": definitions,
        **_obj({"schema_version": {"const": VERSION},
                "operations": _array({"oneOf": [{"$ref": f"#/$defs/{kind}"} for kind in definitions]})},
               ["schema_version", "operations"])}


def _validate(contract, value, prefix):
    error = next(Draft202012Validator(contract).iter_errors(value), None)
    if error:
        path = ".".join(map(str, error.absolute_path))
        raise ValueError(f"Invalid operations at {prefix}.{path}: {error.message}")


def parse_operations(raw):
    """Strict versioned inputs; preserve legacy list and unversioned-object support."""
    if not isinstance(raw, dict) or "schema_version" not in raw:
        return raw.get("operations") if isinstance(raw, dict) else raw
    if raw["schema_version"] != VERSION:
        raise ValueError(f"Unsupported operations schema_version: {raw['schema_version']!r}; supported: {VERSION}")
    contract = schema()
    _validate({**contract, "properties": {**contract["properties"],
              "operations": _array({"type": "object"})}}, raw, "$")
    for index, operation in enumerate(raw["operations"]):
        kind = operation.get("kind")
        if not isinstance(kind, str) or kind not in contract["$defs"]:
            raise ValueError(f"Unsupported operation kind at $.operations.{index}: {kind!r}")
        _validate(contract["$defs"][kind], operation, f"$.operations.{index}")
    return raw["operations"]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = ArgumentParser(description="Offline discovery for external agents.", json_errors=True)
    parser.add_argument("command", choices=["capabilities", "operations-schema"])
    parser.add_argument("--format", choices=["json"], default="json")
    try:
        args = parser.parse_args(argv)
        if args.command == "operations-schema":
            print(json.dumps(schema(), ensure_ascii=False, indent=2))
        else:
            emit_json(args.command, {
                "tool_version": __version__, "operations_schema_version": VERSION,
                "operations": list(schema()["$defs"]), "schema_command": "smc operations-schema",
                "workflow": ["analyze", "plan", "diff", "apply", "verify"],
                "plan_workflow_mutations": ["apply", "restore", "recover-lock"],
                "approval": "Obtain explicit user approval of the exact plan before apply or restore.",
                "safeguards": ["local staging", "scope checks", "sealed plans", "freshness checks",
                               "semantic validation", "byte-exact recovery"],
                "legacy_unversioned_operations": True,
            })
        return 0
    except ValueError as exc:
        emit_json(argv[0] if argv else "capabilities", {"ok": False, "error": str(exc)})
        return 2
