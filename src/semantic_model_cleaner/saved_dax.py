"""Static reference coverage for saved DAX queries; never executes DAX.

This is a reference lexer, not a type checker or DAX evaluator. Every expression
body (including unused DEFINE measures/variables) contributes dependencies.
Unsupported binding constructs and incomplete lexical input fail closed.
"""
from __future__ import annotations

from .reference_tokens import dax_tokens, _reference_owner as _owner

# Built-in scalar/table functions whose dependencies use lexical DAX identifiers.
# New functions/UDFs require an explicit coverage test; never infer their safety.
STATIC_FUNCTIONS = frozenset('''
ABS ADDCOLUMNS ADDMISSINGITEMS ALL ALLCROSSFILTERED ALLEXCEPT ALLNOBLANKROW ALLSELECTED
AND AVERAGE AVERAGEX BLANK CALCULATE CALCULATETABLE CEILING COALESCE COMBINEVALUES
CONCATENATE CONCATENATEX CONTAINS CONTAINSROW CONTAINSSTRING CONTAINSSTRINGEXACT
COUNT COUNTA COUNTAX COUNTBLANK COUNTROWS COUNTX CROSSJOIN CURRENTGROUP
DATE DATEADD DATEDIFF DATESBETWEEN DATESINPERIOD DATESMTD DATESQTD DATESYTD DATEVALUE DAY
DISTINCT DISTINCTCOUNT DIVIDE EARLIER EARLIEST ENDOFMONTH ENDOFQUARTER ENDOFYEAR
EXCEPT FILTER FILTERS FIND FIRSTDATE FIRSTNONBLANK FIRSTNONBLANKVALUE FLOOR FORMAT
GENERATE GENERATEALL GENERATESERIES GROUPBY HASONEFILTER HASONEVALUE HOUR IF IFERROR
IGNORE INDEX INT INTERSECT ISAFTER ISBLANK ISCROSSFILTERED ISEMPTY ISERROR ISFILTERED
ISINSCOPE ISNUMBER ISSELECTEDMEASURE ISTEXT KEEPFILTERS LASTDATE LASTNONBLANK LASTNONBLANKVALUE
LEFT LEN LOOKUPVALUE LOWER MAX MAXA MAXX MEDIAN MEDIANX MID MIN MINA MINUTE MINX MOD
MONTH NATURALINNERJOIN NATURALLEFTOUTERJOIN NEXTMONTH NEXTQUARTER NEXTYEAR NOT NOW
OFFSET OR ORDERBY PATH PATHCONTAINS PATHITEM PATHLENGTH PERCENTILEX_INC POWER
PREVIOUSMONTH PREVIOUSQUARTER PREVIOUSYEAR PRODUCT PRODUCTX QUARTER RANK RANKX
RELATED RELATEDTABLE REMOVEFILTERS REPLACE REPT RIGHT ROLLUP ROLLUPADDISSUBTOTAL
ROLLUPGROUP ROLLUPISSUBTOTAL ROUND ROUNDDOWN ROUNDUP ROW SAMEPERIODLASTYEAR SEARCH
SECOND SELECTCOLUMNS SELECTEDVALUE SIGN SQRT STARTOFMONTH STARTOFQUARTER STARTOFYEAR
SUBSTITUTE SUBSTITUTEWITHINDEX SUM SUMMARIZE SUMMARIZECOLUMNS SUMX SWITCH TIME TODAY TOPN TOTALMTD TOTALQTD
TOTALYTD TREATAS TRIM TRUE FALSE TRUNC UNICHAR UNION UPPER USERELATIONSHIP USERNAME
USERPRINCIPALNAME UTCNOW UTCTODAY VALUE VALUES WEEKDAY WEEKNUM WINDOW YEAR
'''.casefold().split())


def _reference_owner(token):
    if token and token.kind == "identifier" and token.value.casefold() in {
            "evaluate", "by", "asc", "desc", "at", "define", "measure"}:
        return None
    return _owner(token)



class DaxCoverageError(ValueError):
    """The reference surface cannot be covered statically."""


