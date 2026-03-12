# Backlog

## Highest priority

- Add a setting to turn automatic analysis refresh on or off after cleanup actions, and show a disclaimer after refresh that dependency safety/usage results may change once measures are deleted.
- Replace the always-visible filter value lists with dropdown-based multi-select filters, and add a `Select all` action for each filter.
- Expand the item details page to show the full DAX expression for measures and calculated columns; for regular columns, show the relevant Power Query / M source details when available.
- Add the same cleanup actions to the item details page that are available on the main results view, so users can move, hide/unhide, or delete the current item without going back.
- In item details, when `Used by` is shown, add links to navigate to those measures or columns.
- Add a table-centric view with per-table summaries of items and how they are used, including relationship role patterns (for example, dimension-like tables with only active 1-to-many relationships) and isolated dependencies (for example, a single measure depending on a single column).
- In the tables view, make tables with no references obvious at a glance by surfacing the same statuses used on the item details tab.
- Update tab labels to show the visible count out of the total count, instead of always showing the full unfiltered totals.
- Make `Review` classifications explain themselves directly in the results grid and item details by showing the exact trigger(s) for review, instead of only a generic risk label.

## Near-term

- Add a dry-run diff preview before applying cleanup actions in the web app.
- Add an optional backup step before applying cleanup actions; default it to off.
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
