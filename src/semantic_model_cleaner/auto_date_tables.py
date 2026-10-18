"""Power BI auto-date tables: detection, consumer checks and removal.

With Auto date/time on, Power BI Desktop adds one hidden ``LocalDateTable_<guid>``
table per date column. It links the table to the column with a generated
relationship and a ``variation`` on the column, and it keeps one
``DateTableTemplate_<guid>`` table as a template. This module backs one explicit
cleanup action: "Review and remove unused auto-date tables".

Detection never trusts the name alone. A table qualifies only when its metadata is
exactly the generated structure: flags, annotations, template columns, hierarchy,
calculated partition, one generated relationship and one matching variation.

Consumer checks do not rely on the analyzer's parsed usage. Every selected model and
report file is searched for the table name, its relationship id and its lineage tags,
for column-variation DAX (``[OrderDate].[Year]``) and for report
``PropertyVariationSource`` references. Each occurrence must belong to the generated
structure itself. Anything else, or any file that cannot be read, blocks removal and
states why.

The general deletion policy is unchanged. These exceptions apply only to this action
and are checked again server-side when a plan is created and before it is applied.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from . import analyzer
from .tmdl_declarations import TmdlDeclaration, scan_tmdl_declarations
from .tmdl_identifiers import parse_tmdl_dotted_ref, unquote_tmdl_name

OPERATION_KIND = "auto_date_tables"
SUFFIXES = {".tmdl", ".json", ".pbir", ".pbism"}

_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GUID_RE = re.compile(_GUID, re.I)
_NAME_RE = re.compile(rf"^(LocalDateTable|DateTableTemplate)_({_GUID})$", re.I)
_PREFIX_RE = re.compile(r"^(LocalDateTable|DateTableTemplate)_", re.I)
_MARKER_ANNOTATIONS = {"local": "__PBI_LocalDateTable", "template": "__PBI_TemplateDateTable"}
_TEMPLATE_IDS = {"Year", "MonthNumber", "Month", "QuarterNumber", "Quarter", "Day"}
_TABLE_PROPERTIES = {"local": {"isHidden", "showAsVariationsOnly", "lineageTag"},
                     "template": {"isHidden", "isPrivate", "lineageTag"}}
_TABLE_ANNOTATIONS = {"local": {"__PBI_LocalDateTable", "DefaultItem"},
                      "template": {"__PBI_TemplateDateTable", "DefaultItem"}}
_COLUMN_PROPERTIES = {"dataType", "isHidden", "formatString", "lineageTag", "dataCategory", "summarizeBy",
                      "isNameInferred", "isDataTypeInferred", "sourceColumn", "sortByColumn", "annotation"}
_COLUMN_ANNOTATIONS = {"SummarizationSetBy", "TemplateId"}
_RELATIONSHIP_PROPERTIES = {"joinOnDateBehavior", "fromColumn", "toColumn"}
_VARIATION_PROPERTIES = {"isDefault", "relationship", "defaultHierarchy"}
_DAX_REF = r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_]*)\[(?:[^\]]|\]\])+\]"
_LOCAL_SOURCE_RE = re.compile(
    rf"^Calendar\(\s*Date\(\s*Year\(\s*MIN\(\s*(?P<min>{_DAX_REF})\s*\)\s*\)\s*,\s*1\s*,\s*1\s*\)\s*,"
    rf"\s*Date\(\s*Year\(\s*MAX\(\s*(?P<max>{_DAX_REF})\s*\)\s*\)\s*,\s*12\s*,\s*31\s*\)\s*\)$", re.I)
_TEMPLATE_SOURCE_RE = re.compile(
    r"^Calendar\(\s*Date\(\s*2015\s*,\s*1\s*,\s*1\s*\)\s*,\s*Date\(\s*2015\s*,\s*1\s*,\s*1\s*\)\s*\)$", re.I)
_VARIATION_DAX_RE = re.compile(r"\[((?:[^\]\r\n]|\]\])+)\]\s*\.\s*\[")
KIND_LABELS = {"local": "Auto-date table", "template": "Auto-date template table",
               "unknown": "Looks like an auto-date table"}


class AutoDateError(ValueError):
    pass


@dataclass
class _File:
    key: str  # "<artifact>/<relative posix path>"
    artifact: str  # "model" or the report folder name
    path: Path
    text: str
    _offsets: list[int] = field(default_factory=list, repr=False)
    _declarations: list[TmdlDeclaration] | None = field(default=None, repr=False)

    def line_of(self, offset: int) -> int:
        if not self._offsets:
            self._offsets = [0]
            for line in self.text.splitlines(keepends=True):
                self._offsets.append(self._offsets[-1] + len(line))
        return bisect_right(self._offsets, offset)

    @property
    def declarations(self) -> list[TmdlDeclaration]:
        if self._declarations is None:
            self._declarations = scan_tmdl_declarations(self.text) if self.key.endswith(".tmdl") else []
        return self._declarations


@dataclass
class _Candidate:
    name: str
    file: _File
    declaration: TmdlDeclaration
    kind: str = "unknown"
    problems: list[str] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    allowed: list[tuple[str, int, int]] = field(default_factory=list)  # (file key, first line, last line)
    owner: tuple[str, str] | None = None
    relationship: tuple[_File, TmdlDeclaration] | None = None
    variation: tuple[_File, TmdlDeclaration] | None = None
    ref_lines: list[tuple[_File, TmdlDeclaration]] = field(default_factory=list)

    def block(self, code: str, message: str, location: str = "") -> None:
        entry = {"code": code, "message": message, "location": location}
        if entry not in self.blockers:
            self.blockers.append(entry)


def _span_end(declaration: TmdlDeclaration) -> int:
    return max([declaration.end_line, *(_span_end(child) for child in declaration.children)])


def _prop(declaration: TmdlDeclaration, keyword: str) -> TmdlDeclaration | None:
    return declaration.child(keyword)


def _annotation(declaration: TmdlDeclaration, name: str) -> str | None:
    for child in declaration.children:
        if child.keyword == "annotation" and child.name.casefold() == name.casefold():
            return child.expression
    return None


def _flag(declaration: TmdlDeclaration, keyword: str) -> bool:
    child = _prop(declaration, keyword)
    return child is not None and (child.kind == "object" or child.value.casefold() in ("", "true"))


def _dax_ref(value: str) -> tuple[str, str]:
    table, column = value.rsplit("[", 1)
    table = table[1:-1].replace("''", "'") if table.startswith("'") else table
    return table, column[:-1].replace("]]", "]")


def _read_scope(model: Path, reports: list[Path]) -> tuple[list[_File], list[str]]:
    files, problems = [], []
    for artifact, root in [("model", model), *((report.name, report) for report in reports)]:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                problems.append(f"{artifact}/{path.relative_to(root).as_posix()} is a symlink; it cannot be checked.")
                continue
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            key = f"{artifact}/{path.relative_to(root).as_posix()}"
            raw = path.read_bytes()
            if artifact == "model" and path.suffix.lower() == ".tmdl" and raw.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{key} starts with a UTF-8 BOM; changes are withheld for this model in this beta.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                problems.append(f"{key} cannot be read as UTF-8 ({exc.reason}); it cannot be checked.")
                continue
            files.append(_File(key=key, artifact=artifact, path=path, text=text))
    return files, problems


def _describe(file: _File, line: int) -> str:
    """Name the declaration that owns ``line``, for example "measure 'Total' in table Sales"."""
    owner = None
    for declaration in file.declarations:
        if declaration.kind == "object" and declaration.line <= line <= _span_end(declaration):
            owner = declaration
    if owner is None:
        return ""
    chain = [owner, *owner.ancestors()]
    return " in ".join(f"{node.keyword} {node.name}".strip() for node in chain if node.kind == "object")


class _Model:
    """Text-level index of the selected model TMDL files."""

    def __init__(self, files: list[_File]):
        self.files = [f for f in files if f.artifact == "model" and f.key.endswith(".tmdl")]
        self.tables: dict[str, list[tuple[_File, TmdlDeclaration]]] = {}
        self.relationships: list[tuple[_File, TmdlDeclaration]] = []
        self.ref_tables: list[tuple[_File, TmdlDeclaration, str]] = []
        self.time_intelligence: str | None = None
        for file in self.files:
            for declaration in file.declarations:
                if declaration.keyword == "annotation" and declaration.name == "__PBI_TimeIntelligenceEnabled" and \
                        (declaration.parent is None or declaration.parent.keyword == "model"):
                    self.time_intelligence = declaration.expression
                if declaration.parent is not None:
                    continue
                if declaration.keyword == "table" and declaration.name:
                    self.tables.setdefault(declaration.name.casefold(), []).append((file, declaration))
                elif declaration.keyword == "relationship":
                    self.relationships.append((file, declaration))
                elif declaration.keyword == "ref" and declaration.name.startswith("table "):
                    self.ref_tables.append((file, declaration, unquote_tmdl_name(declaration.name[6:])))

    def table(self, name: str) -> TmdlDeclaration | None:
        found = self.tables.get(name.casefold(), [])
        return found[0][1] if len(found) == 1 else None

    @staticmethod
    def endpoints(relationship: TmdlDeclaration) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
        def ref(keyword):
            prop = relationship.child(keyword)
            return parse_tmdl_dotted_ref(prop.value) if prop is not None and prop.kind == "value" else None
        return ref("fromColumn"), ref("toColumn")


def _children(declaration: TmdlDeclaration, keyword: str) -> list[TmdlDeclaration]:
    return [child for child in declaration.children if child.keyword == keyword]


def _verify_structure(candidate: _Candidate, model: _Model) -> None:
    """Record why ``candidate`` is not exactly the generated structure, if it is not."""
    problems = candidate.problems
    table = candidate.declaration
    match = _NAME_RE.match(candidate.name)
    kind = match.group(1).casefold() if match else ""
    candidate.kind = {"localdatetable": "local", "datetabletemplate": "template"}.get(kind, "unknown")
    if candidate.kind == "unknown":
        problems.append("The name is not LocalDateTable_<id> or DateTableTemplate_<id>.")
        return
    kind = candidate.kind
    declared = model.tables.get(candidate.name.casefold(), [])
    if len(declared) != 1:
        problems.append(f"The table is declared {len(declared)} times.")
    others = [d for d in candidate.file.declarations if d.parent is None and d is not table]
    if others:
        problems.append(f"Its file also declares {others[0].keyword} {others[0].name}".rstrip() + ".")
    marker = _MARKER_ANNOTATIONS[kind]
    if (_annotation(table, marker) or "").strip().casefold() != "true":
        problems.append(f"The table has no '{marker} = true' annotation.")
    if not _flag(table, "isHidden"):
        problems.append("The table is not hidden.")
    required_flag = "showAsVariationsOnly" if kind == "local" else "isPrivate"
    if not _flag(table, required_flag):
        problems.append(f"The table is not marked {required_flag}.")
    for child in table.children:
        if child.keyword in ("column", "hierarchy", "partition"):
            continue
        if child.keyword == "annotation":
            if child.name not in _TABLE_ANNOTATIONS[kind]:
                problems.append(f"Unexpected table annotation {child.name} (line {child.line}).")
        elif child.keyword not in _TABLE_PROPERTIES[kind]:
            problems.append(f"Unexpected table metadata '{child.keyword}' (line {child.line}).")
    columns = _children(table, "column")
    column_names = {c.name.casefold() for c in columns}
    date_columns = [c for c in columns if not c.has_expression]
    template_ids = []
    for column in columns:
        for child in column.children:
            if child.keyword == "annotation":
                if child.name not in _COLUMN_ANNOTATIONS:
                    problems.append(f"Unexpected annotation {child.name} on column {column.name} (line {child.line}).")
            elif child.keyword not in _COLUMN_PROPERTIES:
                problems.append(f"Unexpected metadata '{child.keyword}' on column {column.name} (line {child.line}).")
        if not _flag(column, "isHidden"):
            problems.append(f"Column {column.name} is not hidden.")
        sort_by = _prop(column, "sortByColumn")
        if sort_by is not None and unquote_tmdl_name(sort_by.value).casefold() not in column_names:
            problems.append(f"Column {column.name} sorts by a column outside the table.")
        if column.has_expression:
            template_id = (_annotation(column, "TemplateId") or "").strip()
            if template_id not in _TEMPLATE_IDS:
                problems.append(f"Calculated column {column.name} is not a generated date part (no known TemplateId).")
            template_ids.append(template_id)
    if len(template_ids) != len(set(template_ids)):
        problems.append("The table repeats a generated date part.")
    if len(date_columns) != 1:
        problems.append(f"The table has {len(date_columns)} source date columns; the generated table has one.")
    date_column = date_columns[0] if len(date_columns) == 1 else None
    if date_column is not None:
        source = _prop(date_column, "sourceColumn")
        category = _prop(date_column, "dataCategory")
        if source is None or source.value != "[Date]" or category is None or category.value != "PaddedDateTableDates":
            problems.append(f"Column {date_column.name} is not the generated padded date column.")
    hierarchies = _children(table, "hierarchy")
    if len(hierarchies) != 1:
        problems.append(f"The table has {len(hierarchies)} hierarchies; the generated table has one.")
    hierarchy = hierarchies[0] if len(hierarchies) == 1 else None
    if hierarchy is not None:
        if (_annotation(hierarchy, "TemplateId") or "").strip() != "DateHierarchy":
            problems.append(f"Hierarchy {hierarchy.name} is not the generated date hierarchy.")
        for child in hierarchy.children:
            if child.keyword == "level":
                level_column = _prop(child, "column")
                if level_column is None or unquote_tmdl_name(level_column.value).casefold() not in column_names:
                    problems.append(f"Hierarchy level {child.name} does not use a column of this table.")
                if any(grand.keyword not in ("lineageTag", "column") for grand in child.children):
                    problems.append(f"Hierarchy level {child.name} has unexpected metadata.")
            elif child.keyword == "annotation":
                if child.name != "TemplateId":
                    problems.append(f"Unexpected annotation {child.name} on hierarchy {hierarchy.name}.")
            elif child.keyword != "lineageTag":
                problems.append(f"Unexpected metadata '{child.keyword}' on hierarchy {hierarchy.name}.")
    partitions = _children(table, "partition")
    source_text = ""
    if len(partitions) != 1 or partitions[0].expression.strip().casefold() != "calculated":
        problems.append("The table does not have exactly one calculated partition.")
    else:
        partition = partitions[0]
        source = _prop(partition, "source")
        mode = _prop(partition, "mode")
        if any(child.keyword not in ("mode", "source") for child in partition.children) or \
                mode is None or mode.value != "import" or source is None:
            problems.append("The partition is not the generated import partition.")
        else:
            source_text = " ".join(source.expression.split())
    lineage = _prop(table, "lineageTag")
    candidate.tokens = {_NAME_RE.match(candidate.name).group(2).casefold()}
    candidate.tokens.update(
        node.value.casefold() for node in _walk(table)
        if node.keyword == "lineageTag" and node.kind == "value" and _GUID_RE.fullmatch(node.value))
    if lineage is None:
        problems.append("The table has no lineage tag.")
    candidate.allowed.append((candidate.file.key, 1, len(candidate.file.text.splitlines()) or 1))
    for file, declaration, name in model.ref_tables:
        if name.casefold() == candidate.name.casefold():
            candidate.ref_lines.append((file, declaration))
            candidate.allowed.append((file.key, declaration.line, _span_end(declaration)))
    touching = [(file, rel) for file, rel in model.relationships
                if any(end and end[0].casefold() == candidate.name.casefold() for end in model.endpoints(rel))]
    if kind == "template":
        if source_text and not _TEMPLATE_SOURCE_RE.match(source_text):
            problems.append("The partition source is not the generated template calendar.")
        if touching:
            problems.append("A relationship uses the template table.")
        return
    source_match = _LOCAL_SOURCE_RE.match(source_text) if source_text else None
    owner = None
    if source_text and not source_match:
        problems.append("The partition source is not the generated calendar of one date column.")
    elif source_match:
        low, high = _dax_ref(source_match.group("min")), _dax_ref(source_match.group("max"))
        if (low[0].casefold(), low[1].casefold()) != (high[0].casefold(), high[1].casefold()):
            problems.append("The partition source uses two different date columns.")
        else:
            owner = low
    if len(touching) != 1:
        problems.append(f"{len(touching)} relationships use this table; the generated table has exactly one.")
        return
    rel_file, relationship = touching[0]
    candidate.relationship = (rel_file, relationship)
    candidate.tokens.add(relationship.name.casefold())
    from_ref, to_ref = model.endpoints(relationship)
    if rel_file.key != "model/definition/relationships.tmdl":
        problems.append(f"Its relationship is declared in {rel_file.key}, not in relationships.tmdl.")
    if any(child.keyword not in _RELATIONSHIP_PROPERTIES for child in relationship.children):
        extra = next(child.keyword for child in relationship.children if child.keyword not in _RELATIONSHIP_PROPERTIES)
        problems.append(f"Its relationship has non-generated metadata '{extra}'.")
    join = relationship.child("joinOnDateBehavior")
    if join is None or join.value != "datePartOnly":
        problems.append("Its relationship is not the generated date-part relationship.")
    if date_column is None or to_ref is None or to_ref[0].casefold() != candidate.name.casefold() or \
            to_ref[1].casefold() != date_column.name.casefold():
        problems.append("Its relationship does not end at the generated date column.")
    if from_ref is None or owner is None or (from_ref[0].casefold(), from_ref[1].casefold()) != \
            (owner[0].casefold(), owner[1].casefold()):
        problems.append("Its relationship does not start at the date column that the table was generated for.")
        return
    owner_table = model.table(from_ref[0])
    owner_column = next((c for c in _children(owner_table, "column")
                         if c.name.casefold() == from_ref[1].casefold()), None) if owner_table else None
    if owner_column is None:
        problems.append(f"Date column {from_ref[0]}[{from_ref[1]}] was not found.")
        return
    candidate.owner = (owner_table.name, owner_column.name)
    if _NAME_RE.match(owner_table.name):
        problems.append("Its date column belongs to another auto-date table.")
    owner_file = next(f for f, d in model.tables[owner_table.name.casefold()] if d is owner_table)
    variations = [v for v in _children(owner_column, "variation")
                  if (v.child("relationship") is not None
                      and v.child("relationship").value.casefold() == relationship.name.casefold())]
    if len(variations) != 1:
        problems.append(f"Date column {owner_table.name}[{owner_column.name}] has {len(variations)} variations "
                        "linked to this table; the generated column has one.")
        return
    variation = variations[0]
    candidate.variation = (owner_file, variation)
    candidate.allowed.append((owner_file.key, variation.line, _span_end(variation)))
    candidate.allowed.append((rel_file.key, relationship.line, _span_end(relationship)))
    if any(child.keyword not in _VARIATION_PROPERTIES for child in variation.children):
        problems.append(f"The variation on {owner_table.name}[{owner_column.name}] has non-generated metadata.")
    default = variation.child("defaultHierarchy")
    target = parse_tmdl_dotted_ref(default.value) if default is not None and default.kind == "value" else None
    if hierarchy is None or target is None or target[0].casefold() != candidate.name.casefold() or \
            target[1].casefold() != hierarchy.name.casefold():
        problems.append(f"The variation on {owner_table.name}[{owner_column.name}] does not use this table's date hierarchy.")


def _walk(declaration: TmdlDeclaration):
    yield declaration
    for child in declaration.children:
        yield from _walk(child)


def _location(file: _File, line: int) -> str:
    return f"{file.key}:{line}"


def _scan_mentions(candidates: list[_Candidate], files: list[_File]) -> None:
    """Block a candidate for every mention outside its own generated structure."""
    by_token: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        for token in candidate.tokens:
            by_token.setdefault(token, []).append(candidate)
    for file in files:
        for match in _GUID_RE.finditer(file.text):
            owners = by_token.get(match.group(0).casefold())
            if not owners:
                continue
            line = file.line_of(match.start())
            for candidate in owners:
                if any(key == file.key and first <= line <= last for key, first, last in candidate.allowed):
                    continue
                candidate.block(*_mention_reason(file, line, candidate))


def _mention_reason(file: _File, line: int, candidate: _Candidate) -> tuple[str, str, str]:
    location = _location(file, line)
    if file.artifact != "model":
        return ("report_reference", f"Report {file.artifact} names this table ({location}).", location)
    if file.key.startswith("model/definition/cultures/"):
        return ("model_reference", f"Culture metadata names this table ({location}). Removing it would leave "
                "translations or linguistic metadata pointing at a missing table.", location)
    owner = _describe(file, line)
    what = f" in {owner}" if owner else ""
    return ("model_reference", f"The model names this table{what} ({location}).", location)


def _scan_variation_dax(candidates: list[_Candidate], files: list[_File]) -> None:
    """``[OrderDate].[Year]`` reaches the auto-date table without naming it."""
    by_column: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.owner:
            by_column.setdefault(candidate.owner[1].casefold(), []).append(candidate)
    for file in files:
        for match in _VARIATION_DAX_RE.finditer(file.text):
            for candidate in by_column.get(match.group(1).replace("]]", "]").casefold(), []):
                if file is candidate.file:
                    continue
                location = _location(file, file.line_of(match.start()))
                table, column = candidate.owner
                where = f"Report {file.artifact}" if file.artifact != "model" else "DAX in the model"
                candidate.block("variation_dax", f"{where} may use the auto date hierarchy of {table}[{column}] "
                                f"through [{column}].[…] ({location}).", location)


def _scan_report_hierarchies(candidates: list[_Candidate], files: list[_File]) -> list[str]:
    """Match report ``PropertyVariationSource`` fields and query refs to their date columns."""
    owners: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.owner:
            owners.setdefault((candidate.owner[0].casefold(), candidate.owner[1].casefold()), []).append(candidate)
    prefixes = []
    for candidate in candidates:
        if candidate.owner and candidate.variation:
            table, column = candidate.owner
            prefixes.append((f"{table}.{column}.{candidate.variation[1].name}".casefold(), candidate))
    unresolved: list[str] = []
    for file in files:
        if file.artifact == "model" or not file.key.lower().endswith((".json", ".pbir")):
            continue
        try:
            document = json.loads(file.text)
        except ValueError as exc:
            unresolved.append(f"Report file {file.key} is not valid JSON ({exc}); its use of date hierarchies cannot be checked.")
            continue

        def visit(node, aliases):
            if isinstance(node, dict):
                aliases = {**aliases, **analyzer._source_aliases_from_obj(node)}
                source = node.get("PropertyVariationSource")
                if isinstance(source, dict):
                    expression = source.get("Expression")
                    ref = expression.get("SourceRef") if isinstance(expression, dict) else None
                    entity = analyzer._source_ref_entity(ref, aliases) if isinstance(ref, dict) else None
                    prop = source.get("Property")
                    if not entity or not isinstance(prop, str):
                        unresolved.append(f"Report file {file.key} uses an auto date hierarchy that could not be "
                                          "matched to a date column.")
                    else:
                        for candidate in owners.get((entity.casefold(), prop.casefold()), []):
                            candidate.block("report_hierarchy", f"Report {file.artifact} uses the date hierarchy of "
                                            f"{entity}[{prop}] ({file.key}).", file.key)
                for value in node.values():
                    visit(value, aliases)
            elif isinstance(node, list):
                for value in node:
                    visit(value, aliases)
            elif isinstance(node, str):
                folded = node.casefold()
                for prefix, candidate in prefixes:
                    if folded == prefix or folded.startswith(prefix + "."):
                        candidate.block("report_hierarchy", f"Report {file.artifact} uses the date hierarchy of "
                                        f"{candidate.owner[0]}[{candidate.owner[1]}] ({file.key}).", file.key)

        visit(document, analyzer._source_aliases_from_tree(document))
    return sorted(set(unresolved))


def assess(model_path, report_paths, *, require_bound: bool = True) -> dict:
    """Read-only assessment of every auto-date table candidate in the selected scope."""
    model = Path(model_path).resolve()
    reports = sorted({Path(p).resolve() for p in report_paths})
    scope_blockers: list[str] = []
    result = {"ok": True, "scope": {"model": str(model), "reports": [str(r) for r in reports]},
              "scope_blockers": scope_blockers, "time_intelligence_enabled": None, "tables": [],
              "found": 0, "removable_count": 0, "blocked_count": 0}
    if not (model / "definition").is_dir():
        result["ok"] = False
        scope_blockers.append("Select one TMDL semantic model folder with a definition directory.")
        return result
    if not reports:
        scope_blockers.append("Select at least one report bound to this model. Without a report, report use of "
                              "the date hierarchies cannot be checked.")
    for report in reports:
        if not (report / "definition").is_dir():
            scope_blockers.append(f"Report {report.name} has no PBIR definition folder; its use of date "
                                  "hierarchies cannot be checked.")
        elif require_bound:
            status = analyzer.report_binding_status(report, model)["status"]
            if status not in analyzer.BOUND_REPORT_STATUSES:
                scope_blockers.append(f"Report {report.name} is not confirmed to use this model ({status}).")
    files, read_problems = _read_scope(model, [r for r in reports if r.is_dir()])
    scope_blockers.extend(read_problems)
    index = _Model(files)
    result["time_intelligence_enabled"] = (None if index.time_intelligence is None
                                           else index.time_intelligence.strip() not in ("0", "false"))
    candidates = []
    for declared in index.tables.values():
        for file, declaration in declared:
            table_flags = {child.keyword for child in declaration.children}
            markers = {child.name for child in declaration.children if child.keyword == "annotation"}
            if _PREFIX_RE.match(declaration.name) or "showAsVariationsOnly" in table_flags or \
                    markers & set(_MARKER_ANNOTATIONS.values()):
                candidates.append(_Candidate(name=declaration.name, file=file, declaration=declaration))
    for candidate in candidates:
        _verify_structure(candidate, index)
    generated = [c for c in candidates if not c.problems]
    _scan_mentions(generated, files)
    _scan_variation_dax(generated, files)
    unresolved = _scan_report_hierarchies(generated, files)
    for candidate in sorted(candidates, key=lambda c: (c.owner or ("~",) * 2, c.name.casefold())):
        if candidate.problems:
            for problem in candidate.problems:
                candidate.block("not_generated", "Not proven to be a generated auto-date table: " + problem)
        for message in scope_blockers:
            candidate.block("scope", message)
        if candidate.kind == "local":
            for message in unresolved:
                candidate.block("report_hierarchy", message)
        owner = f"{candidate.owner[0]}[{candidate.owner[1]}]" if candidate.owner else None
        result["tables"].append({
            "table": candidate.name, "kind": candidate.kind, "label": KIND_LABELS[candidate.kind],
            "file": candidate.file.key, "date_column": owner,
            "relationship": candidate.relationship[1].name if candidate.relationship else None,
            "variation": candidate.variation[1].name if candidate.variation else None,
            "removable": not candidate.blockers, "blockers": candidate.blockers,
        })
    result["found"] = len(result["tables"])
    result["removable_count"] = sum(1 for t in result["tables"] if t["removable"])
    result["blocked_count"] = result["found"] - result["removable_count"]
    return result


def requested_tables(operation: dict) -> list[str]:
    tables = operation.get("tables")
    if not isinstance(tables, list) or not tables or not all(isinstance(t, str) and t for t in tables):
        raise AutoDateError("Select at least one auto-date table to remove.")
    if len({t.casefold() for t in tables}) != len(tables):
        raise AutoDateError("Each auto-date table can be selected once.")
    return tables


def blocking_reasons(assessment: dict, tables: list[str]) -> list[str]:
    """Server-side gate: every requested table must be a removable generated table now."""
    known = {entry["table"].casefold(): entry for entry in assessment.get("tables", [])}
    reasons = []
    for name in tables:
        entry = known.get(name.casefold())
        if entry is None:
            reasons.append(f"{name} is not an auto-date table in the selected model.")
        elif not entry["removable"]:
            reasons.append(f"{entry['table']} cannot be removed: "
                           + " ".join(blocker["message"] for blocker in entry["blockers"]))
    return reasons


def _remove_span(lines: list[str], first: int, last: int) -> None:
    """Delete 0-based lines ``first..last`` and keep one blank separator where there was one."""
    after = last + 1
    while after < len(lines) and not lines[after].strip():
        after += 1
    before = first
    while before > 0 and not lines[before - 1].strip():
        before -= 1
    if before < first or before == 0:
        del lines[first:after]
    else:
        del lines[first:last + 1]


def integrity_problems(model_path, report_paths=(), removed_tokens: dict[str, str] | None = None) -> set[str]:
    """Independent text-level check of model references; not the analyzer.

    Reports ``ref table`` lines without a table, relationships whose columns are
    missing, variations whose relationship or default hierarchy is missing, sort-by
    and hierarchy levels whose column is missing, and any remaining mention of
    ``removed_tokens`` (lower-case GUID -> removed table) in model or report files.
    """
    model = Path(model_path).resolve()
    files, _ = _read_scope(model, [Path(p).resolve() for p in report_paths])
    index = _Model(files)
    problems: set[str] = set()
    tables = {name: declared[0][1] for name, declared in index.tables.items()}

    def columns(table):
        return {c.name.casefold() for c in _children(table, "column")}

    relationship_ids = {rel.name.casefold() for _, rel in index.relationships}
    for file, _, name in index.ref_tables:
        if name.casefold() not in tables:
            problems.add(f"{file.key}: ref table {name} has no table declaration.")
    for file, relationship in index.relationships:
        for end in index.endpoints(relationship):
            if end is None or end[0].casefold() not in tables or end[1].casefold() not in columns(tables[end[0].casefold()]):
                problems.add(f"{file.key}: relationship {relationship.name} uses a missing column {end}.")
    for name, table in tables.items():
        names = columns(table)
        for column in _children(table, "column"):
            sort_by = _prop(column, "sortByColumn")
            if sort_by is not None and unquote_tmdl_name(sort_by.value).casefold() not in names:
                problems.add(f"{table.name}[{column.name}] sorts by a missing column.")
            for variation in _children(column, "variation"):
                rel = variation.child("relationship")
                if rel is not None and rel.value.casefold() not in relationship_ids:
                    problems.add(f"Variation {variation.name} on {table.name}[{column.name}] uses missing relationship {rel.value}.")
                default = variation.child("defaultHierarchy")
                target = parse_tmdl_dotted_ref(default.value) if default is not None else None
                if default is not None and (target is None or target[0].casefold() not in tables or target[1].casefold()
                                            not in {h.name.casefold() for h in _children(tables[target[0].casefold()], "hierarchy")}):
                    problems.add(f"Variation {variation.name} on {table.name}[{column.name}] uses missing hierarchy {default.value}.")
        for hierarchy in _children(table, "hierarchy"):
            for level in _children(hierarchy, "level"):
                column = _prop(level, "column")
                if column is not None and unquote_tmdl_name(column.value).casefold() not in names:
                    problems.add(f"Hierarchy {table.name}.{hierarchy.name} level {level.name} uses a missing column.")
    for file in files:
        for match in _GUID_RE.finditer(file.text):
            table = (removed_tokens or {}).get(match.group(0).casefold())
            if table:
                problems.add(f"{_location(file, file.line_of(match.start()))} still refers to removed {table}.")
    return problems


def remove_tables(model_path, report_paths, tables: list[str], *, require_bound: bool = True) -> dict:
    """Remove validated auto-date tables with their generated relationship, ref line and variation.

    Assesses the given files again, so callers pass staged copies. Line endings and
    every untouched byte are preserved. Fails without writing when any table is
    blocked, and reports any new reference problem found after writing.
    """
    model = Path(model_path).resolve()
    report_paths = [Path(p).resolve() for p in report_paths]
    tables = requested_tables({"tables": tables})
    assessment = assess(model, report_paths, require_bound=require_bound)
    reasons = blocking_reasons(assessment, tables)
    if reasons:
        return {"ok": False, "error": " ".join(reasons), "assessment": assessment}
    before = integrity_problems(model, report_paths)
    files, _ = _read_scope(model, [])
    index = _Model(files)
    selected = {t.casefold() for t in tables}
    spans: dict[Path, list[tuple[int, int]]] = {}
    deleted: list[Path] = []
    tokens: dict[str, str] = {}
    summary = {"removed_tables": [], "removed_relationships": [], "removed_variations": [], "deleted_files": []}
    candidates = []
    for declared in index.tables.values():
        for file, declaration in declared:
            if declaration.name.casefold() in selected:
                candidate = _Candidate(name=declaration.name, file=file, declaration=declaration)
                _verify_structure(candidate, index)
                if candidate.problems:  # Assessed as removable a moment ago; files changed underneath.
                    return {"ok": False, "error": f"{candidate.name} changed while it was being removed."}
                candidates.append(candidate)
    for candidate in candidates:
        deleted.append(candidate.file.path)
        summary["removed_tables"].append(candidate.name)
        summary["deleted_files"].append(candidate.file.key)
        tokens.update({token: candidate.name for token in candidate.tokens})
        for file, declaration in candidate.ref_lines:
            spans.setdefault(file.path, []).append((declaration.line, _span_end(declaration)))
        if candidate.relationship:
            file, declaration = candidate.relationship
            spans.setdefault(file.path, []).append((declaration.line, _span_end(declaration)))
            summary["removed_relationships"].append(declaration.name)
        if candidate.variation:
            file, declaration = candidate.variation
            spans.setdefault(file.path, []).append((declaration.line, _span_end(declaration)))
            summary["removed_variations"].append(f"{candidate.owner[0]}[{candidate.owner[1]}] {declaration.name}")
    for path, ranges in spans.items():
        lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
        for first, last in sorted(ranges, reverse=True):
            _remove_span(lines, first - 1, last - 1)
        text = "".join(lines)
        if path.name == "relationships.tmdl" and not text.strip():
            deleted.append(path)
            summary["deleted_files"].append(f"model/{path.relative_to(model).as_posix()}")
            continue
        path.write_bytes(text.encode("utf-8"))
    for path in deleted:
        path.unlink()
    new = integrity_problems(model, report_paths, tokens) - before
    if new:
        return {"ok": False, "error": "Removal would leave broken references: " + "; ".join(sorted(new))}
    return {"ok": True, **summary}