def covered_tokens(text):
    # Validate lexical closure before using the shared tokenizer, whose historic
    # permissive behavior is retained for its other consumers.
    i = 0
    while i < len(text):
        if text.startswith(("//", "--"), i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise DaxCoverageError("Unterminated DAX comment.")
            i = end + 2
        elif text[i] in ('"', "'", '['):
            close = ']' if text[i] == '[' else text[i]
            i += 1
            while True:
                if i >= len(text):
                    raise DaxCoverageError("Unterminated DAX string or identifier.")
                if text[i] == close:
                    i += 1
                    if i < len(text) and text[i] == close:
                        i += 1
                    else:
                        break
                else:
                    i += 1
        else:
            i += 1
    tokens = dax_tokens(text)
    stack = []
    opaque = {"selectedmeasure", "selectedmeasurename", "isselectedmeasure",
              "externalmeasure", "evaluateandlog"}
    for n, token in enumerate(tokens):
        if token.kind != "punctuation":
            if token.kind == "identifier":
                name = token.value.casefold()
                if name in opaque:
                    raise DaxCoverageError("Dynamic DAX reference context: " + token.value)
                if n + 1 < len(tokens) and tokens[n + 1].value == "(" and name not in STATIC_FUNCTIONS:
                    raise DaxCoverageError("Unsupported DAX function: " + token.value)
            continue
        if token.value in "({":
            stack.append(token.value)
        elif token.value in ")}":
            if not stack or stack.pop() != {")": "(", "}": "{"}[token.value]:
                raise DaxCoverageError("Unbalanced DAX delimiters.")
        elif token.value == ".":
            # Decimal literals are harmless; dotted function/namespace access
            # can invoke a UDF whose dependencies are not in this query.
            before = tokens[n - 1].value if n else ""
            after = tokens[n + 1].value if n + 1 < len(tokens) else ""
            if not (before.isdigit() and after.isdigit()):
                raise DaxCoverageError("Unsupported DAX namespace or member access.")
        elif token.value == "|":
            if not ((n and tokens[n - 1].value == "|") or (n + 1 < len(tokens) and tokens[n + 1].value == "|")):
                raise DaxCoverageError("Incomplete DAX OR operator.")
        elif token.value not in "+-*/^&=<>!,;:%0123456789":
            raise DaxCoverageError("Unsupported DAX token: " + token.value)
    if stack:
        raise DaxCoverageError("Unbalanced DAX delimiters.")
    return tokens


def expression_references(text):
    tokens = covered_tokens(text)
    return [( _reference_owner(tokens[n - 1] if n else None), token.value)
            for n, token in enumerate(tokens) if token.kind == "object"]


def query_references(text):
    """Return external (table-or-None, name) refs after DEFINE shadowing.

    A (table, None) reference retains a DEFINE MEASURE owner table. It is
    required even for an unused or fully shadowing local declaration. Callers
    must resolve it against model items and protect the table from disappearing.

    Qualified local references shadow only their exact identity. Bare local
    references shadow by unique local name. Every local body is scanned, so
    transitive external dependencies remain even when a body is not evaluated.
    """
    tokens = covered_tokens(text)
    if not tokens:  # An untouched/comment-only editor tab has no references.
        return []
    def word(n, value):
        return n < len(tokens) and tokens[n].kind == "identifier" and tokens[n].value.casefold() == value
    if not (word(0, "define") or word(0, "evaluate")):
        raise DaxCoverageError("Expected DEFINE or EVALUATE in saved DAX query.")
    if sum(t.kind == "identifier" and t.value.casefold() == "define" for t in tokens) > 1:
        raise DaxCoverageError("Multiple DEFINE blocks are unsupported.")
    declarations = set()
    local = set()
    depth = 0
    evaluated = False
    definitions = 0
    for n, token in enumerate(tokens):
        if token.kind == "punctuation":
            if token.value in "({":
                depth += 1
            elif token.value in ")}":
                depth -= 1
        if token.kind != "identifier":
            continue
        value = token.value.casefold()
        if value in {"function", "column", "table"} and depth == 0:
            raise DaxCoverageError("Unsupported DEFINE " + value.upper() + " binding.")
        if value == "evaluate" and depth == 0:
            evaluated = True
            if n + 1 == len(tokens):
                raise DaxCoverageError("Empty EVALUATE expression.")
        if value != "measure" or depth:
            continue
        if evaluated or not word(0, "define"):
            raise DaxCoverageError("MEASURE declaration outside DEFINE.")
        if (n + 4 >= len(tokens) or tokens[n + 1].kind not in {"identifier", "table"}
                or tokens[n + 2].kind != "object" or tokens[n + 3].value != "="
                or (tokens[n + 4].kind == "identifier" and tokens[n + 4].value.casefold() in {"measure", "evaluate"})):
            raise DaxCoverageError("Malformed DEFINE MEASURE declaration.")
        key = (tokens[n + 1].value.casefold(), tokens[n + 2].value.casefold())
        if key in local or any(name == key[1] for _, name in local):
            raise DaxCoverageError("Ambiguous duplicate DEFINE MEASURE name.")
        local.add(key)
        declarations.add(n + 2)
        definitions += 1
    if not evaluated:
        raise DaxCoverageError("Saved DAX query has no EVALUATE statement.")
    if word(0, "define") and not definitions and not any(word(n, "var") for n in range(len(tokens))):
        raise DaxCoverageError("Empty or unsupported DEFINE block.")
    # Item references alone cannot describe a whole-table result: removing any
    # column can change EVALUATE/FILTER/ALL/VALUES(table). Until table lineage
    # is represented, standalone table bindings must make coverage incomplete.
    # Only query-global DEFINE VAR names have a provable scope here; local VAR
    # expression scopes, VAR after MEASURE, and other bare identifiers are
    # deliberately unsupported. A VAR is visible only in later bindings/evaluation.
    variables = {}
    pending_variable = None
    measure_body = False
    variable_declarations = set()
    depth = 0
    evaluated = False
    for n, token in enumerate(tokens):
        if token.kind == "punctuation":
            if token.value in "({":
                depth += 1
            elif token.value in ")}":
                depth -= 1
        if word(n, "return"):
            raise DaxCoverageError("Unsupported local VAR binding scope.")
        if depth == 0 and any(word(n, keyword) for keyword in ("var", "measure", "evaluate")):
            if pending_variable is not None:
                variables[pending_variable] = n
                pending_variable = None
            if word(n, "measure"):
                measure_body = True
        if word(n, "evaluate") and depth == 0:
            evaluated = True
        if not word(n, "var"):
            continue
        if (depth or evaluated or measure_body or not word(0, "define") or n + 3 >= len(tokens)
                or tokens[n + 1].kind != "identifier" or tokens[n + 2].value != "="):
            raise DaxCoverageError(
                "Unsupported local or malformed VAR binding: "
                + ("expression-local VAR inside nested delimiters; lexical scope and transitive bindings are not resolved."
                   if depth else "VAR after EVALUATE; expression-local scope is not resolved."
                   if evaluated else "VAR following DEFINE MEASURE; declaration boundary and lexical scope are not resolved."
                   if measure_body else "expected query-global DEFINE VAR name = expression."))
        name = tokens[n + 1].value.casefold()
        if name in variables:
            raise DaxCoverageError("Ambiguous duplicate VAR binding.")
        variables[name] = len(tokens)  # Self/forward references have no proven binding.
        pending_variable = name
        variable_declarations.add(n + 1)
    keywords = {"define", "measure", "evaluate", "var", "order", "by",
                "asc", "desc", "start", "at", "return", "in", "not",
                "and", "or", "true", "false"}
    for n, token in enumerate(tokens):
        if token.kind not in {"identifier", "table"}:
            continue
        following = tokens[n + 1] if n + 1 < len(tokens) else None
        if following and following.kind == "object":
            continue  # Explicit item owner, including DEFINE MEASURE owner.
        if token.kind == "identifier":
            if n in variable_declarations or token.value.casefold() in keywords:
                continue
            if following and following.value == "(":
                continue  # covered_tokens already checked the function allowlist.
            available = variables.get(token.value.casefold())
            if available is not None and n >= available:
                continue
        raise DaxCoverageError("Unsupported standalone table or identifier binding: " + token.value)
    # DEFINE shadowing removes references to the local *measure*, never its
    # required model owner table. Consumers conservatively retain every model
    # item in that table rather than guessing which surviving item anchors it.
    refs = [(table, None) for table in dict.fromkeys(
        tokens[n - 1].value for n in sorted(declarations))]
    names = {name for _, name in local}
    for n, token in enumerate(tokens):
        if token.kind != "object" or n in declarations:
            continue
        table = _reference_owner(tokens[n - 1] if n else None)
        if ((table is None and token.value.casefold() in names)
                or (table is not None and (table.casefold(), token.value.casefold()) in local)):
            continue
        refs.append((table, token.value))
    return refs
