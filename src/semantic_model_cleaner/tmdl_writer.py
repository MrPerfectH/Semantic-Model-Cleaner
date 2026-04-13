#!/usr/bin/env python3
"""
TMDL Writer Engine

Line-based read-modify-write operations on Power BI TMDL files.
Supports: set display folder, set hidden, delete item.
Creates timestamped backups and validates after each write.
"""

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


# ── Locate item in TMDL file ─────────────────────────────────────────────────


def _find_tmdl_file(model_path: Path, table: str) -> Path | None:
    """Find the TMDL file for a given table name."""
    tables_dir = model_path / "definition" / "tables"
    if not tables_dir.exists():
        return None
    # Try exact match first, then case-insensitive
    for f in tables_dir.glob("*.tmdl"):
        stem = f.stem
        if stem == table or stem.casefold() == table.casefold():
            return f
    return None


def _quote_tmdl_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _find_item_block(lines: list[str], name: str, item_type: str) -> tuple[int, int] | None:
    """Find start/end line indices for a measure or column block.

    Returns (start, end) where start is the declaration line and end is the last
    line of the block (exclusive — suitable for slicing).
    """
    kind = "measure" if item_type.lower() == "measure" else "column"
    # Patterns: \tmeasure 'Name' = ... or \tcolumn 'Name'
    escaped = re.escape(name)
    if kind == "measure":
        pattern = re.compile(rf"^\tmeasure\s+'?{escaped}'?\s*=", re.IGNORECASE)
    else:
        pattern = re.compile(rf"^\tcolumn\s+'?{escaped}'?\s*$", re.IGNORECASE)

    i = 0
    while i < len(lines):
        if pattern.match(lines[i]):
            start = i
            i += 1
            # Consume all 2-tab and 3-tab property/DAX lines, plus blank lines within block
            while i < len(lines):
                line = lines[i]
                if line == "" or line.strip() == "":
                    # Blank lines inside a block — peek ahead to see if block continues
                    j = i + 1
                    while j < len(lines) and (lines[j] == "" or lines[j].strip() == ""):
                        j += 1
                    if j < len(lines) and lines[j].startswith("\t\t"):
                        i = j
                        continue
                    else:
                        break
                if line.startswith("\t\t"):
                    i += 1
                    continue
                break
            # Include trailing blank lines that are part of item separation
            while i < len(lines) and (lines[i] == "" or lines[i].strip() == ""):
                i += 1
            return (start, i)
        i += 1
    return None


def _find_property_line(
    lines: list[str], start: int, end: int, prop_name: str | tuple[str, ...]
) -> int | None:
    """Find a 2-tab property line within a block. Returns line index or None."""
    prop_names = (prop_name,) if isinstance(prop_name, str) else prop_name
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        for candidate in prop_names:
            if stripped.startswith(candidate + ":") or stripped == candidate:
                return i
    return None


def _insert_point_for_property(lines: list[str], start: int, end: int) -> int:
    """Find the best insertion point for a new property (after existing 2-tab props,
    but before sub-objects like annotations, changedProperties, etc.)."""
    last_prop = start
    for i in range(start + 1, end):
        line = lines[i]
        if not line.startswith("\t\t") or line.startswith("\t\t\t"):
            continue
        stripped = line.strip()
        # Sub-object declarations (annotation, changedProperty, etc.) come after properties
        if stripped.startswith("annotation ") or stripped.startswith("changedProperty "):
            break
        last_prop = i
    return last_prop + 1


# ── Backup & Safety ──────────────────────────────────────────────────────────


def create_backup(model_path: Path) -> Path:
    """Create a timestamped copy of the .SemanticModel directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = model_path.parent / f"{model_path.name}_backup_{ts}"
    shutil.copytree(model_path, backup_dir)
    return backup_dir


def check_git_dirty(model_path: Path) -> str | None:
    """Check if the model directory has uncommitted changes. Returns warning or None."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(model_path)],
            capture_output=True, text=True, timeout=10,
            cwd=model_path.parent
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"Working directory has uncommitted changes:\n{result.stdout.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ── Write Operations ─────────────────────────────────────────────────────────


