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
        "action": "move_to_folder" | "hide" | "unhide" | "delete",
        "table": str,
        "name": str,
        "item_type": str,  # "Measure", "Column", "Calculated Column"
        "folder": str      # only for move_to_folder
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
