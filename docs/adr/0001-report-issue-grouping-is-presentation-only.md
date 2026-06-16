# Report-issue root-cause grouping is presentation-only

## Status

accepted

## Context

On a real workspace (PMRA_POC vs its 7 live-connected reports) the Report Health
surface produces ~6,363 Report Reference issues. The issues collapse to a small
number of root causes — most are the fallout of two model-side renames (the table
`IW_49n` → `'Work Order Maintenance (IW_49n)'` alone accounts for ~1,409 of them) —
and ~5,783 of the issues live on hidden report pages. The flat list is a wall, not
help.

The obvious next step seemed to be "group by root cause, then offer a one-click
*repair the references for this rename*", reusing the existing model-rename
rewrite machinery. Code inspection (`design-report-issue-grouping` workflow,
2026-06-16) found that path is not safe to ship yet:

- `rewrite_model_reference_changes` rewrites a Report Reference's **table** name
  (`SourceRef.Entity`) but never its **column** name (`Column.Property`,
  `report_writer.py:560-593`), so the `Cost_Center` → `'Cost Center'` column
  rename cannot be repaired without new engine code.
- `_fuzzy_suggestions` forces **High** confidence on any exact name match
  regardless of which table it lives in (`analyzer.py:2153-2154`), so a shared
  column name can yield a confident-but-wrong target. A one-click repair applied
  across hundreds of references on a wrong-High suggestion is the
  report-corrupting outcome we most want to avoid.
- The existing broken-reference write path, `apply_report_issue_actions`
  (`report_writer.py:1144`), has no `file_transaction` snapshot, no PBIR
  validation, and no dry-run, and `_remove_related_references` (line 1124)
  deletes every sibling reference to the same `table[name]` — more than the user
  selected. Amplifying that to group scale escalates the half-written-report risk.

## Decision

The first slice of report-issue root-cause grouping is **presentation-only**:

- Group broken Report References by their **target Semantic Model Item** (the
  missing table/column/measure) — one root cause, one card. Group Stale Report
  References separately by selector kind.
- Lead with an impact split (references on **visible** vs **hidden** report
  surfaces), since most issues are on hidden pages.
- Label cards **cause-neutrally** ("N Report References to a missing item under
  table X"); the closest current item is shown only as a **Review**-grade hint,
  never as an asserted rename or an applied action.
- The **only** group-level write action is Stale Report Reference cleanup, which
  already routes through `cleanup_stale_metadata_selectors` (transaction +
  validation + dry-run). Broken-reference cards stop at "select all in group" —
  no group-level remove or repair.

No rename is ever inferred-and-applied as an action in this slice.

## Consequences

- Delivers nearly all the wall-to-help UX win while structurally excluding the
  worst outcome (a wrong repair applied at scale; a half-written report).
- A future reader will ask "why doesn't it just fix the renames?" — the answer is
  the column-rewrite gap, the wrong-High fuzzy match, and the un-transactional
  write path above. Auto-repair is deferred to a later, gated slice that must:
  (1) route through the transactional `rewrite_model_reference_changes`, not
  `apply_report_issue_actions`; (2) handle **table** renames first, columns only
  after the engine learns `Column.Property` rewriting; (3) gate any suggestion
  behind an agreement rule (a dominant target winning a strong majority of the
  group AND existing in the live model).
- Making `apply_report_issue_actions` transactional + validated + dry-run-capable
  is the immediate next slice — it is a latent corruption risk already shipped in
  v0.2.3 and the prerequisite for any future group-scale repair.
- New product vocabulary (the visible/hidden surface tier, the grouping concept,
  the rename "hint") is expressed with the existing CONTEXT.md glossary for now;
  sanctioned terms will be added in a grilling pass when the repair slice is
  designed.
