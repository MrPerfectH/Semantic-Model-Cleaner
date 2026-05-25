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


def _unquote_tmdl_name(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


def _tmdl_name_pattern(name: str) -> str:
    quoted = "'" + re.escape(name.replace("'", "''")) + "'"
    unquoted = re.escape(name)
    return rf"(?:{quoted}|{unquoted})"


def _quote_dax_table_name(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _quote_dax_object_name(name: str) -> str:
    return name.replace("]", "]]")


def _iter_tmdl_files(model_path: Path) -> list[Path]:
    definition_dir = model_path / "definition"
    if not definition_dir.exists():
        return []
    return sorted(path for path in definition_dir.rglob("*.tmdl") if path.is_file())


def _model_has_column_named(model_path: Path, name: str) -> bool:
    column_pattern = re.compile(r"^\tcolumn\s+(.+?)(?:\s*=.*)?$", re.IGNORECASE)
    for filepath in _iter_tmdl_files(model_path):
        for line in filepath.read_text(encoding="utf-8").splitlines():
            match = column_pattern.match(line)
            if match and _unquote_tmdl_name(match.group(1)).casefold() == name.casefold():
                return True
    return False


def _rewrite_table_name_in_text(text: str, old_table: str, new_table: str) -> tuple[str, int]:
    count = 0
    table_pattern = _tmdl_name_pattern(old_table)
    new_tmdl = _quote_tmdl_name(new_table)
    new_dax = _quote_dax_table_name(new_table)

    def replace_table_decl(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{new_tmdl}"

    text = re.sub(
        rf"^(table\s+){table_pattern}\s*$",
        replace_table_decl,
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    def replace_model_ref(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{new_tmdl}"

    text = re.sub(
        rf"^(ref\s+table\s+){table_pattern}\s*$",
        replace_model_ref,
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    def replace_relationship_ref(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{new_tmdl}."

    text = re.sub(
        rf"^(\t(?:fromColumn|toColumn):\s+){table_pattern}\.",
        replace_relationship_ref,
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    def replace_dax_table_ref(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{new_dax}["

    text = re.sub(
        rf"(?<![A-Za-z0-9_']){table_pattern}\[",
        replace_dax_table_ref,
        text,
        flags=re.IGNORECASE,
    )
    return text, count


def _rewrite_measure_name_in_text(
    text: str,
    table: str,
    old_name: str,
    new_name: str,
    *,
    update_unqualified: bool,
) -> tuple[str, int]:
    count = 0
    table_pattern = _tmdl_name_pattern(table)
    old_object = re.escape(_quote_dax_object_name(old_name))
    new_object = _quote_dax_object_name(new_name)
    table_ref_re = re.compile(
        rf"(?<![A-Za-z0-9_']){table_pattern}\[{old_object}\]",
        flags=re.IGNORECASE,
    )

    def replace_table_qualified(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{_quote_dax_table_name(table)}[{new_object}]"

    text = table_ref_re.sub(replace_table_qualified, text)

    if update_unqualified:
        unqualified_re = re.compile(rf"\[{old_object}\]", flags=re.IGNORECASE)

        def replace_unqualified(match: re.Match) -> str:
            nonlocal count
            count += 1
            return f"[{new_object}]"

        text = unqualified_re.sub(replace_unqualified, text)

    return text, count


def _rewrite_measure_table_ref_in_text(
    text: str,
    old_table: str,
    new_table: str,
    measure_name: str,
) -> tuple[str, int]:
    count = 0
    table_pattern = _tmdl_name_pattern(old_table)
    measure_object = re.escape(_quote_dax_object_name(measure_name))
    new_ref = f"{_quote_dax_table_name(new_table)}[{_quote_dax_object_name(measure_name)}]"
    table_ref_re = re.compile(
        rf"(?<![A-Za-z0-9_']){table_pattern}\[{measure_object}\]",
        flags=re.IGNORECASE,
    )

    def replace_table_qualified(match: re.Match) -> str:
        nonlocal count
        count += 1
        return new_ref

    return table_ref_re.sub(replace_table_qualified, text), count


def _find_item_block(lines: list[str], name: str, item_type: str) -> tuple[int, int] | None:
    """Find start/end line indices for a measure or column block.

    Returns (start, end) where start is the declaration line and end is the last
    line of the block (exclusive — suitable for slicing).
    """
    kind = "measure" if item_type.lower() == "measure" else "column"
    if kind == "measure":
        pattern = re.compile(r"^\tmeasure\s+(.+?)\s*=", re.IGNORECASE)
    else:
        pattern = re.compile(r"^\tcolumn\s+(.+?)(?:\s*=.*)?$", re.IGNORECASE)

    i = 0
    while i < len(lines):
        match = pattern.match(lines[i])
        if match and _unquote_tmdl_name(match.group(1)).casefold() == name.casefold():
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
    for attempt in range(100):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{attempt}" if attempt else ""
        backup_dir = model_path.parent / f"{model_path.name}_backup_{ts}{suffix}"
        try:
            shutil.copytree(model_path, backup_dir)
            return backup_dir
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create a unique backup for {model_path}")


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


def move_measure_to_table(
    model_path: Path,
    table: str,
    name: str,
    target_table: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Move a measure block from one table TMDL file to another."""
    table = table.strip()
    name = name.strip()
    target_table = target_table.strip()
    if not table or not name or not target_table:
        return {"ok": False, "error": "Source table, measure name, and target table are required"}
    if table.casefold() == target_table.casefold():
        return {"ok": False, "error": "Target table must be different from the current table"}

    source_file = _find_tmdl_file(model_path, table)
    if not source_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}
    target_file = _find_tmdl_file(model_path, target_table)
    if not target_file:
        return {"ok": False, "error": f"TMDL file not found for target table '{target_table}'"}

    source_lines = source_file.read_text(encoding="utf-8").splitlines()
    source_block = _find_item_block(source_lines, name, "Measure")
    if not source_block:
        return {"ok": False, "error": f"Measure '{name}' not found in {source_file.name}"}

    target_lines = target_file.read_text(encoding="utf-8").splitlines()
    if _find_item_block(target_lines, name, "Measure"):
        return {"ok": False, "error": f"Target table '{target_table}' already has a measure named '{name}'"}

    start, end = source_block
    measure_block = source_lines[start:end]
    if dry_run:
        return {
            "ok": True,
            "action": "move_measure_to_table",
            "table": table,
            "name": name,
            "target_table": target_table,
            "source_file": str(source_file),
            "target_file": str(target_file),
            "dry_run": True,
            "written": False,
        }

    del source_lines[start:end]
    while source_lines and not source_lines[-1].strip():
        source_lines.pop()

    while target_lines and not target_lines[-1].strip():
        target_lines.pop()
    if target_lines:
        target_lines.append("")
    target_lines.extend(measure_block)

    source_file.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    target_file.write_text("\n".join(target_lines) + "\n", encoding="utf-8")

    changed_ref_files = []
    updated_reference_count = 0
    for filepath in _iter_tmdl_files(model_path):
        text = filepath.read_text(encoding="utf-8")
        new_text, count = _rewrite_measure_table_ref_in_text(text, table, target_table, name)
        if new_text != text:
            filepath.write_text(new_text, encoding="utf-8")
            changed_ref_files.append(str(filepath))
            updated_reference_count += count

    return {
        "ok": True,
        "action": "move_measure_to_table",
        "table": table,
        "name": name,
        "target_table": target_table,
        "source_file": str(source_file),
        "target_file": str(target_file),
        "dry_run": False,
        "written": True,
        "changed_reference_files": changed_ref_files,
        "updated_reference_count": updated_reference_count,
    }


def move_measures_to_tables(
    model_path: Path,
    moves: list[dict],
    *,
    dry_run: bool = False,
) -> dict:
    """Validate and optionally apply a batch of measure table moves."""
    if not moves:
        return {"ok": False, "error": "No measure moves specified", "results": []}

    validation_results = [
        move_measure_to_table(
            model_path,
            str(move.get("table", "") or ""),
            str(move.get("name", "") or ""),
            str(move.get("target_table", "") or ""),
            dry_run=True,
        )
        for move in moves
    ]
    if any(not result.get("ok") for result in validation_results):
        return {
            "ok": False,
            "error": "One or more measure moves are invalid",
            "results": validation_results,
        }

    if dry_run:
        return {
            "ok": True,
            "action": "move_measures_to_tables",
            "dry_run": True,
            "results": validation_results,
            "moved_count": 0,
        }

    snapshots = _snapshot_model_files(model_path)
    results = []
    try:
        for move in moves:
            result = move_measure_to_table(
                model_path,
                str(move.get("table", "") or ""),
                str(move.get("name", "") or ""),
                str(move.get("target_table", "") or ""),
                dry_run=False,
            )
            results.append(result)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Measure move failed")
    except Exception as exc:
        _restore_model_files(model_path, snapshots)
        return {
            "ok": False,
            "error": str(exc),
            "results": results,
            "rolled_back": True,
        }

    return {
        "ok": True,
        "action": "move_measures_to_tables",
        "dry_run": False,
        "results": results,
        "moved_count": len(results),
    }


def rename_measure(
    model_path: Path,
    table: str,
    name: str,
    target_name: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Rename a measure and update semantic-model TMDL references."""
    table = table.strip()
    name = name.strip()
    target_name = target_name.strip()
    if not table or not name or not target_name:
        return {"ok": False, "error": "Table, measure name, and target name are required"}
    if name.casefold() == target_name.casefold():
        return {"ok": False, "error": "Target measure name must be different"}

    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}

    lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    block = _find_item_block(lines, name, "Measure")
    if not block:
        return {"ok": False, "error": f"Measure '{name}' not found in {tmdl_file.name}"}
    if _find_item_block(lines, target_name, "Measure"):
        return {"ok": False, "error": f"Table '{table}' already has a measure named '{target_name}'"}

    update_unqualified = not _model_has_column_named(model_path, name)
    changed_files = []
    reference_count = 0

    source_start, _ = block
    source_match = re.match(r"^(\tmeasure\s+)(.+?)(\s*=.*)$", lines[source_start], re.IGNORECASE)
    if not source_match:
        return {"ok": False, "error": f"Measure declaration not recognized for '{name}'"}

    for filepath in _iter_tmdl_files(model_path):
        text = filepath.read_text(encoding="utf-8")
        new_text = text
        count = 0
        if filepath == tmdl_file:
            file_lines = new_text.splitlines()
            current_block = _find_item_block(file_lines, name, "Measure")
            if current_block:
                start, _ = current_block
                match = re.match(r"^(\tmeasure\s+)(.+?)(\s*=.*)$", file_lines[start], re.IGNORECASE)
                if match:
                    file_lines[start] = f"{match.group(1)}{_quote_tmdl_name(target_name)}{match.group(3)}"
                    new_text = "\n".join(file_lines) + ("\n" if text.endswith("\n") else "")
                    count += 1

        new_text, ref_count = _rewrite_measure_name_in_text(
            new_text,
            table,
            name,
            target_name,
            update_unqualified=update_unqualified,
        )
        count += ref_count
        if new_text != text:
            reference_count += count
            changed_files.append(str(filepath))
            if not dry_run:
                filepath.write_text(new_text, encoding="utf-8")

    return {
        "ok": True,
        "action": "rename_measure",
        "table": table,
        "name": name,
        "target_name": target_name,
        "dry_run": dry_run,
        "changed_files": changed_files,
        "updated_reference_count": reference_count,
        "updated_unqualified_refs": update_unqualified,
        "warnings": [] if update_unqualified else [f"Skipped unqualified [{name}] rewrites because a column with the same name exists."],
    }


def rename_table(
    model_path: Path,
    table: str,
    target_table: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Rename a table TMDL file/declaration and semantic-model references."""
    table = table.strip()
    target_table = target_table.strip()
    if not table or not target_table:
        return {"ok": False, "error": "Table and target table are required"}
    if table.casefold() == target_table.casefold():
        return {"ok": False, "error": "Target table name must be different"}

    source_file = _find_tmdl_file(model_path, table)
    if not source_file:
        return {"ok": False, "error": f"TMDL file not found for table '{table}'"}
    if _find_tmdl_file(model_path, target_table):
        return {"ok": False, "error": f"Table '{target_table}' already exists"}

    target_file = source_file.with_name(f"{target_table}.tmdl")
    if target_file.exists():
        return {"ok": False, "error": f"Target TMDL file already exists: {target_file.name}"}

    changed_files = []
    reference_count = 0
    for filepath in _iter_tmdl_files(model_path):
        text = filepath.read_text(encoding="utf-8")
        new_text, count = _rewrite_table_name_in_text(text, table, target_table)
        if new_text != text:
            reference_count += count
            changed_files.append(str(target_file if filepath == source_file else filepath))
            if not dry_run:
                filepath.write_text(new_text, encoding="utf-8")

    if not dry_run:
        source_file.rename(target_file)

    return {
        "ok": True,
        "action": "rename_table",
        "table": table,
        "target_table": target_table,
        "source_file": str(source_file),
        "target_file": str(target_file),
        "dry_run": dry_run,
        "changed_files": changed_files,
        "updated_reference_count": reference_count,
        "warnings": [],
    }


def rename_model_metadata(
    model_path: Path,
    *,
    table_renames: list[dict] | None = None,
    measure_renames: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Validate and optionally apply table/measure renames in the semantic model."""
    table_renames = table_renames or []
    measure_renames = measure_renames or []
    if not table_renames and not measure_renames:
        return {"ok": False, "error": "No table or measure renames specified", "results": []}

    validation_results = []
    for rename in table_renames:
        validation_results.append(rename_table(
            model_path,
            str(rename.get("table", "") or ""),
            str(rename.get("target_table", "") or ""),
            dry_run=True,
        ))
    for rename in measure_renames:
        validation_results.append(rename_measure(
            model_path,
            str(rename.get("table", "") or ""),
            str(rename.get("name", "") or ""),
            str(rename.get("target_name", "") or ""),
            dry_run=True,
        ))
    if any(not result.get("ok") for result in validation_results):
        return {
            "ok": False,
            "error": "One or more model renames are invalid",
            "results": validation_results,
        }

    if dry_run:
        return {
            "ok": True,
            "action": "rename_model_metadata",
            "dry_run": True,
            "results": validation_results,
        }

    snapshots = _snapshot_model_files(model_path)
    results = []
    try:
        for rename in table_renames:
            result = rename_table(
                model_path,
                str(rename.get("table", "") or ""),
                str(rename.get("target_table", "") or ""),
                dry_run=False,
            )
            results.append(result)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Table rename failed")
        for rename in measure_renames:
            table_name = str(rename.get("table", "") or "")
            for table_result in results:
                if (
                    table_result.get("action") == "rename_table"
                    and table_name.casefold() == str(table_result.get("table", "")).casefold()
                ):
                    table_name = str(table_result.get("target_table", "") or table_name)
            result = rename_measure(
                model_path,
                table_name,
                str(rename.get("name", "") or ""),
                str(rename.get("target_name", "") or ""),
                dry_run=False,
            )
            results.append(result)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Measure rename failed")
    except Exception as exc:
        _restore_model_files(model_path, snapshots)
        return {
            "ok": False,
            "error": str(exc),
            "results": results,
            "rolled_back": True,
        }

    return {
        "ok": True,
        "action": "rename_model_metadata",
        "dry_run": False,
        "results": results,
    }


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
    table_pattern = _tmdl_name_pattern(table)
    col_pattern = _tmdl_name_pattern(column)
    ref_pattern = re.compile(
        rf"(?:fromColumn|toColumn):\s+"
        rf"{table_pattern}\.{col_pattern}\s*$",
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
    # Match: ref table TableName  or  ref table 'Table Name'
    pattern = re.compile(rf"^ref\s+table\s+{_tmdl_name_pattern(table)}\s*$", re.IGNORECASE)

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

    table_pattern = _tmdl_name_pattern(table)
    ref_pattern = re.compile(
        rf"(?:fromColumn|toColumn):\s+{table_pattern}\.",
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
    validation_results = [_validate_action(model_path, act) for act in actions]
    if any(not result["ok"] for result in validation_results):
        return [
            {
                **result,
                "ok": False,
                "validated": False,
                "written": False,
                "skipped": result["ok"],
                "error": result.get("error") or "Skipped because another action in the batch is invalid.",
            }
            for result in validation_results
        ]

    snapshots = _snapshot_model_files(model_path)
    results = []
    for act in actions:
        action = act["action"]
        table = act["table"]
        name = act["name"]
        item_type = act["item_type"]

        try:
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
        except Exception as exc:
            r = {"ok": False, "error": str(exc)}

        r.update({
            "table": table,
            "name": name,
            "item_type": item_type,
            "validated": True,
            "written": bool(r.get("ok")),
        })
        results.append(r)

        if not r.get("ok"):
            _restore_model_files(model_path, snapshots)
            return [
                {
                    **result,
                    "written": False,
                    "rolled_back": True,
                    "error": result.get("error") or "Rolled back because another action in the batch failed.",
                }
                for result in results
            ]

    return results


def _validate_action(model_path: Path, act: dict) -> dict:
    action = act.get("action")
    table = act.get("table")
    name = act.get("name")
    item_type = act.get("item_type")
    result = {
        "ok": True,
        "action": action,
        "table": table,
        "name": name,
        "item_type": item_type,
    }

    if action not in ("move_to_folder", "move_to_table_group", "hide", "unhide", "delete"):
        return {**result, "ok": False, "error": f"Unknown action '{action}'"}
    for field_name, value in (("table", table), ("name", name), ("item_type", item_type)):
        if not value:
            return {**result, "ok": False, "error": f"Missing field '{field_name}' in action"}

    tmdl_file = _find_tmdl_file(model_path, table)
    if not tmdl_file:
        return {**result, "ok": False, "error": f"TMDL file not found for table '{table}'"}

    try:
        lines = tmdl_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {**result, "ok": False, "error": str(exc)}

    if action == "move_to_table_group":
        if not any(re.match(r"^table\s+", line) for line in lines):
            return {**result, "ok": False, "error": f"Table declaration not found in {tmdl_file.name}"}
        return result

    if not _find_item_block(lines, name, item_type):
        return {**result, "ok": False, "error": f"Item '{name}' not found in {tmdl_file.name}"}
    return result


def _snapshot_model_files(model_path: Path) -> dict[Path, str | None]:
    definition_dir = model_path / "definition"
    if not definition_dir.exists():
        return {}
    files = {path for path in definition_dir.rglob("*.tmdl") if path.is_file()}
    snapshot: dict[Path, str | None] = {}
    for path in files:
        snapshot[path] = path.read_text(encoding="utf-8")
    return snapshot


def _restore_model_files(model_path: Path, snapshot: dict[Path, str | None]) -> None:
    definition_dir = model_path / "definition"
    current_files = {path for path in definition_dir.rglob("*.tmdl") if path.is_file()} if definition_dir.exists() else set()

    for path in current_files - set(snapshot):
        path.unlink()

    for path, content in snapshot.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(content, encoding="utf-8")
