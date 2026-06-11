# Backlog

Last updated: 2026-06-11

## Highest priority

- Cut release v0.2.0 (prerelease) so testers get the compare screen, interpretation guide, and dry-run preview work shipped since v0.1.1.
- Time-boxed UX paper-cut pass on the first-session path (analyze loading feedback, actionable path errors, label/legend clarity).

## Near-term

- Export Cleanup Action plans as JSON or Markdown for review before edits are applied.
  Design: reuse `tmdl_writer.plan_actions()` output and the `model_compare` formatter patterns; store the last plan in `_state`; add `GET /api/action/plan/export`; export buttons in the action plan preview panel.
- Add a Protected Items list for items that should never be flagged or modified.
  Design: app-side store in the user dir keyed by resolved model path (`~/.semantic-model-cleaner/protected_items.json`); new `Protected` Cleanup Recommendation distinct from `Keep`; hard block on delete/rename/move/DAX-edit in `_validate_action`/`plan_actions`/`apply_actions` (incl. protected-table cascade); annotate analysis and plan exports; Protect/Unprotect toggle in Item Details.
- Expand analyzer fixtures for metadata and report-definition edge cases.
- Split the single-page web template into smaller front-end modules around cleanup planning, product-language helpers, and render helpers once the next product slices settle.

## Medium-term

- Add calculation-group support to the analyzer.
- Add search support for slicers.
- Cover broader metadata indirection and additional dynamic report references.
- Add more TMDL editing safety checks and regression tests.

## Later

- Make backups less annoying instead of changing the default: single backup folder and/or auto-pruning of old backups. (Decision 2026-06-11: backup before apply stays on by default — it is cheap insurance and a trust signal for a file-editing tool.)
- Prepare the repo for public release with an OSS license, public-facing demo assets, and issue/community scaffolding.

## Completed recently

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
