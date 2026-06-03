"""Helpers for TMDL and DAX identifiers."""

from __future__ import annotations

import re


_SIMPLE_TMDL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def quote_tmdl_name(name: str) -> str:
    """Return a TMDL-safe object name."""
    if _SIMPLE_TMDL_NAME_RE.fullmatch(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def quote_dax_table_name(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def quote_dax_object_name(name: str) -> str:
    return name.replace("]", "]]")


def read_single_quoted_name(text: str, start: int = 0) -> tuple[str, int] | None:
    """Read a single-quoted TMDL/DAX name, where '' escapes an apostrophe."""
    if start >= len(text) or text[start] != "'":
        return None

    chars: list[str] = []
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if i + 1 < len(text) and text[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return "".join(chars), i + 1
        chars.append(ch)
        i += 1

    return None


def unquote_tmdl_name(value: str) -> str:
    raw = value.strip()
    parsed = read_single_quoted_name(raw)
    if parsed:
        name, end = parsed
        if not raw[end:].strip():
            return name
    return raw


def split_tmdl_name_and_expression(value: str) -> tuple[str, str, bool]:
    """Split declaration text after a keyword into name, expression, has_expression."""
    raw = value.strip()
    if raw.startswith("'"):
        parsed = read_single_quoted_name(raw)
        if parsed:
            name, end = parsed
            rest = raw[end:].lstrip()
            if rest.startswith("="):
                return name, rest[1:].strip(), True
            return name, rest, False

    if "=" in raw:
        name, expression = raw.split("=", 1)
        return name.strip(), expression.strip(), True
    return raw, "", False


def tmdl_name_pattern(name: str) -> str:
    quoted = "'" + re.escape(name.replace("'", "''")) + "'"
    unquoted = re.escape(name)
    return rf"(?:{quoted}|{unquoted})"


def parse_tmdl_dotted_ref(value: str) -> tuple[str, str] | None:
    raw = value.strip()
    table_part = _read_tmdl_ref_part(raw, 0, stop_chars=".")
    if not table_part:
        return None
    table, pos = table_part

    pos = _skip_whitespace(raw, pos)
    if pos >= len(raw) or raw[pos] != ".":
        return None
    column_part = _read_tmdl_ref_part(raw, pos + 1, stop_chars="")
    if not column_part:
        return None
    column, end = column_part

    if raw[end:].strip():
        return None
    return table, column


def _read_tmdl_ref_part(text: str, start: int, *, stop_chars: str) -> tuple[str, int] | None:
    start = _skip_whitespace(text, start)
    if start >= len(text):
        return None

    if text[start] == "'":
        return read_single_quoted_name(text, start)

    i = start
    while i < len(text):
        ch = text[i]
        if ch.isspace() or (stop_chars and ch in stop_chars):
            break
        i += 1

    name = text[start:i].strip()
    if not name:
        return None
    return name, i


def _skip_whitespace(text: str, start: int) -> int:
    i = start
    while i < len(text) and text[i].isspace():
        i += 1
    return i