def set_display_folder(model_path: Path, table: str, name: str,
                       item_type: str, folder: str) -> dict:
    """Set or change the displayFolder property of a measure or column."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}

    start, end = block
    prop_line = _find_property_line(lines, start, end, "displayFolder")

    if prop_line is not None:
        if folder:
            lines[prop_line] = f"\t\tdisplayFolder: {folder}"
        else:
            # Remove displayFolder if folder is empty
            lines.pop(prop_line)
    elif folder:
        insert_at = _insert_point_for_property(lines, start, end)
        lines.insert(insert_at, f"\t\tdisplayFolder: {folder}")

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "set_display_folder", "folder": folder}


def set_hidden(model_path: Path, table: str, name: str,
               item_type: str, hidden: bool = True) -> dict:
    """Set hidden property on a measure or column using modern TMDL syntax."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}

    start, end = block
    prop_line = _find_property_line(lines, start, end, ("hidden", "isHidden"))

    if hidden:
        if prop_line is None:
            insert_at = _insert_point_for_property(lines, start, end)
            lines.insert(insert_at, "\t\tisHidden")
        else:
            lines[prop_line] = "\t\tisHidden"
    else:
        # isHidden defaults to false — just remove the line
        if prop_line is not None:
            del lines[prop_line]

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "set_hidden", "hidden": hidden}


