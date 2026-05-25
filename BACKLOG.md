# Backlog

Last updated: 2026-05-19

## Highest priority

- Add a setting to turn automatic analysis refresh on or off after cleanup actions, and show a disclaimer after refresh that dependency safety/usage results may change once measures are deleted.
- Expand the item details page to show the full DAX expression for measures and calculated columns; for regular columns, show the relevant Power Query / M source details when available.
- Add the same cleanup actions to the item details page that are available on the main results view, so users can move, hide/unhide, or delete the current item without going back.
- In the tables view, make tables with no references obvious at a glance by surfacing the same statuses used on the item details tab.
- Update tab labels to show the visible count out of the total count, instead of always showing the full unfiltered totals.
- Add a new `Semantic Model Compare (1:1)` screen in the web app as a separate feature flow.
- Support baseline vs candidate model selection and run model-to-model diffs for tables, measures, columns, display folders, hidden flags, and key DAX/property changes.
- Add compare output views (summary + detailed differences) and export options for review.

## Near-term

- Add an `Issues` filter/slicer so users can isolate `Broken`, `Stale`, and `Broken + Stale` items without mixing those signals into Usage or Cleanup.
- Let the main search match issue labels such as `Broken` and `Stale`, in addition to item names and table names.
- Add an in-app help/legend experience for result interpretation, covering summary cards, filters, status badges, issue states, and cleanup recommendations; include clear definitions for `Usage` vs `Cleanup`, `Used`, `Indirect`, `Stale only`, `Unused`, `Broken`, `Stale`, `Safe`, `Review`, `Blocked`, and `Keep`.
- Add a dry-run diff preview before applying cleanup actions in the web app.
- Keep optional backup before cleanup actions, but switch default to off.
- Export cleanup plans as JSON or Markdown for review before edits are applied.
- Add an ignore/protect list for items that should never be flagged or modified.
- Expand analyzer fixtures for metadata and report-definition edge cases.

## Medium-term

- Add calculation-group support to the analyzer.
- Add search support for slicers.
- Cover broader metadata indirection and additional dynamic report references.
- Add more TMDL editing safety checks and regression tests.

## Later

- Prepare the repo for public release with an OSS license, public-facing demo assets, and issue/community scaffolding.

## Completed recently

- Replaced always-visible filter lists with dropdown-based multi-select filters and per-filter `Select all` actions.
- Added `Used by` links in item details to navigate to related measures/columns.
- Added table-centric summaries and table details with role and dependency signals.
- Added explicit `Review` trigger explanations in results grid and item details.
