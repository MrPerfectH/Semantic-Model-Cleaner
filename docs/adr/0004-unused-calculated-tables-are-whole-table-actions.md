# Unused calculated tables are explicit whole-table cleanup actions

## Status

accepted (repo owner approval from the CLI agent benchmark follow-up)

## Context

An engine-inferred calculated-table column is output of its partition expression.
Deleting a column's TMDL declaration cannot remove that output. Keeping such
columns individually is correct, but keeping a completely unused calculated
table forever prevents complete cleanup. Report References are case-insensitive,
and a Report using another Semantic Model is not a consumer in this scope.

## Decision

- Keep inferred columns from individual deletion and explain the expression-edit
  requirement. Do not label the inferred flag as Report usage.
- Offer a whole-table action for an unused calculated table, removing its
  declaration, partition, inferred columns and memberships together. Only a
  consolidated declaration is written; split definitions fail closed.
- Use the ordinary deletion policy for retained DAX, NAMEOF, relationships,
  metadata consumers, calendar/detail-rows constructs, Report References and
  Analysis Limitations. A retained bare-table consumer such as `COUNTROWS(T)`
  blocks the table action even if all its columns have no Live Report Reference.
- Keep Tool Entity rules from ADR 0002: this automatic cleanup does not silently
  confirm calculation groups or field parameters.
- Hidden-only Review remains protected by default. `--include-review` records
  explicit hidden-flag approval in the saved actions; it waives no other reason.
- A dependency-closed cleanup is one reviewed plan, staged and validated once.
  Retaining a blocked owner also retains its required targets. An unresolved
  visual-property expression naming a model measure conservatively retains that
  measure until its entity binding is resolved.

## Consequences

`items --unused` exposes whole-table options separately from column actions.
`smc plan PROJECT --cleanup unused --cascade -o PLAN` selects the supported
closure, emits concrete kept reasons, and uses existing apply/verify/recovery.
It never edits a calculated expression to remove inferred columns one by one,
uses model-folder comparisons, or performs runtime DAX tests.
