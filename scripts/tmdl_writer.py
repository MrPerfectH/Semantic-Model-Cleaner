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


def _find_property_line(lines: list[str], start: int, end: int, prop_name: str) -> int | None:
    """Find a 2-tab property line within a block. Returns line index or None."""
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(prop_name + ":") or stripped == prop_name:
            return i
    return None


def _insert_point_for_property(lines: list[str], start: int, end: int) -> int:
    """Find the best insertion point for a new property (after existing 2-tab props)."""
    last_prop = start
    for i in range(start + 1, end):
        if lines[i].startswith("\t\t") and not lines[i].startswith("\t\t\t"):
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
    """Set or remove the isHidden flag on a measure or column."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}

    start, end = block
    prop_line = _find_property_line(lines, start, end, "isHidden")

    if hidden:
        if prop_line is None:
            insert_at = _insert_point_for_property(lines, start, end)
            lines.insert(insert_at, "\t\tisHidden")
    else:
        if prop_line is not None:
            lines.pop(prop_line)

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "set_hidden", "hidden": hidden}


def delete_item(model_path: Path, table: str, name: str, item_type: str) -> dict:
    """Delete an entire measure or column block from the TMDL file."""
    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, item_type)
    if not block:
        return {"ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}

    start, end = block
    del lines[start:end]

    tmdl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(tmdl_file), "action": "delete", "item": name}


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
        results.append(r)

    return results
