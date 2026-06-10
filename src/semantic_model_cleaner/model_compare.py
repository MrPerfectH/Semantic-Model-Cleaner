"""Semantic model to semantic model comparison for local TMDL projects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_model_cleaner.tmdl_identifiers import split_tmdl_name_and_expression, unquote_tmdl_name


class UnsupportedCompareModelError(RuntimeError):
    """Raised when a selected Semantic Model cannot be compared as TMDL."""


@dataclass(frozen=True)
class CompareObject:
    category: str
    table: str
    name: str
    properties: dict[str, Any]
    source_file: str


@dataclass
class ModelSnapshot:
    path: Path
    tables: dict[tuple[str, str], CompareObject]
    measures: dict[tuple[str, str], CompareObject]
    columns: dict[tuple[str, str], CompareObject]


_CATEGORY_LABELS = {
    "tables": "Table",
    "measures": "Measure",
    "columns": "Column",
}

_PROPERTY_ORDER = {
    "tables": ("isHidden",),
    "measures": ("expression", "displayFolder", "isHidden", "formatString", "formatStringDefinition"),
    "columns": (
        "expression",
        "dataType",
        "sourceColumn",
        "summarizeBy",
        "displayFolder",
        "isHidden",
        "isKey",
        "sortByColumn",
        "formatString",
    ),
}

_BOOLEAN_PROPERTIES = {"isHidden", "isKey"}
_TABLE_PROPERTY_KEYS = {"isHidden"}


def compare_models(baseline_model_path: Path, candidate_model_path: Path) -> dict[str, Any]:
    """Compare two local TMDL Semantic Model folders."""
    baseline = parse_model_snapshot(Path(baseline_model_path))
    candidate = parse_model_snapshot(Path(candidate_model_path))

    summary: dict[str, dict[str, int] | int] = {}
    diffs: list[dict[str, Any]] = []

    for category in ("tables", "measures", "columns"):
        baseline_objects = getattr(baseline, category)
        candidate_objects = getattr(candidate, category)
        category_summary, category_diffs = _compare_category(category, baseline_objects, candidate_objects)
        summary[category] = category_summary
        diffs.extend(category_diffs)

    summary["totalDifferences"] = len(diffs)
    return {
        "baselineModel": _model_payload(baseline.path),
        "candidateModel": _model_payload(candidate.path),
        "summary": summary,
        "diffs": diffs,
    }


def parse_model_snapshot(model_path: Path) -> ModelSnapshot:
    model_path = model_path.resolve()
    if not model_path.exists():
        raise UnsupportedCompareModelError(f"Model path not found: {model_path}")
    if not model_path.is_dir():
        raise UnsupportedCompareModelError(f"Model path is not a folder: {model_path}")

    tables_dir = model_path / "definition" / "tables"
    if not tables_dir.exists():
        if (model_path / "model.bim").exists() or (model_path / "definition" / "model.bim").exists():
            raise UnsupportedCompareModelError(
                "Semantic Model Compare requires TMDL. Convert the Semantic Model from TMSL/model.bim first: "
                f"{model_path}"
            )
        raise UnsupportedCompareModelError(
            "Semantic Model Compare requires TMDL table definitions at definition/tables: "
            f"{model_path}"
        )

    snapshot = ModelSnapshot(path=model_path, tables={}, measures={}, columns={})
    for filepath in sorted(tables_dir.glob("*.tmdl")):
        _parse_table_file(filepath, snapshot)
    return snapshot


def _parse_table_file(filepath: Path, snapshot: ModelSnapshot) -> None:
    lines = filepath.read_text(encoding="utf-8").splitlines()
    current_table = ""
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = _indent_level(line)

        if not stripped:
            i += 1
            continue

        if indent == 0 and stripped.startswith("table "):
            current_table = _parse_declaration_name(stripped, "table")
            snapshot.tables.setdefault(
                _table_key(current_table),
                CompareObject(
                    category="tables",
                    table=current_table,
                    name=current_table,
                    properties={"isHidden": False},
                    source_file=str(filepath),
                ),
            )
            i += 1
            continue

        if not current_table:
            i += 1
            continue

        if indent == 1:
            table = snapshot.tables.setdefault(
                _table_key(current_table),
                CompareObject(
                    category="tables",
                    table=current_table,
                    name=current_table,
                    properties={"isHidden": False},
                    source_file=str(filepath),
                ),
            )
            if _apply_property(stripped, table.properties, allowed_keys=_TABLE_PROPERTY_KEYS):
                i += 1
                continue

            measure = _parse_declaration(stripped, "measure")
            if measure:
                name, first_expression = measure
                props = {"expression": _clean_expression(first_expression), "displayFolder": "", "isHidden": False}
                i = _collect_object_properties(lines, i + 1, props)
                snapshot.measures[(current_table, name)] = CompareObject(
                    category="measures",
                    table=current_table,
                    name=name,
                    properties=props,
                    source_file=str(filepath),
                )
                continue

            column = _parse_declaration(stripped, "column")
            if column:
                name, first_expression = column
                props = {
                    "expression": _clean_expression(first_expression),
                    "displayFolder": "",
                    "isHidden": False,
                    "isKey": False,
                }
                i = _collect_object_properties(lines, i + 1, props)
                snapshot.columns[(current_table, name)] = CompareObject(
                    category="columns",
                    table=current_table,
                    name=name,
                    properties=props,
                    source_file=str(filepath),
                )
                continue

        i += 1


def _collect_object_properties(lines: list[str], start: int, props: dict[str, Any]) -> int:
    expression_lines: list[str] = []
    i = start

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = _indent_level(line)

        if not stripped:
            i += 1
            continue
        if indent <= 1:
            break

        if indent >= 2:
            if _apply_property(stripped, props):
                i += 1
                continue
            cleaned = _clean_expression(stripped)
            if cleaned:
                expression_lines.append(cleaned)
            i += 1
            continue

        i += 1

    if expression_lines:
        existing = str(props.get("expression", "") or "")
        props["expression"] = "\n".join(line for line in [existing, *expression_lines] if line)
    return i


def _compare_category(
    category: str,
    baseline_objects: dict[tuple[str, str], CompareObject],
    candidate_objects: dict[tuple[str, str], CompareObject],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    diffs: list[dict[str, Any]] = []

    for key in sorted(set(baseline_objects) | set(candidate_objects), key=_sort_key):
        baseline = baseline_objects.get(key)
        candidate = candidate_objects.get(key)

        if baseline is None and candidate is not None:
            summary["added"] += 1
            diffs.append(_diff_payload(category, "added", candidate, []))
            continue

        if candidate is None and baseline is not None:
            summary["removed"] += 1
            diffs.append(_diff_payload(category, "removed", baseline, []))
            continue

        if baseline is None or candidate is None:
            continue

        properties = _property_changes(category, baseline, candidate)
        if properties:
            summary["changed"] += 1
            diffs.append(_diff_payload(category, "changed", candidate, properties, baseline=baseline))
        else:
            summary["unchanged"] += 1

    return summary, diffs


def _property_changes(category: str, baseline: CompareObject, candidate: CompareObject) -> list[dict[str, Any]]:
    changes = []
    for name in _PROPERTY_ORDER[category]:
        baseline_value = _property_value(baseline, name)
        candidate_value = _property_value(candidate, name)
        if baseline_value != candidate_value:
            changes.append({
                "name": name,
                "baseline": baseline_value,
                "candidate": candidate_value,
            })
    return changes


def _diff_payload(
    category: str,
    status: str,
    obj: CompareObject,
    properties: list[dict[str, Any]],
    *,
    baseline: CompareObject | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "type": _CATEGORY_LABELS[category],
        "status": status,
        "table": obj.table,
        "name": obj.name,
        "displayName": obj.name if category == "tables" else f"{obj.table}[{obj.name}]",
        "sourceFile": obj.source_file,
        "baselineSourceFile": baseline.source_file if baseline else (obj.source_file if status == "removed" else ""),
        "candidateSourceFile": obj.source_file if status != "removed" else "",
        "properties": properties,
    }


def _property_value(obj: CompareObject, name: str) -> Any:
    if name in _BOOLEAN_PROPERTIES:
        return bool(obj.properties.get(name, False))
    return obj.properties.get(name, "") or ""


def _apply_property(
    raw: str,
    props: dict[str, Any],
    *,
    allowed_keys: set[str] | None = None,
) -> bool:
    if raw in {"hidden", "isHidden"}:
        return _set_allowed(props, allowed_keys, "isHidden", True)
    if raw == "isKey":
        return _set_allowed(props, allowed_keys, "isKey", True)

    if ":" in raw:
        key, value = raw.split(":", 1)
        key = _normalize_property_key(key.strip())
        if key in _PROPERTY_KEYS:
            return _set_allowed(props, allowed_keys, key, _coerce_property_value(key, value.strip()))
        return False

    if "=" in raw:
        key, value = raw.split("=", 1)
        key = _normalize_property_key(key.strip())
        if key in {"expression", "formatStringDefinition"}:
            return _set_allowed(props, allowed_keys, key, _clean_expression(value.strip()))

    return False


_PROPERTY_KEYS = {
    "dataType",
    "displayFolder",
    "expression",
    "formatString",
    "formatStringDefinition",
    "isHidden",
    "isKey",
    "sortByColumn",
    "sourceColumn",
    "summarizeBy",
}


def _set_allowed(
    props: dict[str, Any],
    allowed_keys: set[str] | None,
    key: str,
    value: Any,
) -> bool:
    if allowed_keys is not None and key not in allowed_keys:
        return False
    props[key] = value
    return True


def _normalize_property_key(key: str) -> str:
    if key == "hidden":
        return "isHidden"
    return key


def _coerce_property_value(key: str, value: str) -> Any:
    if key in _BOOLEAN_PROPERTIES:
        return value.lower() == "true"
    if key in {"sourceColumn", "sortByColumn"}:
        return unquote_tmdl_name(value)
    return _clean_scalar(value)


def _parse_declaration(raw: str, keyword: str) -> tuple[str, str] | None:
    prefix = f"{keyword} "
    if not raw.startswith(prefix):
        return None
    name, expression, _ = split_tmdl_name_and_expression(raw[len(prefix):])
    if not name:
        return None
    return name, expression


def _parse_declaration_name(raw: str, keyword: str) -> str:
    declaration = _parse_declaration(raw, keyword)
    if declaration:
        return declaration[0]
    return unquote_tmdl_name(raw[len(keyword) + 1:])


def _clean_expression(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned == "```":
        return ""
    return cleaned


def _clean_scalar(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        if cleaned[0] == "'":
            return unquote_tmdl_name(cleaned)
        return cleaned[1:-1]
    return cleaned


def _indent_level(line: str) -> int:
    tabs = 0
    for ch in line:
        if ch == "\t":
            tabs += 1
            continue
        if ch == " ":
            continue
        break
    if tabs:
        return tabs
    return (len(line) - len(line.lstrip(" "))) // 4


def _table_key(table_name: str) -> tuple[str, str]:
    return table_name, ""


def _sort_key(key: tuple[str, str]) -> tuple[str, str]:
    return key[0].casefold(), key[1].casefold()


def _model_payload(model_path: Path) -> dict[str, str]:
    return {
        "name": model_path.name.replace(".SemanticModel", ""),
        "path": str(model_path),
    }
