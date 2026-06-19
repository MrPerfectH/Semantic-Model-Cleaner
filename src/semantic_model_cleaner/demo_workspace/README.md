# Demo Workspace

This directory contains a synthetic PBIR + TMDL workspace that is safe to share publicly.
It ships inside the package so the web app can offer a one-click "Try the demo workspace"
experience: the app copies it to `~/.semantic-model-cleaner/demo-workspace` and analyzes
the copy, so the bundled files are never modified. Loading the demo again resets the copy.

Use it to:

- see analysis and cleanup actions without preparing your own Power BI Project files
- validate local setup
- generate screenshots or demo recordings

## What it showcases

- A clean field-parameter setup: `Sales[Revenue]` / `Sales[Margin %]` used via the
  `Metric Parameter` field parameter (so the analyzer counts them as used).
- A deliberate **rename-fallout** on the "Sales Detail" page, so Report Health shows
  root-cause grouping and both repair flows. Repairs rewrite the report files only —
  never the model.
  - **Table-reference repair** — the page references a missing table `Sales Orders`
    (renamed to `Orders`). Repointing it to `Orders` is step one: `order_date` resolves
    immediately, and because the columns were *also* renamed, `OrderID` / `Amount`
    then surface as column issues under `Orders` — clear them with a column repair
    (`OrderID` → `order_id`, `Amount` → `order_amount`).
  - **Column-reference repair** — the page also references renamed columns
    `OrderTotal` / `OrderQty` on the existing `Orders` table; map them to
    `order_amount` / `order_qty`.
  Walking both flows in sequence takes the report to zero issues. (Column names were
  deliberately renamed, so the mappings above won't pre-fill — the app shows a fuzzy
  "suggested" hint but, as its copy warns, verify before selecting.)

Suggested commands when working from the repository:

```bash
semantic-model-cleaner src/semantic_model_cleaner/demo_workspace --format full
semantic-model-cleaner-web src/semantic_model_cleaner/demo_workspace
```
