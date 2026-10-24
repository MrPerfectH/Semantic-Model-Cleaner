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


class DaxBindingError(DaxCoverageError):
    """A required external binding is missing in this model/report scope."""


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
                if n + 1 < len(tokens) and tokens[n + 1].value == "(" and name not in STATIC_FUNCTIONS and name not in {"return", "evaluate", "in"}:
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


def query_references(text, *, items=None):
    """Conservative external bindings, including whole-table owner consumers.

    With items supplied, every external binding must resolve in that report's
    model/extension scope. Virtual names are resolved by expression ownership.
    """
    from .saved_dax_bindings import bind_query
    try:
        return bind_query(text, items)
    except RecursionError as exc:
        raise DaxCoverageError("Saved query binding nesting exceeds the supported bound.") from exc
