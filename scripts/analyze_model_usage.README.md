# analyze_model_usage.py

Deterministic analyzer for Power BI PBIR + TMDL projects.
The supported workflow is exactly one semantic model and one or more reports.

It cross-references:

- semantic model items from `*.SemanticModel`
- report references from `*.Report`

and classifies each measure/column as used or not used.

## Quick usage

From a standard workspace root:

```bash
python3 scripts/analyze_model_usage.py . --format full
python3 scripts/analyze_model_usage.py . --format unused
python3 scripts/analyze_model_usage.py . --format json
python3 scripts/analyze_model_usage.py . --format xlsx
python3 scripts/analyze_model_usage.py . --format xlsx -o report.xlsx
```

From non-standard folder layout:

```bash
python3 scripts/analyze_model_usage.py \
  --models-path /path/to/models_root_or_model_dirs \
  --reports-path /path/to/reports_root_or_report_dirs \
  --format full
```

Interactive selection:

```bash
python3 scripts/analyze_model_usage.py . --interactive --format full
```

Filter by model and report name:

```bash
python3 scripts/analyze_model_usage.py . --model Sales Finance --report Executive Regional --format unused
```

## clean-stale subcommand

Bulk-removes dead PBIR metadata: stale visual selectors, stale bookmark projections and stale formatting rules — the `warning` issues the analyzer emits with a `clean_stale` suggestion because the reference is not part of the live visual query. Broken `missing_table` / `missing_column` / `missing_measure` references (severity `error`) are never removed.

```bash
python3 scripts/analyze_model_usage.py clean-stale .                              # dry run
python3 scripts/analyze_model_usage.py clean-stale . --kind selector bookmark     # limit kinds
python3 scripts/analyze_model_usage.py clean-stale . --format json                # machine-readable
python3 scripts/analyze_model_usage.py clean-stale . --apply                      # write + backup per report
python3 scripts/analyze_model_usage.py clean-stale . --apply --no-backup          # write, no backup
```

Accepts the same selection flags as the analyzer (`--models-path`, `--reports-path`, `--model`, `--report`).

Dry run is the default and writes nothing; it prints per-report and per-kind counts plus the full candidate list (report, PBIR file, selector value). Exit codes: `0` nothing to clean or applied OK, `2` dry run found candidates, `1` engine/validation error (the engine is transactional, so nothing was written).

Passing no subcommand keeps the historical behaviour: `analyze_model_usage.py . --format unused` still runs the analyzer.

## What it scans

1. Model items

- Measures
- Columns
- Calculated columns
- Relationship columns
- RLS filter references
- Hierarchies and their backing columns

2. Report references

- Visual field/query definitions
- Visual interactions
- Page-level filters
- Drillthrough target fields
- Hierarchy level references
- Bookmarks
- Additional report definition JSON

3. DAX dependency analysis

- Measure to measure dependencies
- Measure to column dependencies
- Transitive closure for helper measures/columns

4. Field parameter handling

- Detects field-parameter table definitions that use `NAMEOF(...)` inside table-level calculated-table source/expression blocks
- Promotes resolved `NAMEOF(...)` targets when the field-parameter table is used in a report
- Emits warnings instead of silently promoting unresolved or ambiguous targets

## Status meanings

- `USED`
- `USED (Field Parameter: ...)`
- `USED (Relationship)`
- `USED (RLS: ...)`
- `USED (Key Column)`
- `USED (Hierarchy: ...)`
- `USED (Sort Column for: ...)`
- `INDIRECT (via: ...)`
- `NOT USED`

## Important notes / limits

- Matching is case-insensitive
- Field parameters backed by `NAMEOF(...)` are supported
- Calculation groups are not modeled yet
- Broader metadata indirection is not fully covered yet
- Invalid or malformed JSON files are skipped
- Unsupported or unresolved `NAMEOF(...)` patterns are surfaced as warnings

## Output formats

- `full`: Markdown summary plus detailed usage matrix
- `unused`: Markdown report of only `NOT USED` items
- `json`: machine-readable output including top-level `warnings`
- `xlsx`: workbook with `Summary`, `Details`, and `All References`

All formats support `-o` to write to a file instead of stdout.

Examples:

```bash
python3 scripts/analyze_model_usage.py . --format json -o analysis.json
python3 scripts/analyze_model_usage.py . --format xlsx -o analysis.xlsx
```

## Web app export

The local web app can download the latest completed analysis as:

- `json`
- `xlsx`

Those downloads reuse the same analyzer output shape and include top-level warnings.

## Related files

- `scripts/app.py`
- `scripts/tmdl_writer.py`
- `scripts/templates/index.html`
