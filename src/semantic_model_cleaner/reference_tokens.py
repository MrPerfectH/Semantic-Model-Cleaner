"""Small lexical transformations for supported DAX and TMDL expression sites.

This is not a DAX compiler. Strings/comments are opaque; callers must reject
ambiguous binding instead of guessing. M and descriptive TMDL metadata are not
expression sites and are never passed to the DAX transformer.
"""
import re
from dataclasses import dataclass

from .tmdl_identifiers import quote_dax_object_name, quote_dax_table_name


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


def dax_tokens(text: str) -> list[Token]:
    tokens = []
    i = 0
    while i < len(text):
        start = i
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if text.startswith('//', i) or text.startswith('--', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if char in ('"', "'", '['):
            close = ']' if char == '[' else char
            i += 1
            value = ''
            while i < len(text):
                if text[i] == close:
                    if i + 1 < len(text) and text[i + 1] == close:
                        value += close
                        i += 2
                        continue
                    i += 1
                    break
                value += text[i]
                i += 1
            kind = {'"': 'string', "'": 'table', '[': 'object'}[char]
            tokens.append(Token(kind, value, start, i))
            continue
        if char.isalpha() or char == '_':
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == '_'):
                i += 1
            tokens.append(Token('identifier', text[start:i], start, i))
            continue
        i += 1
        tokens.append(Token('punctuation', char, start, i))
    return tokens


def _reference_owner(token: Token | None) -> str | None:
    if token and token.kind == 'table':
        return token.value
    if (token and token.kind == 'identifier'
            and token.value.casefold() not in {'return', 'var', 'in', 'not', 'and', 'or', 'true', 'false'}):
        return token.value
    return None


def dax_references(text: str) -> list[tuple[str | None, str]]:
    tokens = dax_tokens(text)
    refs = []
    for i, token in enumerate(tokens):
        if token.kind != 'object':
            continue
        previous = tokens[i - 1] if i else None
        table = _reference_owner(previous)
        refs.append((table, token.value))
    return refs


def rewrite_dax(text: str, *, tables=None, measures=None, objects=None, unqualified=True) -> tuple[str, int]:
    tables = tables or {}
    measures = measures or {}
    objects = objects or {}
    measures = {**measures, **{key: value[1] for key, value in objects.items()}}
    tokens = dax_tokens(text)
    edits = []
    # A VAR sharing a bare table name changes lexical binding. Never rewrite it
    # as a table; qualified references and quoted table tokens stay explicit.
    variables = {tokens[i + 1].value.casefold() for i, t in enumerate(tokens[:-1])
                 if t.kind == 'identifier' and t.value.casefold() == 'var'}
    for i, token in enumerate(tokens):
        previous = tokens[i - 1] if i else None
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if token.kind in ('table', 'identifier'):
            target = tables.get(token.value.casefold())
            object_target = objects.get((token.value.casefold(), following.value.casefold())) if following and following.kind == 'object' else None
            if object_target:
                target = object_target[0]
                if target.casefold() == token.value.casefold():
                    target = None
            if target and not (token.kind == 'identifier' and
                               (token.value.casefold() in variables or
                                (following and following.value == '('))):
                edits.append((token.start, token.end, quote_dax_table_name(target)))
        if token.kind == 'object':
            owner = _reference_owner(previous)
            table = owner.casefold() if owner is not None else None
            target = measures.get((table, token.value.casefold()))
            if target is None and table is None and unqualified:
                matches = {value for (owner, name), value in measures.items() if name == token.value.casefold()}
                target = next(iter(matches)) if len(matches) == 1 else None
            if target:
                edits.append((token.start, token.end, '[' + quote_dax_object_name(target) + ']'))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text, len(edits)


def transform_tmdl_expressions(text: str, transform) -> tuple[str, int]:
    """Transform explicit DAX sites, retaining indentation and all other text."""
    lines = text.splitlines(keepends=True)
    output = []
    count = 0
    i = 0
    partition_kind = None
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if re.match(r'partition\s', stripped, re.I):
            partition_kind = stripped.rsplit('=', 1)[-1].strip().casefold()
        elif indent <= 1 and stripped.strip() and not stripped.startswith('//'):
            partition_kind = None
        declaration = re.match(r'\s*(?:measure|column|calculationItem|tablePermission)\s+.+?\s*=\s*', line, re.I)
        prop = re.match(r'\s*(?:expression|filterExpression|detailRowsDefinition|defaultDetailRowsDefinition)\s*=\s*', line, re.I)
        source = re.match(r'\s*source\s*=\s*', line, re.I) if partition_kind == 'calculated' else None
        match = declaration or (prop if indent > 0 and partition_kind != 'm' else None) or source
        if not match:
            output.append(line)
            i += 1
            continue
        # Preserve newline after an empty '=' so continuation indentation survives.
        prefix_end = match.end()
        while prefix_end and line[prefix_end - 1] in '\r\n':
            prefix_end -= 1
        end = i + 1
        fenced = end < len(lines) and lines[end].strip() == '```'
        fence_count = 0
        role_expression = stripped.casefold().startswith('tablepermission ')
        while end < len(lines):
            next_line = lines[end]
            next_indent = len(next_line) - len(next_line.lstrip())
            if next_line.strip() and next_indent <= indent:
                break
            # Item properties are one level deeper; multiline item DAX uses three tabs.
            if declaration and not role_expression and not fenced and next_line.strip() and next_indent <= indent + 1:
                break
            if fenced and next_line.strip() == '```':
                fence_count += 1
                if fence_count == 2:
                    end += 1
                    break
            end += 1
        expression = line[prefix_end:] + ''.join(lines[i + 1:end])
        rewritten, changes = transform(expression)
        output.append(line[:prefix_end] + rewritten)
        count += changes
        i = end
    return ''.join(output), count
