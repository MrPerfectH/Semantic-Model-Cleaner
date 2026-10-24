# Saved-query argument and generated-format coverage

The saved-query binder is a bounded symbolic scanner, not a DAX evaluator.
Iterator row schemas apply only to expression arguments. RANKX's expression
uses its table row; its value, order and ties arguments keep the caller context,
including an existing outer row. TOPN's sorting expressions and CONCATENATEX's
expression/sorting expressions use the table row. Their scalar options,
CONCATENATEX's delimiter and MINX/MAXX's variant argument keep caller context.
SUBSTITUTEWITHINDEX similarly separates sorting expressions from order options.

A bare bracket matching both a row column and a model/report measure is an
Analysis Limitation. The binder does not settle DAX name precedence by silently
choosing the column. Explicit qualified bindings remain available; unsupported
or ambiguous bindings keep deletion fail closed.

A missing persisted identity shaped like `_Revenue FormatString` is classified
as an unsupported generated dynamic-format binding only when the exact native
`Revenue` measure in the specified table (or current unqualified scope) has a
nonempty parsed `formatStringDefinition`. It is not accepted as a dependency:
generated lineage and runtime validity remain unverified. Suffix alone, static
format strings and report-only owner metadata do not establish that native
owner. Persisted helper identities and DEFINE declarations follow normal
binding rules. Neither query filenames nor private model identities are used.

This diagnostic change does not authorize source repair or establish a mapping
for missing persisted references. Original queries must retain their bytes until
the user supplies an authoritative source revision or correction mapping.

Argument roles checked against primary documentation:
- https://learn.microsoft.com/en-us/dax/rankx-function-dax
- https://learn.microsoft.com/en-us/dax/topn-function-dax
- https://learn.microsoft.com/en-us/dax/concatenatex-function-dax
- https://learn.microsoft.com/en-us/dax/minx-function-dax
- https://learn.microsoft.com/en-us/dax/maxx-function-dax
- https://learn.microsoft.com/en-us/dax/substitutewithindex-function-dax

Audit boundaries: ROW/ADDCOLUMNS/SELECTCOLUMNS name/expression pairs preserve
their existing contexts; SUMMARIZE grouping and name/expression handling is
unchanged. ADDMISSINGITEMS grouping metadata remains bounded by its existing
schema checks. Joins retain existing schema/collision checks; no new correlated
join semantics are asserted. Unknown consumed schemas remain unsupported.
