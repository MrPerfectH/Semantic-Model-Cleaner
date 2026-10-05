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
   calculation-group structure are concrete metadata facts. They appear as
   item-specific Review reasons that name the perspective, the member, the group
   and its retained parent-table consumers. Membership alone never counts as a
   Report Reference or proof of runtime use; the existing reviewed-change policy
   (Review) still applies.
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
- Deletion plans are evaluated against a simulated final state (issue #91).
  The fresh analysis still reads the current files, but the deletion policy
  then drops shared limitations whose owning table the plan removes completely
  and that no retained structural or DAX consumer still references
  (`SMC-D006` finds none). `coverage.complete` for the plan
  (`policy.scope.complete`, `plan.coverage.final_state`) and `SMC-D002` are
  computed from the remaining limitations; each cleared gap is listed in
  `scope.cleared_limitations` and in the plan preview's validation notes
  ("Coverage gap owned by '<group>' is cleared because the plan removes the
  calculation group and every retained parent-table consumer."). For removed
  items, the collapsed shared-coverage reason and the calculation-group
  structure reasons are re-derived against that final state; every other
  Review reason (hidden, key, perspective membership, targeted metadata) and
  every other guard still applies. Deleting only the group keeps both
  `SMC-D006` and its own `SMC-D002`. Limitations owned by any retained object,
  report-scan gaps and model-level constructs never clear, and targeted
  limitations whose owner remains still apply to remaining items.
- Property declarations that are not part of TOM (such as a hypothetical
  `secondaryExpression`) are no longer treated as a feature. Detectors cover
  calculation groups and items, calculation-item format strings, selection
  expressions, KPI target/status/trend expressions, detail rows, format string
  definitions, data coverage definitions and culture/translation files.
- Calculation groups and field parameters are tool entities (issue #103).
  An unused entity, with no retained consumer outside it, stays at Review
  with exactly one reason, "Entity type requires confirmation", instead of
  the hidden flag, group-structure or internal sort reasons of its own
  columns. Items report `review_basis` (`entity_type` or `evidence`) and the
  summary splits the Review count accordingly. That split sits with the
  cleanup counts, not in Report Health, which stays limited to report-side
  problems. A plan that removes the whole entity, with nothing remaining
  that uses it, waives those internal reasons and returns one `confirmations`
  entry, shown in the plan preview, rather than an `SMC-D005` violation.
  Partial plans keep the item-alone reasons, and every guard on objects
  outside the entity still applies.
