# Product Pass Discovery

Date: 2026-06-09

## Purpose

This discovery pass reviews the current Semantic Model Cleaner product surface after the
documentation-backed TMDL/PBIR safety work. The goal is to identify the next useful product
theme, avoid redoing already-shipped backlog work, and split the next implementation pass into
small, shippable slices.

## Evidence Reviewed

- Product glossary: `CONTEXT.md`
- Product backlog: `BACKLOG.md`
- App README and current release-channel notes: `README.md`
- Web app API and serialization: `src/semantic_model_cleaner/webapp.py`
- Single-page web UI: `src/semantic_model_cleaner/templates/index.html`
- Experiment gating: `src/semantic_model_cleaner/experiments.py`
- Existing design prototypes:
  - `prototypes/item-details-layouts/`
  - `prototypes/details-proposals/`
  - `prototypes/details-proposals-v2/`
- Public demo workspace:
  - `examples/public-demo-workspace/`

The local web app was run against `examples/public-demo-workspace` on port `8765`.
`/api/discover` found one Semantic Model and one Report. `/api/analyze` returned four Semantic
Model Items, one Safe cleanup candidate, three Report References, and no Report Health issues.

## Current Product Map

### Selection And Analysis

The setup flow supports choosing exactly one Semantic Model and one or more Reports, finding
connected Reports, running analysis, and exporting JSON/Excel from the latest analysis. The setup
area also exposes trust-critical settings:

- auto-refresh analysis after apply
- confirm delete
- create backup before apply
- show action log

This is enough for a local practitioner workflow, but the default demo does not exercise connected
Report discovery, remote/live-connected Reports, invalid PBIR, stale metadata, or unsupported
metadata.

### Results Views

The UI currently has these main views:

- Details
- Tables
- Reports
- All References
- Item Details
- Table Details

The tab labels already show visible/total counts, so that old backlog item is complete.

### Details And Item Details

The item details surface is more advanced than the old backlog suggests. It already has three
layouts:

- Decision
- Evidence
- Actions

It also includes cleanup actions, DAX expression editing for measures/calculated columns, Power
Query / M source display for regular columns when available, report-level measure promotion, stale
PBIR cleanup, and report-reference trees.

This means the next pass should refine the details workflow rather than simply "add item detail
actions" from the stale backlog.

### Cleanup Actions

Cleanup Actions currently split into two product shapes:

- queued model-only actions through `/api/action`
- direct preview/apply flows for measure move, measure/table rename, report-measure migration, and
  stale PBIR cleanup

Measure move and rename already have dry-run previews before writes. Generic queued actions
through `/api/action` do not expose a first-class dry-run plan showing every affected file/item
before apply. This is the largest remaining trust gap in the cleanup workflow.

### Report Health

Report Health exists as both a banner and the Reports view. It supports issue grouping, row
selection, stale cleanup preview/apply, and action application for report-side issues.

The current public demo workspace does not produce Report Health rows, so a product pass cannot
evaluate this surface well without richer fixtures.

### Experiments And Compare Models

`compare-models` exists as an experiment key and can show a beta banner/pill, but there is no
implemented Semantic Model Compare screen or API. README and BACKLOG mention the experiment, so the
product currently advertises a feature flag before the feature has a real surface.

## Key Findings

### 1. The Next Theme Should Be Cleanup Confidence, Not More Parser Coverage

The last workstream closed the biggest documentation-backed parser and writer safety gaps. The next
valuable product theme is helping users understand and act on cleanup decisions in the web flow:

- what will change
- why it is safe/review/blocked
- which files are affected
- what has to be manually checked
- what changed after refresh

### 2. The Demo Workspace Is Too Thin For Product QA

The public demo is useful for happy-path smoke tests and screenshots, but it does not exercise the
surfaces that most need product judgment:

- Report Health
- stale Report References
- invalid PBIR JSON
- unsupported metadata Review downgrades
- report extension measures
- RLS/model-backed dependencies
- generic Cleanup Action preview/apply
- move/rename report rewrite previews

