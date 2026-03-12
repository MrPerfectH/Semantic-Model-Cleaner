# Backlog

## Highest priority

- Add a setting to turn automatic analysis refresh on or off after cleanup actions, and show a disclaimer after refresh that dependency safety/usage results may change once measures are deleted.
- Replace the always-visible filter value lists with dropdown-based multi-select filters, and add a `Select all` action for each filter.
- Expand the item details page to show the full DAX expression for measures and calculated columns; for regular columns, show the relevant Power Query / M source details when available.

## Near-term

- Add a dry-run diff preview before applying cleanup actions in the web app.
- Export cleanup plans as JSON or Markdown for review before edits are applied.
- Add an ignore/protect list for items that should never be flagged or modified.
- Expand analyzer fixtures for metadata and report-definition edge cases.

## Medium-term

- Add calculation-group support to the analyzer.
- Cover broader metadata indirection and additional dynamic report references.
- Add more TMDL editing safety checks and regression tests.

## Later

- Prepare the repo for public release with an OSS license, public-facing demo assets, and issue/community scaffolding.
