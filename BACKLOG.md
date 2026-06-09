# Backlog

Last updated: 2026-06-09

## Highest priority

- Add a new `Semantic Model Compare (1:1)` screen in the web app as a separate feature flow.
- Support baseline vs candidate model selection and run model-to-model diffs for tables, measures, columns, display folders, hidden flags, and key DAX/property changes.
- Add compare output views (summary + detailed differences) and export options for review.

## Near-term

- Keep optional backup before cleanup actions, but switch default to off.
- Export cleanup plans as JSON or Markdown for review before edits are applied.
- Add an ignore/protect list for items that should never be flagged or modified.
- Expand analyzer fixtures for metadata and report-definition edge cases.
- Split the single-page web template into smaller front-end modules around cleanup planning, product-language helpers, and render helpers once the next product slices settle.

## Medium-term

- Add calculation-group support to the analyzer.
- Add search support for slicers.
- Cover broader metadata indirection and additional dynamic report references.
- Add more TMDL editing safety checks and regression tests.

## Later

- Prepare the repo for public release with an OSS license, public-facing demo assets, and issue/community scaffolding.

## Completed recently

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