def set_table_group(model_path: Path, table: str, group_name: str) -> dict:
    """Set or change the Tabular Editor table-group annotation on a table."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {"ok": False, "error": f"TMDL file is empty for table '{table}'"}

    table_line = None
    for i, line in enumerate(lines):
        if re.match(r"^table\s+", line):
            table_line = i
            break
    if table_line is None:
        return {"ok": False, "error": f"Table declaration not found in {tmdl_file.name}"}

    annotation_name = "TabularEditor_TableGroup"
    annotation_pattern = re.compile(
        rf"^\tannotation\s+{re.escape(annotation_name)}\s*=\s*.*$",
        re.IGNORECASE,
    )
    annotation_line = None
    for i in range(table_line + 1, len(lines)):
        if annotation_pattern.match(lines[i]):
            annotation_line = i
            break

    if annotation_line is not None:
        if group_name:
            lines[annotation_line] = f"\tannotation {annotation_name} = {group_name}"
        else:
            lines.pop(annotation_line)
    elif group_name:
        lines.insert(table_line + 1, f"\tannotation {annotation_name} = {group_name}")

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "file": str(tmdl_file),
        "action": "set_table_group",
        "table_group": group_name,
    }


def create_measure(
    model_path: Path,
    table: str,
    name: str,
    dax_expression: str,
    *,
    display_folder: str = "",
    format_string: str = "",
    hidden: bool = False,
) -> dict:
    """Append a new measure block to an existing table file."""
    expression_lines = _normalize_expression_lines(dax_expression)
    if not expression_lines:
        return {"ok": False, "error": "DAX expression cannot be empty"}

    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    if _find_item_block(lines, name, "Measure"):
        return {"ok": False, "error": f"Item '{name}' already exists in {tmdl_file.name}"}

    new_lines = list(lines)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    if new_lines:
        new_lines.append("")

    new_lines.append(f"\tmeasure {_quote_tmdl_name(name)} = {expression_lines[0]}")
    new_lines.extend(f"\t\t\t{line}" for line in expression_lines[1:])
    if format_string:
        new_lines.append(f"\t\tformatString: {format_string}")
    if display_folder:
        new_lines.append(f"\t\tdisplayFolder: {display_folder}")
    if hidden:
        new_lines.append("\t\tisHidden")

    tmdl_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "create_measure"}


def _normalize_expression_lines(dax_expression: str) -> list[str]:
    lines = [line.rstrip() for line in str(dax_expression).splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def set_dax_expression(
    model_path: Path,
    table: str,
    name: str,
    item_type: str,
    dax_expression: str,
) -> dict:
    """Replace DAX expression for a measure or calculated column."""
    if item_type not in ("Measure", "Calculated Column"):
        return {"ok": False, "error": "Only Measure and Calculated Column are supported"}

    expression_lines = _normalize_expression_lines(dax_expression)
    if not expression_lines:
        return {"ok": False, "error": "DAX expression cannot be empty"}

    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}
    start, end = block

    if item_type == "Measure":
        declaration = lines[start]
        match = re.match(r"^(\tmeasure\s+.+?=)\s*(.*)$", declaration, re.IGNORECASE)
        if not match:
            return {"ok": False, "error": f"Measure declaration not recognized for '{name}'"}

        new_declaration = f"{match.group(1)} {expression_lines[0]}"
        continuation = [f"\t\t\t{line}" for line in expression_lines[1:]]

        i = start + 1
        while i < end and (lines[i].startswith("\t\t\t") or not lines[i].strip()):
            i += 1
        remainder = lines[i:end]

        lines = lines[:start] + [new_declaration] + continuation + remainder + lines[end:]
    else:
        expr_line_idx = None
        for i in range(start + 1, end):
            line = lines[i]
            if line.startswith("\t\t") and not line.startswith("\t\t\t"):
                stripped = line.strip()
                if "expression" in stripped and "=" in stripped and not stripped.startswith("formatString"):
                    expr_line_idx = i
                    break
        if expr_line_idx is None:
            return {"ok": False, "error": f"Calculated column expression block not found for '{name}'"}

        prop_prefix = lines[expr_line_idx].split("=", 1)[0].rstrip()
        new_expr_line = f"{prop_prefix} = {expression_lines[0]}"
        continuation = [f"\t\t\t{line}" for line in expression_lines[1:]]

        j = expr_line_idx + 1
        while j < end and (lines[j].startswith("\t\t\t") or not lines[j].strip()):
            j += 1

        lines = lines[:expr_line_idx] + [new_expr_line] + continuation + lines[j:]

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "set_dax_expression"}


def _delete_relationships_for_column(model_path: Path, table: str, column: str) -> list[str]:
    """Remove any relationship blocks from relationships.tmdl that reference
    the given table + column (on either fromColumn or toColumn side).

    Returns list of removed relationship identifiers.
    """
    rel_file = model_path / "definition" / "relationships.tmdl"
    if not rel_file.exists():
        return []

    lines = rel_file.read_text(encoding="utf-8").splitlines()

    # Build a reference pattern that matches Table.column in either quoted or unquoted form
    # fromColumn: 'Table'.column  |  Table.column  |  Table.'column'
    escaped_table = re.escape(table)
    escaped_col = re.escape(column)
    ref_pattern = re.compile(
        rf"(?:fromColumn|toColumn):\s+"
        rf"(?:'{escaped_table}'|{escaped_table})\.(?:'{escaped_col}'|{escaped_col})\s*$",
        re.IGNORECASE,
    )

    # Parse relationship blocks and identify ones to remove
    blocks_to_remove: list[tuple[int, int, str]] = []  # (start, end, name)
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("relationship ") or line.startswith("relationship\t"):
            block_start = i
            rel_name = line.strip()
            i += 1
            matches_column = False
            while i < len(lines):
                inner = lines[i]
                if inner == "" or inner.strip() == "":
                    j = i + 1
                    while j < len(lines) and (lines[j] == "" or lines[j].strip() == ""):
                        j += 1
                    if j < len(lines) and lines[j].startswith("\t"):
                        i = j
                        continue
                    else:
                        break
                if inner.startswith("\t"):
                    if ref_pattern.search(inner):
                        matches_column = True
                    i += 1
                    continue
                break
            # Consume trailing blank lines
            while i < len(lines) and (lines[i] == "" or lines[i].strip() == ""):
                i += 1
            if matches_column:
                blocks_to_remove.append((block_start, i, rel_name))
        else:
            i += 1

    if not blocks_to_remove:
        return []

    # Remove blocks in reverse order to preserve indices
    removed = []
    for start, end, rel_name in reversed(blocks_to_remove):
        del lines[start:end]
        removed.append(rel_name)

    rel_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return removed


def _delete_table_ref_from_model(model_path: Path, table: str) -> bool:
    """Remove the 'ref table' line for the given table from model.tmdl.
    Returns True if a line was removed."""
    model_file = model_path / "definition" / "model.tmdl"
    if not model_file.exists():
        return False

    lines = model_file.read_text(encoding="utf-8").splitlines()
    escaped = re.escape(table)
    # Match: ref table TableName  or  ref table 'Table Name'
    pattern = re.compile(rf"^ref\s+table\s+(?:'{escaped}'|{escaped})\s*$", re.IGNORECASE)

    new_lines = [line for line in lines if not pattern.match(line)]
    if len(new_lines) == len(lines):
        return False

    model_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def _table_has_items(lines: list[str]) -> bool:
    """Check if a TMDL table file still has any column or measure declarations."""
    for line in lines:
        if re.match(r"^\tcolumn\s+", line) or re.match(r"^\tmeasure\s+", line):
            return True
    return False


def _delete_all_relationships_for_table(model_path: Path, table: str) -> list[str]:
    """Remove all relationship blocks from relationships.tmdl that reference
    the given table on either side. Returns list of removed relationship identifiers."""
    rel_file = model_path / "definition" / "relationships.tmdl"
    if not rel_file.exists():
        return []

    lines = rel_file.read_text(encoding="utf-8").splitlines()

    escaped_table = re.escape(table)
    ref_pattern = re.compile(
        rf"(?:fromColumn|toColumn):\s+(?:'{escaped_table}'|{escaped_table})\.",
        re.IGNORECASE,
    )

    blocks_to_remove: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("relationship ") or line.startswith("relationship\t"):
            block_start = i
            rel_name = line.strip()
            i += 1
            matches_table = False
            while i < len(lines):
                inner = lines[i]
                if inner == "" or inner.strip() == "":
                    j = i + 1
                    while j < len(lines) and (lines[j] == "" or lines[j].strip() == ""):
                        j += 1
                    if j < len(lines) and lines[j].startswith("\t"):
                        i = j
                        continue
                    else:
                        break
                if inner.startswith("\t"):
                    if ref_pattern.search(inner):
                        matches_table = True
                    i += 1
                    continue
                break
            while i < len(lines) and (lines[i] == "" or lines[i].strip() == ""):
                i += 1
            if matches_table:
                blocks_to_remove.append((block_start, i, rel_name))
        else:
            i += 1

    if not blocks_to_remove:
        return []

    removed = []
    for start, end, rel_name in reversed(blocks_to_remove):
        del lines[start:end]
        removed.append(rel_name)

    rel_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return removed


def delete_item(model_path: Path, table: str, name: str, item_type: str) -> dict:
    """Delete an entire measure or column block from the TMDL file.
    If the item is a column, also removes any relationships referencing it.
    If the table has no remaining columns or measures, deletes the table file
    and all its relationships."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}

    start, end = block
    del lines[start:end]

    result = {"ok": True, "file": str(tmdl_file), "action": "delete", "item": name}

    # If deleting a column, also clean up any relationships referencing it
    if item_type.lower() in ("column", "calculated column"):
        removed_rels = _delete_relationships_for_column(model_path, table, name)
        if removed_rels:
            result["removed_relationships"] = removed_rels

    # Check if the table has any remaining columns or measures
    if not _table_has_items(lines):
        # Remove the table file entirely
        tmdl_file.unlink()
        result["table_deleted"] = True
        # Remove all remaining relationships for this table
        removed_table_rels = _delete_all_relationships_for_table(model_path, table)
        if removed_table_rels:
            existing = result.get("removed_relationships", [])
            result["removed_relationships"] = existing + removed_table_rels
        # Remove the ref table line from model.tmdl
        _delete_table_ref_from_model(model_path, table)
    else:
        tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return result


