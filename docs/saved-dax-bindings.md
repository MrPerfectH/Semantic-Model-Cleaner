# Saved DAX query binding coverage

Saved query analysis is a bounded static binding check. It does not execute DAX,
infer data values, validate DAX types, or claim compiler parity.

The binding tree gives each expression its own variable scope. Query-global
variables are available after their declaration; local variables are confined to
their VAR/RETURN expression. Every declaration body contributes dependencies,
including unused variables and unused or shadowing DEFINE MEASURE definitions.
A DEFINE MEASURE always retains its model owner table.

Table expressions carry a schema of named columns and their origins. Supported
schema operations include ROW, SELECTCOLUMNS, ADDCOLUMNS, SUMMARIZE,
SUMMARIZECOLUMNS, rollups, ADDMISSINGITEMS, FILTER, TOPN, common iterators,
CALCULATETABLE, VALUES/FILTERS/DISTINCT/ALL variants, natural joins, CROSSJOIN,
SUBSTITUTEWITHINDEX and bounded set operations. A virtual column is visible only
through its source table expression and supported row/output contexts. A string
literal elsewhere cannot declare it. Each EVALUATE has its own ORDER BY schema.

A whole-table reference conservatively retains every enumerated model item in
that table, including its last item. This intentionally trades precision for
safety. Model and report extension references are resolved only within the
selected report's scope. Query-local measure shadowing does not cross reports.

Unknown functions, dynamic references, unresolved or ambiguous objects, duplicate
virtual columns, self/forward variables, unknown consumed table schemas and
excessive nesting remain explicit Analysis Limitations. Unsupported syntax is not
described as malformed PBIR JSON. Missing external bindings are errors so staged
rename validation cannot strand an unchanged saved query.

The optional item inventory on query_references supplies scope resolution.
Production analysis and report deletion assessment both supply it. Without an
inventory the helper returns symbolic external references that the caller must
resolve; this mode alone is not proof of complete model coverage.

The safety invariants are:
- Every external binding in every visited body is retained or causes a coverage
  error. Transitive variable dependencies cannot disappear when a variable is
  reused or shadowed.
- Function-specific schema propagation is the only way a virtual column reaches
  another expression. Ambiguous ownership cannot select a convenient model item.
- Whole-table and DEFINE owner consumers protect table existence.
- Unresolved scope remains fail closed.
- Query inventory, byte fingerprints, staging, race checks, cache lifetimes and
  exact restore are unchanged by binding expansion.

Synthetic regression tests cover those boundaries and deletion behavior. Native
TOM validates an offline object graph; runtime query and Desktop acceptance remain
separate evidence.
