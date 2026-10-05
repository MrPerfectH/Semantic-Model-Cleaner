# Analysis limitations are a separate surface from Report Health

## Status

accepted

## Context

The 0.4.0b2 beta showed Unsupported Metadata inside the Report Health banner
and repeated every shared coverage gap as a Review reason on every unused item.
On one private workspace that produced 3,911 warning occurrences from 424
affected items: nine shared limitations per item plus 95 item-specific
findings. Users read the number as a count of distinct problems, and the Report
Health framing implied that valid model configuration (a calculation group, a
KPI) was a report defect that needed repair.

Two detection faults made it worse (issues #82 and #83):

- Feature detection matched the substring `kpi` anywhere in a TMDL line, so a
  table named `KPI Selector`, a description mentioning KPI flags or a string
  literal produced KPI-expression limitations in files with no KPI declaration.
- Known evidence was described as a generic limitation. Perspective membership
  became "Unsupported Metadata: Perspectives", and a calculation-group selector
  showed "Unused, zero DAX consumers, Review" although the analyzer already
  recorded retained measures referencing the parent table and the deletion
  policy already blocked whole-group deletion because of them.

## Decision

1. **Detection comes from TMDL declarations.** `tmdl_declarations.py` scans the
   indentation-based declaration tree and recognises constructs only where the
   grammar places them: a `kpi` object under a measure, a `calculationItem`
   under a `calculationGroup`, a `detailRowsDefinition` property. Names,
   descriptions, comments, string literals and DAX bodies never produce a
   finding. Each finding carries the owning object and `file:line`.
2. **Evidence is not a limitation.** Perspective membership and
   calculation-group structure are concrete metadata facts. Calculation-group
   structure appears as item-specific Review reasons that name the group and its
   retained parent-table consumers. Perspective membership is informational
   evidence naming the perspective and the member: a perspective is a view over
   the model, not a consumer, so membership never counts as a Report Reference or
   proof of runtime use and never changes the Cleanup Recommendation (an unused
   member stays Safe; deleting it also removes the member). Owner decision
   2026-10-05, issue #101; this supersedes the earlier wording that listed
   membership among the Review reasons.
3. **Analysis limitations get their own surface.** The analyzer returns a
   distinct `analysis_limitations` list. Each entry states the feature, owning
   object, source location, what was checked, what remains unchecked and the
   effect on the Cleanup Recommendation. Shared limitations (unresolved or
   dynamic coverage such as `SELECTEDMEASURE()`) still keep every unused item
   at Review, but an item shows one collapsed line for them instead of one line
   per limitation. Report Health lists report-side problems only.
4. **Counts use explicit units.** Browser, JSON export, Excel summary, CLI
   Markdown and `smc check` report distinct limitations and affected items.
   Repeating a shared reason on an item never increments the distinct count.
5. **Coverage stays conservative.** Unknown or dynamic expressions are never
   claimed as fully analysed. `coverage.complete` and the `SMC-D002` deletion
   guard keep their meaning; a calculation item that applies to arbitrary
   measures still prevents an unjustified Safe recommendation.

## Consequences

- The Report Health `unsupported_metadata` group and the
  `signalCounts.unsupportedMetadata` field are gone; clients read
  `analysisLimitations` instead. `coverage.limitations` entries gained
  `id`, `feature`, `owner`, `line`, `checked`, `unchecked`, `effect` and `scope`.
- `SMC003` findings are emitted per construct with owner and location rather
  than per file and area, so their fingerprints changed. `SMC003` is a coverage
  rule and was never baseline-suppressible.
- Whole-group deletion of a calculation group with dynamic items remains
  blocked by `SMC-D002` even in a coordinated plan, because the fresh analysis
  cannot evaluate a final state in which the group file is gone. Evaluating
  deletions against a simulated final state is a later slice; the parent-table
  guard (`SMC-D006`) already evaluates the proposed final state for ordinary
  tables.
- Property declarations that are not part of TOM (such as a hypothetical
  `secondaryExpression`) are no longer treated as a feature. Detectors cover
  calculation groups and items, calculation-item format strings, selection
  expressions, KPI target/status/trend expressions, detail rows, format string
  definitions, data coverage definitions and culture/translation files.