Without a richer demo or fixture workspace, product QA will keep relying on synthetic tests and
private workspaces.

### 3. The Backlog Was Partly Stale

Several "highest priority" items are already implemented in the live UI:

- item details includes DAX and Power Query / M source panels
- item details includes cleanup actions
- table view exposes usage/status signals
- tab labels show visible/total counts

The backlog should now focus on the remaining trust and workflow gaps.

### 4. Main Item Filtering Still Needs Issue Semantics

The Reports view has issue grouping. The main Details/All References surfaces still need an issue
filter/slicer for `Broken`, `Stale`, and `Broken + Stale`, and search should match issue labels.

This matters because Usage and Cleanup are intentionally separate product concepts. Issues should
not be hidden behind Usage or Cleanup filters.

### 5. Help Exists, But Not As A Coherent Legend

The UI has tooltips, inline help, and table-action help panels. It still lacks one consolidated
legend that explains the core product language: Usage, Cleanup Recommendation, Report Reference,
Live Report Reference, Stale Report Reference, Safe, Review, Blocked, Keep, Broken, and Stale.

This should be treated as trust infrastructure, not decorative documentation.

### 6. Generic Cleanup Preview Is The Most Important Implementation Slice

The app already has transactional behavior and backups. The missing user-facing layer is a dry-run
plan for queued Cleanup Actions before writing, especially for batch actions from Details and
Tables.

The product should show:

- each queued Cleanup Action
- each target Semantic Model Item or table dependency set
- each TMDL file that will change
- whether a backup will be created
- whether analysis will auto-refresh afterward
- any blocked or unsupported action before apply

### 7. The Single-Page Template Is Becoming The Main Product Architecture Risk

`src/semantic_model_cleaner/templates/index.html` contains CSS, markup, state management,
filtering, rendering, action planning, API calls, and product copy in one large file. This has
worked so far, but the next UI-heavy pass will be slower and riskier unless we introduce clearer
front-end modules or at least separate action-plan and render helpers.

This is not a reason to pause product work. It is a warning to keep the next slices narrow and to
extract only where locality improves.

## Recommended Implementation Slices

### Slice 1: Rich Product QA Workspace

Create a second demo/fixture workspace for internal product QA while keeping the public demo small.
It should include:

- one Safe cleanup candidate
- one Review candidate due to Unsupported Metadata
- one Blocked item due to RLS/model metadata
- stale report metadata
- broken report reference
- report extension measure
- at least one move/rename rewrite scenario

This gives every later UI pass a stable workflow to inspect.

### Slice 2: Generic Cleanup Plan Preview

Add a dry-run plan for queued `/api/action` Cleanup Actions and show it before apply.

Start with external behavior:

- selected actions produce a preview response without writing files
- preview includes affected model items and source files
- UI shows the preview before apply
- apply still uses existing transactional writer behavior

### Slice 3: Issue Filter And Issue-Aware Search

Add a main-grid issue filter for:

- Broken
- Stale
- Broken + Stale
- No issue

Also make search match issue labels and review trigger text.

### Slice 4: Product Language Legend

Add a compact in-app legend/help surface that defines the core product language from `CONTEXT.md`.
It should be accessible from the main results area and not require leaving the app.

### Slice 5: Compare Models Decision

Either implement the first real `compare-models` beta surface or remove/defer the visible experiment
copy until there is an actual flow. The current state is only a flag/pill.

### Slice 6: Front-End Locality Cleanup

After the user-facing slices above, extract a small front-end module seam around cleanup planning
and rendering. Do not do a broad rewrite first. The useful first extraction is likely:

- action planning state
- preview/apply rendering
- product-language helpers

## Top Recommendation

Start with Slice 1, then Slice 2.

The rich product QA workspace gives us the data needed to evaluate the real product flow. Generic
Cleanup Plan Preview is then the highest-trust improvement because it makes destructive changes
visible before writing, using the safety infrastructure that already exists behind the API.
