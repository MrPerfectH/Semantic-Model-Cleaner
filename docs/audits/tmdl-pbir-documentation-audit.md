# TMDL and PBIR Documentation Audit

Date: 2026-06-02

Worktree: `/Users/przemek.harazny/Projects/Semantic-Model-Cleaner-tmdl-pbir-doc-audit`

Branch: `codex/tmdl-pbir-doc-audit`

## Scope

This audit validates Semantic Model Cleaner against Microsoft documentation and public schemas for the parts that matter to the product:

- TMDL semantic-model discovery, parsing, usage analysis, and write operations.
- PBIR report discovery, report reference scanning, stale metadata detection, and report JSON rewrite/cleanup actions.
- Safety logic behind "used", "not used", "safe", "review", and destructive local edits.
- Pending local changes in `/Users/przemek.harazny/Projects/Semantic-Model-Cleaner`, treated as likely-to-ship but labeled separately from the clean baseline.

This is a documentation-first audit. No application code was changed in this worktree.

## Evidence Sources

Microsoft documentation:

- [Power BI Desktop projects overview](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [Power BI Desktop project semantic model folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
- [Power BI Desktop project report folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [Fabric report definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/report-definition)
- [TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview?view=asallproducts-allversions)
- [TMDL object definitions](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-reference-tabular-object?view=sql-analysis-services-2025)

Public Microsoft schemas fetched during the audit:

- `https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainerMobileState/1.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/bookmark/1.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/bookmarksMetadata/1.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/semanticQuery/1.0.0/schema.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/filterConfiguration/1.2.0/schema-embedded.json`
- `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualConfiguration/2.0.0/schema-embedded.json`

Validation commands:

- Baseline: `PYTHONPATH=src /Users/przemek.harazny/Projects/Semantic-Model-Cleaner/.venv/bin/python -m pytest`
  - Result: `69 passed`
- Pending local tree: `PYTHONPATH=src /Users/przemek.harazny/Projects/Semantic-Model-Cleaner/.venv/bin/python -m pytest`
  - Result: `86 passed`
- Baseline and pending local: `/Users/przemek.harazny/Projects/Semantic-Model-Cleaner/.venv/bin/python -m ruff check .`
  - Result: `All checks passed!`

## Implemented Surface

Baseline features in the clean worktree:

- Discovers `.SemanticModel` and `.Report` folders.
- Parses TMDL tables, measures, columns, calculated columns, hierarchy levels, relationships, role references, field parameter `NAMEOF(...)` targets, sort-by columns, key columns, and inferred columns.
- Scans PBIR `visual.json`, `page.json`, bookmark files, and fallback `definition/**/*.json`.
- Detects live report usage, stale visual metadata selectors, stale bookmark field-parameter projections, relationship usage, RLS usage, DAX dependencies, broken DAX references, and report extension measures.
- Applies TMDL actions: display folder, hidden/unhidden, table group annotation, DAX edit, create measure, move measure to table, rename measure, rename table, delete item.
- Applies PBIR actions: rewrite report references after model moves/renames and clean stale metadata selectors.

Pending local likely-to-ship improvements:

- Adds `ReportIssue` output and report-health action APIs.
- Adds invalid PBIR JSON report issues instead of silent skips.
- Adds page/report filter pane coverage for `filterConfig`.
- Adds `SourceRef.Source` alias resolution for PBIR scanning.
- Adds stale formatting rule and inactive filter detection.
- Adds visual/page hidden state and visual position metadata.
- Improves table rename rewriting for bare DAX table references like `COUNTROWS('Sales Orders')`.
- Adds report issue action application for exact remove/replace flows.

## Findings

### F-01. RLS `tablePermission` filters are not detected

Severity: High

Status: Open in baseline and pending local.

Microsoft evidence:

- TMDL docs show role filters as `tablePermission Store = 'Store'[Store Code] IN ...`.
- TMDL default-property docs list `TablePermission` with `FilterExpression` as its DAX expression property.

Code evidence:

- Baseline `parse_rls_roles` only looks for the literal text `filterExpression`: `src/semantic_model_cleaner/analyzer.py:906`.
- Pending local retains the same behavior.

Validation probe:

```text
role Role_Store1
    modelPermission: read
    tablePermission Store = 'Store'[Store Code] IN {1,10}
```

Result in both trees: `parse_rls_roles(...) == []`.

Why this matters:

Columns used only in RLS can be marked `NOT USED` and may receive a `Safe` cleanup recommendation. Deleting them can break row-level security or change security semantics.

Recommendation:

Parse `tablePermission <table> = <DAX>` declarations and multi-line table-permission expressions. Feed referenced columns into the same RLS usage path that already exists.

### F-02. Partial TMDL declarations are analyzed but cannot be edited safely

Severity: High

Status: Open in baseline and pending local.

Microsoft evidence:

- TMDL explicitly supports partial declaration, including splitting measures from multiple tables into a separate measures file.

Code evidence:

- Analyzer parses every `definition/tables/*.tmdl`, so it can see partial declarations: `src/semantic_model_cleaner/analyzer.py:272`.
- Writers find a table file by file stem only: `src/semantic_model_cleaner/tmdl_writer.py:20`.
- Writers then search only that one file for the item block.

Validation probe:

```text
tables/Sales.tmdl:
table Sales
    column Amount

tables/_Measures.tmdl:
table Sales
    measure Revenue = SUM(Sales[Amount])
```

Result in both trees:

- Analyzer finds `Sales[Revenue]`.
- `set_display_folder(model, "Sales", "Revenue", "Measure", "Core")` returns `Item 'Revenue' not found in Sales.tmdl`.

Why this matters:

The UI can list an item and offer actions that cannot locate the true source block. More dangerous future cases are delete/move/rename actions that assume table name equals file name.

Recommendation:

Track `source_file` and source block location on every parsed model item. All writers should locate the actual item block by source file, not by table file stem. Keep table-level operations separate from item-level operations.

### F-03. Write paths do not validate TMDL or PBIR schema after mutation

Severity: High

Status: Open in baseline and pending local.

Microsoft evidence:

- PBIR is a publicly documented format with public JSON schemas for its files.
- Microsoft warns that unsupported or invalid external edits can prevent Power BI Desktop from opening the project.
- TMDL has a serializer/deserializer API and strict indentation, expression, quoting, and reference rules.

Code evidence:

- TMDL writes directly with string joins, for example `set_dax_expression`: `src/semantic_model_cleaner/tmdl_writer.py:468`.
- PBIR rewrites write JSON directly after mutation: `src/semantic_model_cleaner/report_writer.py:393`.
- `jsonschema` is not in the current dependency set.
- There is no TMDL deserialization or schema validation gate before returning success.

Why this matters:

This is a cleanup/refactor tool that mutates project files. A syntactically valid JSON write can still be invalid PBIR according to schema. A line-based TMDL write can break Desktop load, especially around multiline expressions, partial declarations, object ordering, and quoted values.

Recommendation:

Add a validation layer:

- PBIR: validate changed files against the `$schema` they declare. Cache schema downloads or vendor pinned schema references for repeatability.
- TMDL: if a supported .NET/TOM validation path is available, run deserialization after writes. If not, implement a narrower guard initially for changed TMDL blocks and document the limitation.
- Fail writes atomically when validation fails.

### F-04. Baseline misses documented page `filterConfig` references

Severity: High

Status: Fixed by pending local for page/report filter scanning.

Microsoft evidence:

- PBIR page schema includes `filterConfig`.
- Fabric report-definition examples show page and visual metadata with schema-backed filters.

Code evidence:

- Baseline `scan_visual_interactions` only checks `page.json` `filters`, not `filterConfig`: `src/semantic_model_cleaner/analyzer.py:1291`.
- Baseline excludes `page.json` from the fallback scanner: `src/semantic_model_cleaner/analyzer.py:2245`.
- Pending local adds `_filter_pane_refs`, `scan_report_filters`, and `filterConfig` page handling.

Validation probe:

Page `filterConfig.filters[0].field.Column` referencing `Sales[Region]`.

- Baseline: `Sales[Region]` is `NOT USED`.
- Pending local: `Sales[Region]` is `USED`.

Why this matters:

Page-level filters are common report behavior. Missing them makes the cleanup recommendation unsafe.

Recommendation:

Merge the pending filter coverage and keep tests for page, visual, and report filter panes. Add schema-shaped fixtures rather than minimal ad hoc JSON.

### F-05. PBIR semantic-query alias handling is incomplete across all writers

Severity: High

Status: Partially fixed by pending local for scanning; still open for model move/rename report rewrites.

Microsoft evidence:

- The semantic query schema defines `From` entries with `Name` and `Entity`.
- It also defines `QuerySourceRefExpression` with `Source`, separate from `StandaloneSourceRefExpression` with `Entity`.

Code evidence:

- Baseline `_find_json_refs` only recognizes `SourceRef.Entity`: `src/semantic_model_cleaner/analyzer.py:984`.
- Pending local scanner adds `_aliases_from_from_clause` and `_source_ref_entity`: `/Users/przemek.harazny/Projects/Semantic-Model-Cleaner/src/semantic_model_cleaner/analyzer.py:1067`.
- The main PBIR rewrite path still only handles `SourceRef.Entity` in `Measure`, `Column`, and `HierarchyLevel` branches: `src/semantic_model_cleaner/report_writer.py:249`.
- Pending local `apply_report_issue_actions` handles aliases for exact issue actions, but `/api/measure/move` and `/api/model/rename` still use `rewrite_model_reference_changes`.

Why this matters:

Report fields represented through `From` aliases can be detected after pending changes, but model move/rename actions may not update all corresponding alias-backed references. This can leave PBIR JSON with mixed old and new references.

Recommendation:

Make `_rewrite_model_refs_in_json` alias-aware using the same `From`/`Source` model as pending scanner code. Add tests for:

- table rename through alias-backed `Column`
- measure rename through alias-backed `Measure`
- measure move between tables when `queryRef` does not use the same entity string as the source semantic-model table

### F-06. Broad PBIR rewrite logic can touch non-semantic `Entity` strings

Severity: Medium

Status: Open in baseline and pending local.

Code evidence:

- `_rewrite_model_refs_in_json` recursively rewrites any object key named `Entity` or `entity` when it matches a renamed table: `src/semantic_model_cleaner/report_writer.py:323`.
- It scans every JSON file under `definition/`: `src/semantic_model_cleaner/report_writer.py:425`.

Why this matters:

PBIR contains custom visual metadata, resource metadata, annotations, settings, and schema-owned structures. A string field named `Entity` is not necessarily a semantic model entity. Broad recursive replacement is convenient but risky in a file format with public schemas.

Recommendation:

Restrict rewrites to schema-known semantic query/reference shapes:

- `Measure/Column/HierarchyLevel.Expression.SourceRef`
- semantic-query `From[].Entity` only when linked to a matching `SourceRef.Source`
- `queryRef`, `queryRefs`, and metadata selector strings when they parse as a semantic model reference
- `reportExtensions.entities[].name` and measure references

### F-07. TMDL quoted names and escaped single quotes are not normalized consistently

Severity: Medium

Status: Open in baseline and pending local.

Microsoft evidence:

- TMDL names containing single quotes must be single-quoted and escape embedded quotes by doubling them.

Code evidence:

- Analyzer strips quote characters with `.strip("'\"")` instead of unescaping TMDL names: `src/semantic_model_cleaner/analyzer.py:581` and `src/semantic_model_cleaner/analyzer.py:592`.
- `tmdl_writer` has `_unquote_tmdl_name`, but analyzer parsing does not consistently use it.
- DAX reference extraction uses regexes that do not handle escaped quotes in quoted table names: `src/semantic_model_cleaner/analyzer.py:1619`.

Validation probe:

```text
table 'O''Brien'
    measure 'Bob''s Revenue' = 1
```

Result: analyzer returns `("O''Brien", "Bob''s Revenue")` instead of `("O'Brien", "Bob's Revenue")`.

Why this matters:

Names with apostrophes can fail usage matching, DAX dependency resolution, rename rewrites, and PBIR matching.

Recommendation:

Use one TMDL name parser/unparser everywhere. Add tests for table, column, measure, hierarchy, relationship, sort-by, DAX, and PBIR references containing apostrophes.

### F-08. Some documented TMDL metadata can hide dependencies not reflected in cleanup risk

Severity: High for calculation groups and perspectives; Medium for cultures/translations and secondary expressions.

Status: Open in baseline and pending local.

Microsoft evidence:

- TMDL maps to the full Tabular Object Model.
- TMDL object references include perspectives.
- TMDL expressions include calculation items, format string definitions, detail rows definitions, data coverage definitions, KPI expressions, and table permissions.
- TMDL translations can include caption, description, and display folder values for model objects.

Current coverage:

- Relationships, sort-by columns, keys, hierarchies, RLS via unsupported `filterExpression`, report extension measures, field parameters, and some measure `formatStringDefinition` expressions.

Missing or incomplete:

- Calculation groups and calculation items.
- Perspectives and perspective object references.
- Cultures/translations cleanup or stale translation detection.
- KPI status/target/trend expressions.
- Detail rows definitions and multiline `formatStringDefinition` expressions.
- Data coverage definitions.
- M expressions outside the narrow field-parameter `NAMEOF` path.

Why this matters:

The user asked that caution states explain why. If these metadata areas are not scanned, the app should not present a simple `Safe` deletion claim for affected projects. For example, a measure referenced only by a calculation item can be reported safe even though deleting it breaks calculation group behavior.

Recommendation:

Add model-level capability detection. If any unsupported metadata type is present, downgrade relevant cleanup confidence and show why. Then implement direct parsers in priority order:

1. calculation groups/items
2. perspectives
3. table permissions
4. KPI/detail rows/format string expressions
5. cultures/translations stale metadata cleanup

### F-09. Report extension measure schema is only partially honored

Severity: Medium

Status: Open in baseline and pending local.

Microsoft schema evidence:

- `ReportExtensionMeasure` requires `name`, `dataType`, and `expression`.
- `ReportExtensionEntity.name` must match a semantic model entity.
- `references` can include `unrecognizedReferences` and measure references with optional `schema`.

Code evidence:

- Parser does not require or surface `dataType`: `src/semantic_model_cleaner/analyzer.py:723`.
- Parser does not warn on `references.unrecognizedReferences`.
- Migration preserves expression, display folder, format string, and hidden, but drops description, data category, annotations, measure template, and data type: `src/semantic_model_cleaner/report_writer.py:94`.
- Migration only supports same-name/same-entity promotion: `src/semantic_model_cleaner/report_writer.py:83`.

Why this matters:

Report-level measures are product-relevant. Missing schema fields can hide quality issues, and promotion can lose metadata users expect to keep.

Recommendation:

Validate report extension schema, surface missing/invalid fields as report issues, warn on `unrecognizedReferences`, and preserve all schema-backed measure metadata where TMDL supports equivalent properties.

### F-10. Connected report discovery should parse `definition.pbir`

Severity: Medium

Status: Open in baseline and pending local.

Microsoft evidence:

- `definition.pbir` is required and holds `datasetReference`.
- `datasetReference` supports `byPath` and `byConnection`.

Code evidence:

- `/api/reports/find-connected` scans every `definition*.pbir` and checks whether the selected model name appears as a substring: `src/semantic_model_cleaner/webapp.py:766`.

Why this matters:

Substring matching can create false positives and false negatives. It also cannot explain unsupported live-connection or remote semantic model cases clearly.

Recommendation:

Parse each candidate as JSON and inspect `datasetReference.byPath.path`. Normalize it relative to the `definition.pbir` file and compare to the selected `.SemanticModel` folder. For `byConnection`, surface a clear "remote model, cannot verify local path" status.

### F-11. Cross-artifact writes are not transactional

Severity: High

Status: Open in baseline and pending local.

Code evidence:

- `/api/measure/move` validates model and report dry-runs, then writes model changes and report changes separately: `src/semantic_model_cleaner/webapp.py:1056`.
- `/api/model/rename` follows the same pattern: `src/semantic_model_cleaner/webapp.py:1139`.
- `report_writer.rewrite_model_reference_changes` writes each report JSON file as it goes: `src/semantic_model_cleaner/report_writer.py:393`.
- `migrate_measure_to_model` creates a model measure before saving `reportExtensions.json`: `src/semantic_model_cleaner/report_writer.py:59`.

Why this matters:

If a report write fails after model files were changed, the workspace can be left in a mixed state. Backups are optional and do not provide automatic rollback.

Recommendation:

Introduce a transaction plan:

- Snapshot all affected model and report files before write.
- Apply all changes in memory.
- Validate all changed artifacts.
- Write files.
- Roll back snapshots on any exception.

### F-12. TMSL semantic models should fail clearly

Severity: Medium

Status: Open in baseline and pending local.

Microsoft evidence:

- Semantic model projects can store model metadata as TMSL `model.bim` or TMDL `definition/`, depending on `definition.pbism` version and selected format.

Code evidence:

- App intentionally targets TMDL, but `parse_model_items` simply returns an empty list when `definition/tables` is absent: `src/semantic_model_cleaner/analyzer.py:272`.

Why this matters:

A user selecting a TMSL model can get confusing empty analysis instead of a clear "TMDL required" message.

Recommendation:

Check `definition.pbism` and the presence of `model.bim` versus `definition/`. Emit an actionable error: "This semantic model is saved as TMSL/model.bim. Convert to TMDL first."

## Pending Local Changes Worth Keeping

The pending local tree contains several improvements that should be considered part of the likely next baseline:

- Page/report `filterConfig` support fixes a high-risk false-negative.
- Invalid PBIR JSON issues replace silent skips.
- Alias-aware scanning aligns with `semanticQuery` schema.
- Report-health issues give users a safer way to understand stale or broken PBIR references.
- Visual hidden/page hidden/position context improves evidence quality.
- Bare DAX table rename rewriting fixes a concrete TMDL table rename bug:
  - Baseline leaves `COUNTROWS('Sales Orders')` unchanged.
  - Pending local rewrites it to `COUNTROWS('Fact Sales Orders')`.

Before shipping pending local, close these remaining holes:

- Make the main report rewrite path alias-aware, not only report issue action replacement.
- Add schema validation after report issue actions.
- Ensure broad remove actions cannot delete unrelated schema nodes.
- Add transaction/rollback across model and report artifacts.

## Product-Scope Backlog

P0 before trusting cleanup recommendations:

1. Parse TMDL `tablePermission` RLS filters.
2. Track exact TMDL source file/block for every item and update writers to use it.
3. Add PBIR schema validation for every changed JSON file.
4. Add TMDL post-write validation or at least a structured parser guard.
5. Make model/report writes transactional across all affected files.

P1 for real-world Power BI coverage:

1. Merge pending page/report filter and invalid JSON issue coverage.
2. Make PBIR rewrite alias-aware for `SourceRef.Source` and `From[]`.
3. Add calculation group/item dependency detection.
4. Add perspective references and cleanup-risk downgrades.
5. Fix TMDL quoted name and escaped quote parsing.
6. Improve report extension measure schema handling and promotion metadata preservation.

P2 useful future product features:

1. Schema-backed "Report Health" view for all PBIR files, including `mobile.json`, bookmarks metadata, custom visuals, resources, and report settings.
2. "Unsupported metadata detected" banners with exact why and affected files.
3. Safe cleanup plan preview that shows every file and every JSON/TMDL path to change before writing.
4. Local model/report compatibility check for `definition.pbir` `byPath` and `byConnection`.
5. Stale cultures/translations cleanup after model object deletion or rename.
6. Perspective-aware cleanup suggestions.
7. Optional model.bim/TMSL detection with conversion guidance.

## Conservative Safety Rule

When the app has not scanned a documented metadata area that can reference model objects, it should not say only `Safe`.

Recommended user-facing pattern:

```text
Review: No selected PBIR report references were found, but this model contains calculation groups/perspectives/RLS metadata that this version does not fully scan. Deleting this item may break semantic model behavior outside selected report visuals.
```

Every downgrade should name:

- the unsupported metadata area
- the file or folder where it was detected
- the possible hidden dependency
- the practical user harm

## Validation Notes

Targeted probes were run with `PYTHONPATH=src` to force imports from each checkout.

Confirmed behavior:

- Baseline and pending local both miss documented RLS `tablePermission` filters.
- Baseline and pending local both parse partial TMDL measures but cannot edit them when the measure is not in the table-named file.
- Baseline misses page `filterConfig`; pending local detects it.
- Baseline silently skips invalid visual JSON; pending local emits a report issue.
- Baseline misses bare table references in table rename DAX rewrite; pending local fixes them.