# ── Batch Operations ─────────────────────────────────────────────────────────


def apply_actions(model_path: Path, actions: list[dict]) -> list[dict]:
    """Apply a batch of actions. Each action dict:
    {
        "action": "move_to_folder" | "move_to_table_group" | "hide" | "unhide" | "delete",
        "table": str,
        "name": str,
        "item_type": str,  # "Measure", "Column", "Calculated Column", "Table"
        "folder": str,     # only for move_to_folder
        "table_group": str # only for move_to_table_group
    }
    Returns list of result dicts.
    """
    results = []
    for act in actions:
        action = act["action"]
        table = act["table"]
        name = act["name"]
        item_type = act["item_type"]

        if action == "move_to_folder":
            r = set_display_folder(model_path, table, name, item_type, act.get("folder", ""))
        elif action == "move_to_table_group":
            r = set_table_group(model_path, table, act.get("table_group", ""))
        elif action == "hide":
            r = set_hidden(model_path, table, name, item_type, hidden=True)
        elif action == "unhide":
            r = set_hidden(model_path, table, name, item_type, hidden=False)
        elif action == "delete":
            r = delete_item(model_path, table, name, item_type)
        else:
            r = {"ok": False, "error": f"Unknown action '{action}'"}

        r["table"] = table
        r["name"] = name
        r["item_type"] = item_type
        results.append(r)

    return results
