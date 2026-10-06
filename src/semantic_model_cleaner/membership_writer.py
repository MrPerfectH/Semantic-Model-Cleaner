"""Conservative, byte-preserving edits to perspective and culture references.

Only the supported declaration tree is editable. Unknown structure blocks the
operation rather than leaving a reference behind or rewriting prose/payloads.
Expression payloads (including linguistic metadata) remain opaque.
"""
from pathlib import Path
import re

from .tmdl_declarations import scan_tmdl_declarations
from .tmdl_identifiers import quote_tmdl_name, read_single_quoted_name


class MembershipError(ValueError):
    pass


_CHILDREN = {
    "perspective": {"perspectiveTable"},
    "perspectiveTable": {"perspectiveMeasure", "perspectiveColumn", "perspectiveHierarchy"},
    "perspectiveMeasure": set(), "perspectiveColumn": set(), "perspectiveHierarchy": set(),
    "culture": {"translations", "linguisticMetadata"},
    "cultureInfo": {"translations", "linguisticMetadata"},
    "translations": {"model", "table"},
    "model": {"table"},
    "table": {"measure", "column", "hierarchy"},
    "measure": set(), "column": set(), "hierarchy": {"level"}, "level": set(),
}
_TRANSLATED_PROPERTIES = {"caption", "description", "displayFolder",
                          "translatedCaption", "translatedDescription", "translatedDisplayFolder"}
_TRANSLATED_OBJECTS = {"model", "table", "measure", "column", "hierarchy", "level"}
_OPAQUE = {"annotation", "extendedProperty", "linguisticMetadata"}
_CANONICAL = {key.casefold(): key for key in
              _CHILDREN.keys() | _TRANSLATED_PROPERTIES | _OPAQUE | {"contentType", "type"}}


def is_membership_file(model_path: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to((model_path / "definition").resolve())
    except ValueError:
        return False
    return len(relative.parts) > 1 and relative.parts[0].casefold() in {"perspectives", "cultures"}


def _parse(text, family):
    declarations = scan_tmdl_declarations(text, strict=True)
    roots = {"perspective"} if family == "perspectives" else {"culture", "cultureInfo"}
    if not declarations:
        raise ValueError("no perspective/culture declaration")
    for node in declarations:
        node.keyword = _CANONICAL.get(node.keyword.casefold(), node.keyword)
        parent = node.parent
        if parent is None:
            allowed = node.keyword in roots
        elif parent.keyword in _OPAQUE:
            allowed = node.kind == "value" and node.keyword in {"contentType", "type"}
        elif node.keyword in _OPAQUE:
            allowed = (node.keyword != "linguisticMetadata" or
                       parent.keyword in {"culture", "cultureInfo"}) and node.has_expression
        elif node.kind == "value":
            allowed = node.keyword in (_TRANSLATED_PROPERTIES if parent.keyword in
                                        _TRANSLATED_OBJECTS else {"description"})
        else:
            allowed = node.keyword in _CHILDREN.get(parent.keyword, set())
        if not allowed:
            raise ValueError(f"line {node.line}: unsupported {node.keyword} declaration or parent")
        if node.keyword in _CHILDREN:
            if node.kind != "object" or node.has_expression or bool(node.name) == (node.keyword == "translations"):
                raise ValueError(f"line {node.line}: malformed {node.keyword} declaration")
        if node.keyword in _OPAQUE and not node.has_expression:
            raise ValueError(f"line {node.line}: missing {node.keyword} expression")
    return declarations


def _documents(model_path):
    for family in ("perspectives", "cultures"):
        directory = model_path / "definition" / family
        for path in sorted(directory.rglob("*.tmdl")):
            try:
                text = path.read_bytes().decode("utf-8")
                declarations = _parse(text, family)
            except (OSError, UnicodeError, ValueError) as exc:
                location = path.relative_to(model_path).as_posix()
                raise MembershipError(f"Blocked: cannot safely edit {location}: {exc}") from exc
            yield path, text, declarations


def validate_membership_files(model_path: Path) -> None:
    """Preflight every file: malformed text cannot prove absence of a reference."""
    for _ in _documents(model_path):
        pass


def _span(node, lines):
    start = node.line - 1
    # Triple-slash descriptions belong to the following declaration. Other
    # comments and blank lines outside the removed block keep their exact bytes.
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    while start and lines[start - 1].startswith(indent + "///"):
        start -= 1
    end = node.end_line
    pending = list(node.children)
    while pending:
        child = pending.pop()
        end = max(end, child.end_line)
        pending.extend(child.children)
    return start, end


def _rename_line(line, new_name):
    match = re.match(r"(\s*\w+\s+)(.*?)(\r?\n)?$", line)
    rest = match.group(2)
    parsed = read_single_quoted_name(rest)
    end = parsed[1] if parsed else len(rest.rstrip())
    return match.group(1) + quote_tmdl_name(new_name) + rest[end:] + (match.group(3) or "")


def prepare_membership_edits(model_path: Path, *, table: str, name: str = "",
                             item_type: str = "Table", target_name: str | None = None,
                             delete_table: bool = False) -> dict[Path, bytes]:
    """Return changed files without writing; None target means deletion.

    Table deletion also removes all child membership/translation declarations.
    After item deletion an empty culture table is pruned; perspective table
    membership survives while the model table itself still exists.
    """
    item_kind = {"measure": "measure", "column": "column", "calculated column": "column",
                 "hierarchy": "hierarchy", "table": "table"}[item_type.casefold()]
    pending = {}
    for path, text, declarations in _documents(model_path):
        lines = text.splitlines(keepends=True)
        removed = set()
        renamed = {}
        for table_node in declarations:
            if table_node.keyword not in {"table", "perspectiveTable"} or table_node.name.casefold() != table.casefold():
                continue
            if item_kind == "table" or delete_table:
                targets = [table_node]
            else:
                keyword = ("perspective" + item_kind.capitalize()
                           if table_node.keyword == "perspectiveTable" else item_kind)
                targets = [child for child in table_node.children if child.keyword == keyword
                           and child.name.casefold() == name.casefold()]
            if target_name is not None:
                for target in targets:
                    renamed[target.line - 1] = _rename_line(lines[target.line - 1], target_name)
            else:
                for target in targets:
                    removed.update(range(*_span(target, lines)))
                if targets and table_node.keyword == "table" and all(
                        child.line - 1 in removed for child in table_node.children):
                    removed.update(range(*_span(table_node, lines)))
        updated = "".join(renamed.get(index, line) for index, line in enumerate(lines) if index not in removed)
        if updated != text:
            # Check the remaining supported structure before handing bytes to a writer.
            _parse(updated, path.relative_to(model_path / "definition").parts[0])
            pending[path] = updated.encode("utf-8")
    return pending
