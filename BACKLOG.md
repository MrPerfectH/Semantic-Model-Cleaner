# Backlog

Last updated: 2026-09-22

## Highest priority

- Time-boxed UX pass on first-session analysis feedback, actionable path errors, and label/legend clarity using the current default tabbed workspace.

## Near-term

- Reconcile [#75](https://github.com/MrPerfectH/Semantic-Model-Cleaner/issues/75) with shipped `smc check`: warning gating and reviewed baselines exist, but `--fail-on-unused` and a Safe-only unused gate do not. Decide whether an unused-specific policy is still needed; preserve the existing check exit contract (0 pass, 1 findings, 2 error).
- Finish the bulk repair CLI experience in [#77](https://github.com/MrPerfectH/Semantic-Model-Cleaner/issues/77): grouped map generation and a dedicated repair command remain missing. Reuse `report_repair` saved plans, including table/column/measure rename maps, exact diff review, freshness checks, receipts and recovery.
- Reduce template duplication between the default tabbed and classic layouts; decide whether to retire classic or extract more shared behavior. Detail workspace, plan, policy and schema code already have separate modules.
- Improve plan review/export ergonomics where needed. Reviewable JSON plans and CLI diff output already ship; a dedicated browser download or Markdown export remains a possible follow-up.
- Add an explicit Protected Items policy that blocks changes to protected items and protects table children during cascading actions. Repository review-policy `keep` decisions currently suppress eligible CI warnings only; they do not prevent edits.
- Expand analyzer fixtures for metadata and report-definition edge cases.
- Reduce repeated verdict fields and long issue messages in large analysis payloads; coordinate the response contract with client-side lookup changes and measure a real large workspace.
- Add search within filter/slicer option lists.

## Medium-term

- Complete calculation-group support and broader metadata/dynamic-reference coverage; current support remains partial and requires review.
- Add BOM-safe TMDL writes with byte-preserving regression coverage before lifting the beta's write block for model scopes containing BOM-prefixed files.
- Extend editing safety checks and recovery regression tests as additional model/report constructs become supported.

## Later

- Improve backup/journal organization and retention without weakening reviewed recovery. Backup before apply stays the default; retained original bytes support guarded restore.
- Evaluate service-wide Fabric discovery separately from the supported local-file workflow.

## Completed recently

- Integrated the large-metadata scan performance fix and first-run model/comparison picker defaults for 0.4.0b2. Release publication remains gated by combined tests, fresh-wheel consumption and downloaded Windows ZIP browser verification.
- Verified the original four-measure pattern from [#74](https://github.com/MrPerfectH/Semantic-Model-Cleaner/issues/74): guard dependencies resolve without missing references. Added an end-to-end regression for both `NOT [guard]` and `NOT[guard]`; source model/report files were unchanged.

- Released public beta 0.4.0b1 with MIT licensing, public installation/support docs, versioned Python and Windows artifacts, checksum sidecars, and source/wheel/downloaded-EXE release gates.
- Made the approved tabbed workspace the default: stable item tabs, contextual properties, inventory filters, scoped drafts, exact saved-plan review, receipts and guarded restore.
- Shipped read-only `smc check` with structured findings, exit codes 0/1/2, warning thresholds and reviewed baselines; added repository review decisions and naming previews.
- Shipped shared saved plans for the web UI and CLI, including model cleanup/refactoring and report-only repairs with table, column and measure maps. Legacy direct-write HTTP routes and `clean-stale --apply` are withheld.
- Replaced per-row report-issue `indexOf` searches with a precomputed map in the default layout.
- Added pinned offline PBIR schema validation and explicit scope/support evidence.

- Removed duplicate Windows builds in the earlier release-event workflow. The current public-beta pipeline builds on version tags and publishes only after Python and Windows verification succeed.
- Made `apply_report_issue_actions` and `cleanup_stale_metadata_selectors` pre-serialize before the snapshot, matching `rewrite_model_reference_changes`. A `json.dumps` failure mid-loop escaped `except OSError`, leaving earlier reports rewritten with no rollback; both writers now build the `(path, text)` list before touching disk, with a regression test each.
- Introduced the v2 layout with persistent left navigation and a scope drawer; it became the default in 0.4.0b1. Classic remains available through the remembered layout switch.
- Cut prerelease v0.3.0 (2026-06-19, PRs #63–#68): testers get the report-issue root-cause grouping, table + column reference repair, and the trust fixes (field-parameter NAMEOF, report-health payload, group-safe removal). Windows zip attached to the GitHub prerelease.
- Made the bundled demo workspace showcase the new feature: "Try the demo workspace" now ships a rename-fallout (a missing `Sales Orders` table renamed to `Orders`, plus renamed `OrderTotal`/`OrderQty` columns) so the root-cause grouping and both table + column repair flows are visible on first click. The clean field-parameter demo and `warnings == []` are preserved.
- Added column-rename repair: `rewrite_model_reference_changes` now rewrites `Column.Property` (and Entity on cross-table move) via `column_renames`; the column-mapping UI maps each missing column (exact-name matches pre-seeded, fuzzy shown as a verify-hint only). Aliased divergent column-moves are skipped with a warning to avoid corrupting siblings.
- Added user-directed table-reference repair (report-only, transactional, dry-run preview); `/api/report/repair-references`.
- Added report-issue root-cause grouping (presentation-only): an impact line (visible vs hidden) and target-keyed cards above the Reports table that collapse thousands of issues into a handful of groups; clicking a card drills the flat table to that group. See `docs/adr/0001-report-issue-grouping-is-presentation-only.md`.
- Added user-directed table-reference repair: drill into a missing-table group, pick the replacement table from the live model, preview the true reference count, and apply via the transactional `rewrite_model_reference_changes` (report files only — the model is never changed). Table-only; columns renamed alongside still surface under the new table.
- Made `apply_report_issue_actions` group-safe: `file_transaction` snapshot + `validate_pbir_json_file` gate + `dry_run` preview; the Reports-tab Remove now previews the true count (including the sibling sweep) before writing.

- Added a first-run demo experience: the demo workspace ships inside the package, and a `Try the demo workspace` button copies it to the user data dir, then discovers and analyzes it automatically.
- Added compare output views for summary and detailed differences, with review filters and JSON/Markdown/CSV exports.
- Support baseline vs candidate model selection and run model-to-model diffs for tables, measures, columns, display folders, hidden flags, and key DAX/property changes.
- Added a new `Semantic Model Compare (1:1)` screen in the web app as a separate feature flow.
- Added an in-app help/legend experience for result interpretation, covering summary cards, filters, status badges, issue states, and cleanup recommendations; include clear definitions for `Usage` vs `Cleanup`, `Used`, `Indirect`, `Stale only`, `Unused`, `Broken`, `Stale`, `Safe`, `Review`, `Blocked`, and `Keep`.
- Let the main search match issue labels and review trigger text, such as `Broken`, `Stale`, `Unsupported Metadata`, and concrete `Review` reasons.
- Added an `Issues` filter/slicer so users can isolate `Broken`, `Stale`, `Broken + Stale`, and no-issue items without mixing those signals into Usage or Cleanup.
- Added a dry-run Cleanup Action plan preview for queued model actions before `/api/action` writes any TMDL files, including affected Semantic Model Items, source files, backup choice, and auto-refresh behavior.
- Added a richer product QA workspace that exercises Report Health, stale Report References, broken references, unsupported metadata Review downgrades, RLS/model-backed dependencies, and Report Extension Measures.
- Added a setting to turn automatic analysis refresh on or off after cleanup actions, including a post-refresh disclaimer when deleting measures may change dependency safety and usage classifications.
- Expanded Item Details with Decision, Evidence, and Actions layouts, DAX expression editing, and Power Query / M source display when available.
- Added cleanup actions to Item Details for move folder, move measure table, rename measure, hide/unhide, delete, apply queued actions, report measure promotion, and stale PBIR cleanup.
- Surfaced table-level usage/status signals and table detail actions.
- Updated tab labels to show visible count out of total count.
- Replaced always-visible filter lists with dropdown-based multi-select filters and per-filter `Select all` actions.
- Added `Used by` links in item details to navigate to related measures/columns.
- Added table-centric summaries and table details with role and dependency signals.
- Added explicit `Review` trigger explanations in results grid and item details.
