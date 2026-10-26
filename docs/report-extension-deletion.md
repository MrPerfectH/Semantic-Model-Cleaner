# Delete report extension measures (#168)

Report extension measures have a distinct operation: `delete_report_measures`.
A target is an absolute selected report path, an entity (`table`), and a measure
`name`. A model measure or another report's same-named measure is never a fallback.

The analysis JSON and browser API expose `reportMeasureDelete` on report items:
`eligible` means the item can be deleted alone; `groupEligible` means the explicitly
listed `requiredGroup` can be deleted together. The UI enables Delete for these
supported candidates. Select every required group member, then review the actual
diff and validation before applying. Blocked items expose their reasons. These are
operation eligibility fields. An unused blocked item receives Review with its coverage or dependency reason; a closed group receives Caution.

## Minimal operation

Save this as an operations file outside the model/report directories, replacing
the report path with the actual absolute path:

```json
{
  "schema_version": "1.0",
  "operations": [{
    "kind": "delete_report_measures",
    "entries": [{
      "report_path": "C:/Projects/Demo/Reports/Sales.Report",
      "table": "Sales",
      "name": "Unused local measure"
    }]
  }]
}
```

Run the supported CLI workflow (the same plan API powers the browser):

```powershell
smc plan C:/Projects/Demo --model C:/Projects/Demo/Models/Demo.SemanticModel --report C:/Projects/Demo/Reports/Sales.Report --operations operations.json -o reviewed.plan.json --format json
smc diff reviewed.plan.json
smc apply reviewed.plan.json --journal-dir C:/Projects/ReviewJournal --format json
smc verify reviewed.plan.json --format json
smc restore reviewed.plan.json --journal-dir C:/Projects/ReviewJournal --format json
```

For an unused chain `Top -> Middle -> Leaf`, deleting Leaf alone is blocked
while Middle remains. List Top, Middle, and Leaf as three entries to remove the
closed group. There is no implicit cascade. A visible, hidden, indirect, stale, or
possible opaque metadata reference to Top protects its whole dependency chain.
A qualified DAX reference resolves within the owning report/entity; an ambiguous
bare name conservatively retains all matching local candidates.

## Safety and preservation

- Selected reports must have a verified local byPath binding to the exact selected model. Name-only live bindings are insufficient for this operation. Unselected report
  extensions and their consumers do not enter the report-local deletion graph.
- The extension must validate against its bundled schema. Missing, duplicate,
  malformed, unrecognized, dynamic, or unresolved extension dependencies block
  deletion. A name colliding with a model measure is blocked.
- Supported analyzer coverage is required. Every report JSON/PBIR document is
  read with duplicate-property rejection. The scanner includes visuals, filters,
  slicers, bookmarks, drillthrough, conditional formatting, hidden surfaces and
  additional metadata. A conservative string scan also blocks possible references
  on opaque surfaces, including stale selectors. This may retain a measure whose
  name occurs in a title or descriptive string; it never rewrites that text.
  Invalid or unknown declared schemas and unsupported report-extension DAX block deletion within the affected report.
- Report extension deletion is a separate plan; model changes, reference repair,
  promotion and stale cleanup must be reviewed first in their own plans.
- Only selected measure JSON objects and their adjacent array separators are
  removed. Empty entities and arrays remain. Retained bytes, expressions,
  annotations and unrelated report files stay unchanged. Metadata owned by a
  deleted measure disappears with that measure.
- Plan validation checks schema changes and newly unresolved references on staged
  copies. The plan records each deletion and its required group. All selected model metadata and every selected report file except developer scratch queries and their DAX editor index are fingerprinted; any drift before apply blocks the whole operation.
- The shared transaction records exact original bytes in the saved plan and an
  atomic journal. Apply failures roll back completed writes. Restore refuses to
  overwrite later user edits and otherwise restores the exact original bytes.
- Verification proves that current metadata matches the statically validated
  planned output. It does not refresh data, execute DAX, or establish rendered
  visual parity.


## Coverage and identity rules

External/saved .dax queries are developer scratch files outside model/report cleanup scope. They do not contribute usage, coverage gaps, blockers or plan inputs. Apply and restore leave their current bytes and inventory untouched, including queries changed after preview or apply.

The [reportExtension schema](https://github.com/microsoft/json-schemas/blob/5e1199a15b80e3d51198fe017b1a6fb9bb0871a6/fabric/item/report/definition/reportExtension/1.0.0/schema.json)
defines explicit reference binding: omitted/empty schema means model; the
extension name means that report's extension. Neither resolver falls back from a
missing model reference to a report measure. Extension names must be unique
across model measures and the report's extensions, even across different tables.

An empty expression still has an identity and may have incoming dependencies.
It remains retained with an explicit reason. The standard producer flag
`unrecognizedReferences: true` also retains its owner. When complete lexical
coverage proves the finite static reference set, every matching dependency is
retained and independent identities may be deleted. Missing static targets do
not invent edges to unrelated names. An opaque or dynamic expression instead
blocks its whole report. No defective metadata is repaired or removed to obtain
coverage; retained measure properties and bytes are preserved by the span writer.

Coverage is evaluated separately for each selected report. An unsupported report-extension expression,
unknown schema or invalid metadata in one report does not poison an independent
report's extension assessment. The plan still verifies every selected report's
binding and bytes and rejects new unresolved references or schema errors.
Model-wide metadata limitations cannot hide consumers of report-local measures,
because model expressions do not bind to report extensions.

The exact pinned Microsoft schema bundle now includes visualContainer 2.10ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ2.13
and their dependencies. The recursive reference/string scan also covers nested
formatting expressions in these versions. Unknown 2.14 remains blocked; a new
version requires an official source snapshot, dependency closure and fixtures.
Unused report rows with blocked eligibility receive Review and explicit reasons;
dependency-closed groups receive Caution and the complete required selection.


Scratch query scope includes the exact `DAXQueries/.pbi/daxQueries.json` editor index. Its contents, including unsupported or malformed state, do not affect cleanup eligibility, coverage or plan drift. Apply and restore preserve concurrent scratch edits, additions and deletions. Declared report resources and files in `StaticResources` keep their resource guards regardless of extension (including `.dax`); a declaration that collides with the editor-index path takes precedence. Other JSON and `.pbi` metadata remain guarded.
