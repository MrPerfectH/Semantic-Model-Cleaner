"""Structural TMDL declaration scanning.

Feature detection must come from actual declarations, never from a keyword
appearing inside a name, description, comment, string literal or expression.
This module turns a TMDL file into a shallow declaration tree so callers can
ask "is there a `kpi` object under this measure" instead of "does the text
contain `kpi`".

The scanner is deliberately conservative about structure: it tracks the
indentation-based nesting the TMDL serializer emits, treats lines deeper than
an expression-bearing declaration as that expression's continuation, and
handles ``` fenced expressions and TMDL-level comments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .tmdl_identifiers import split_tmdl_name_and_expression

_KEYWORD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", re.S)
_FENCE = "```"

# Declarations whose expression lives on the declaration line or two levels
# deeper (properties sit one level deeper). Everything else with `=` is a
# property whose continuation is any deeper line.
_OBJECT_KEYWORDS_WITH_EXPRESSION = {"measure", "column", "calculationItem", "annotation",
                                    "expression", "partition", "table"}


@dataclass
class TmdlDeclaration:
    keyword: str
    name: str
    depth: int
    line: int  # 1-based line number of the declaration
    kind: str  # "object" | "expression" | "value"
    has_expression: bool = False
    expression_lines: list[str] = field(default_factory=list)
    value: str = ""
    parent: "TmdlDeclaration | None" = field(default=None, repr=False)
    children: list["TmdlDeclaration"] = field(default_factory=list, repr=False)

    @property
    def expression(self) -> str:
        return "\n".join(line for line in self.expression_lines if line.strip() != _FENCE).strip()

    def child(self, keyword: str) -> "TmdlDeclaration | None":
        for child in self.children:
            if child.keyword == keyword:
                return child
        return None

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def owner(self, *keywords: str) -> "TmdlDeclaration | None":
        for node in self.ancestors():
            if node.keyword in keywords:
                return node
        return None


def _indent_depth(line: str) -> int:
    tabs = len(line) - len(line.lstrip("\t"))
    if tabs:
        return tabs
    spaces = len(line) - len(line.lstrip(" "))
    return spaces // 4


def scan_tmdl_declarations(text: str) -> list[TmdlDeclaration]:
    """Return every declaration in document order with parent/children links."""
    declarations: list[TmdlDeclaration] = []
    stack: list[TmdlDeclaration] = []
    fence_owner: TmdlDeclaration | None = None
    in_block_comment = False

    def expression_owner(depth: int) -> TmdlDeclaration | None:
        if not stack:
            return None
        top = stack[-1]
        if top.kind == "expression" and depth > top.depth:
            return top
        if top.kind == "object" and top.has_expression and depth >= top.depth + 2:
            return top
        return None

    for index, raw in enumerate(text.splitlines(), start=1):
        if fence_owner is not None:
            if raw.strip() == _FENCE:
                fence_owner = None
            else:
                fence_owner.expression_lines.append(raw.strip())
            continue
        if in_block_comment:
            if "*/" in raw:
                in_block_comment = False
            continue
        stripped = raw.strip()
        if not stripped:
            continue
        depth = _indent_depth(raw)

        owner = expression_owner(depth)
        if owner is not None:
            if stripped == _FENCE:
                fence_owner = owner
            else:
                owner.expression_lines.append(stripped)
            continue

        # TMDL-level comments and descriptions are never declarations.
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*"):
            in_block_comment = "*/" not in stripped[2:]
            continue

        while stack and stack[-1].depth >= depth:
            stack.pop()
        parent = stack[-1] if stack else None

        match = _KEYWORD_RE.match(stripped)
        if not match:
            continue
        keyword, rest = match.group(1), match.group(2).strip()
        declaration = TmdlDeclaration(keyword=keyword, name="", depth=depth, line=index,
                                      kind="object", parent=parent)
        if rest.startswith(":"):
            declaration.kind = "value"
            declaration.value = rest[1:].strip()
        elif rest.startswith("="):
            declaration.kind = "expression"
            declaration.has_expression = True
            first = rest[1:].strip()
            if first.startswith(_FENCE):
                fence_owner = declaration
                first = first[len(_FENCE):].strip()
            if first:
                declaration.expression_lines.append(first)
        elif rest:
            name, expression, has_expression = split_tmdl_name_and_expression(rest)
            declaration.name = name
            declaration.has_expression = has_expression
            if has_expression:
                if expression.startswith(_FENCE):
                    fence_owner = declaration
                    expression = expression[len(_FENCE):].strip()
                if expression:
                    declaration.expression_lines.append(expression)
        if declaration.kind == "object" and not declaration.has_expression and \
                keyword not in _OBJECT_KEYWORDS_WITH_EXPRESSION and parent is not None and \
                parent.kind != "object":
            # A bare word under a property is malformed; keep it out of the tree.
            continue
        if parent is not None:
            parent.children.append(declaration)
        declarations.append(declaration)
        stack.append(declaration)

    return declarations


@dataclass
class FeatureExpression:
    """An actual TMDL declaration the analyzer detects but does not fully analyze."""
    area: str
    feature: str  # user-facing feature label, e.g. "KPI target expression"
    construct: str  # TMDL construct path, e.g. "measure/kpi/targetExpression"
    table: str
    owner: str  # user-facing owning object, e.g. "measure 'Sales'[Target]"
    owner_kind: str  # "table" | "measure" | "column" | "calculationItem" | "calculationGroup"
    owner_name: str
    line: int
    expression: str
    dynamic: bool  # true when the construct applies to arbitrary measures at runtime


def _quote(table: str) -> str:
    return "'" + table.replace("'", "''") + "'"


def _measure_label(table: str, name: str) -> str:
    return f"measure {_quote(table)}[{name}]"


def extract_feature_expressions(text: str) -> tuple[list[FeatureExpression], dict[str, dict]]:
    """Return (feature expressions, table metadata) from one TMDL table file.

    Table metadata records calculation groups: {table: {"calculation_items": [...],
    "line": n}}. Only genuine declarations are considered; a table named
    `KPI Selector` or a description mentioning KPI flags yields nothing.
    """
    features: list[FeatureExpression] = []
    tables: dict[str, dict] = {}
    for declaration in scan_tmdl_declarations(text):
        if declaration.keyword != "table" or declaration.depth != 0:
            continue
        table = declaration.name
        for child in declaration.children:
            if child.keyword == "calculationGroup" and child.kind == "object":
                items = [item for item in child.children if item.keyword == "calculationItem"]
                tables[table] = {"calculation_items": [item.name for item in items], "line": child.line}
                for item in items:
                    features.append(FeatureExpression(
                        area="Calculation Groups", feature="calculation item expression",
                        construct="calculationGroup/calculationItem", table=table,
                        owner=f"calculation item '{item.name}' in {_quote(table)}",
                        owner_kind="calculationItem", owner_name=item.name, line=item.line,
                        expression=item.expression, dynamic=True))
                    format_definition = item.child("formatStringDefinition")
                    if format_definition is not None and format_definition.kind == "expression":
                        features.append(FeatureExpression(
                            area="Format string definitions",
                            feature="calculation item format-string expression",
                            construct="calculationGroup/calculationItem/formatStringDefinition",
                            table=table, owner=f"calculation item '{item.name}' in {_quote(table)}",
                            owner_kind="calculationItem", owner_name=item.name,
                            line=format_definition.line, expression=format_definition.expression,
                            dynamic=True))
                for selection in ("multipleOrEmptySelectionExpression", "noSelectionExpression"):
                    expression = child.child(selection)
                    if expression is not None and expression.kind == "expression":
                        features.append(FeatureExpression(
                            area="Calculation Groups", feature=f"calculation group {selection}",
                            construct=f"calculationGroup/{selection}", table=table,
                            owner=f"calculation group {_quote(table)}", owner_kind="calculationGroup",
                            owner_name=table, line=expression.line,
                            expression=expression.expression, dynamic=True))
            elif child.keyword == "defaultDetailRowsDefinition" and child.kind == "expression":
                features.append(FeatureExpression(
                    area="Detail rows", feature="table default detail rows expression",
                    construct="table/defaultDetailRowsDefinition", table=table,
                    owner=f"table {_quote(table)}", owner_kind="table", owner_name=table,
                    line=child.line, expression=child.expression, dynamic=False))
            elif child.keyword == "measure" and child.kind == "object":
                features.extend(_measure_features(table, child))
            elif child.keyword == "column" and child.kind == "object":
                features.extend(_column_features(table, child))
            elif child.keyword == "partition" and child.kind == "object":
                coverage = child.child("dataCoverageDefinition")
                if coverage is not None and coverage.kind == "expression":
                    features.append(FeatureExpression(
                        area="Data coverage definitions", feature="partition data coverage expression",
                        construct="partition/dataCoverageDefinition", table=table,
                        owner=f"partition {_quote(child.name)} in {_quote(table)}",
                        owner_kind="partition", owner_name=child.name, line=coverage.line,
                        expression=coverage.expression, dynamic=False))
    return features, tables


_MEASURE_EXPRESSION_PROPERTIES = {
    "detailRowsDefinition": ("Detail rows", "measure detail rows expression"),
    "formatStringDefinition": ("Format string definitions", "measure format-string expression"),
    "dataCoverageDefinition": ("Data coverage definitions", "measure data coverage expression"),
}
_KPI_EXPRESSION_PROPERTIES = {
    "targetExpression": "KPI target expression",
    "statusExpression": "KPI status expression",
    "trendExpression": "KPI trend expression",
}


def _measure_features(table: str, measure: TmdlDeclaration) -> list[FeatureExpression]:
    features: list[FeatureExpression] = []
    owner = _measure_label(table, measure.name)
    for prop in measure.children:
        if prop.kind == "expression" and prop.keyword in _MEASURE_EXPRESSION_PROPERTIES:
            area, feature = _MEASURE_EXPRESSION_PROPERTIES[prop.keyword]
            features.append(FeatureExpression(
                area=area, feature=feature, construct=f"measure/{prop.keyword}", table=table,
                owner=owner, owner_kind="measure", owner_name=measure.name, line=prop.line,
                expression=prop.expression, dynamic=False))
        elif prop.keyword == "kpi" and prop.kind == "object":
            kpi_expressions = [child for child in prop.children
                               if child.kind == "expression" and child.keyword in _KPI_EXPRESSION_PROPERTIES]
            if not kpi_expressions:
                features.append(FeatureExpression(
                    area="KPI expressions", feature="KPI declaration", construct="measure/kpi",
                    table=table, owner=owner, owner_kind="measure", owner_name=measure.name,
                    line=prop.line, expression="", dynamic=False))
            for child in kpi_expressions:
                features.append(FeatureExpression(
                    area="KPI expressions", feature=_KPI_EXPRESSION_PROPERTIES[child.keyword],
                    construct=f"measure/kpi/{child.keyword}", table=table, owner=owner,
                    owner_kind="measure", owner_name=measure.name, line=child.line,
                    expression=child.expression, dynamic=False))
    return features


def _column_features(table: str, column: TmdlDeclaration) -> list[FeatureExpression]:
    features: list[FeatureExpression] = []
    for prop in column.children:
        if prop.kind == "expression" and prop.keyword == "dataCoverageDefinition":
            features.append(FeatureExpression(
                area="Data coverage definitions", feature="column data coverage expression",
                construct="column/dataCoverageDefinition", table=table,
                owner=f"column {_quote(table)}[{column.name}]", owner_kind="column",
                owner_name=column.name, line=prop.line, expression=prop.expression, dynamic=False))
    return features


@dataclass
class PerspectiveMember:
    perspective: str
    table: str
    name: str  # empty for table-level membership
    kind: str  # "table" | "measure" | "column" | "hierarchy"
    line: int


def extract_perspective_members(text: str) -> list[PerspectiveMember]:
    """Return perspective memberships declared in a perspective TMDL file."""
    members: list[PerspectiveMember] = []
    keywords = {"perspectiveMeasure": "measure", "perspectiveColumn": "column",
                "perspectiveHierarchy": "hierarchy"}
    for declaration in scan_tmdl_declarations(text):
        if declaration.keyword != "perspective" or declaration.depth != 0:
            continue
        for table_member in declaration.children:
            if table_member.keyword != "perspectiveTable" or not table_member.name:
                continue
            members.append(PerspectiveMember(declaration.name, table_member.name, "", "table",
                                             table_member.line))
            for member in table_member.children:
                kind = keywords.get(member.keyword)
                if kind and member.name:
                    members.append(PerspectiveMember(declaration.name, table_member.name,
                                                     member.name, kind, member.line))
    return members
