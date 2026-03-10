# Semantic Model Cleaner

Analyze Power BI PBIR + TMDL projects to find unused semantic model items, explain why items are still needed, and apply safe cleanup actions locally.

## What It Does

This repo has two parts:

- A CLI analyzer that scans exactly one `.SemanticModel` and one or more `.Report` folders, classifies measures and columns, and exports reports in Markdown, JSON, or Excel.
- A local Flask web app that lets you review findings and apply cleanup actions such as move to folder, hide, unhide, and delete.

## Feature Summary

### Analysis

- Auto-discovers `.SemanticModel` and `.Report` folders from a workspace root or explicit paths
- Parses measures, columns, calculated columns, hierarchies, relationships, and RLS filters
- Scans report visuals, filters, bookmarks, drillthrough config, and additional report definition JSON
- Resolves indirect DAX dependencies so helper measures and columns are not misclassified as unused
- Classifies items as `USED`, `INDIRECT`, or `NOT USED`
- Assigns removal risk levels: `Safe`, `Review`, `Caution`, `Do not remove`
- Produces table-level summaries and full reference matrices

### Outputs

- `full`: detailed Markdown report
- `unused`: compact Markdown report of only unused items
- `json`: machine-readable output
- `xlsx`: workbook with `Summary`, `Details`, and `All References` sheets

### Web Cleaner

- Built-in filesystem browser for selecting one model and one or more report folders
- Sortable and filterable results table
- Bulk selection helpers
- TMDL cleanup actions:
  - Move to display folder
  - Hide / unhide
  - Delete measure or column
- Timestamped semantic model backup before destructive edits
- Git dirty-tree warning before writes
- Automatic re-analysis after changes

## Quick Start

```bash
git clone https://github.com/<you>/Semantic-Model-Cleaner.git
cd Semantic-Model-Cleaner
pip install -r requirements.txt
```

## CLI

Run against a workspace root:

```bash
python3 scripts/analyze_model_usage.py ~/Projects/MyProject --format full
```

Write an Excel report:

```bash
python3 scripts/analyze_model_usage.py ~/Projects/MyProject --format xlsx -o usage_analysis.xlsx
```

Use explicit paths:

```bash
python3 scripts/analyze_model_usage.py \
  --models-path /path/to/Model.SemanticModel \
  --reports-path /path/to/Report.Report \
  --format unused
```

## Web App

Start the local UI:

```bash
python3 scripts/app.py
```

Open `http://127.0.0.1:5001`.

Optional flags:

```bash
python3 scripts/app.py . --port 8080
python3 scripts/app.py . --host 0.0.0.0
python3 scripts/app.py . --debug
```

## Safety Notes

- The workflow is intentionally `1 semantic model -> 1 or more reports`.
- The app creates a backup before destructive edits when requested.
- The analyzer is static analysis. Dynamic DAX patterns and metadata indirection can still hide real usage.

## Repo Layout

- `scripts/analyze_model_usage.py`: CLI analyzer and report exporters
- `scripts/app.py`: Flask app and API
- `scripts/tmdl_writer.py`: TMDL edit engine
- `scripts/templates/index.html`: single-page web UI
- `scripts/analyze_model_usage.README.md`: analyzer-specific usage details

## Next Features

Recommended next steps for the project:

1. Add test coverage for TMDL editing and analyzer edge cases using small fixture models and reports.
2. Add a dry-run diff preview in the web app before applying destructive changes.
3. Export cleanup plans as JSON or Markdown so teams can review changes before writing files.
4. Add support for more Power BI metadata cases, especially semantic links not covered by current static parsing.
5. Add packaging and developer tooling: `pyproject.toml`, linting, formatting, and CI checks.

Full analyzer usage is documented in [scripts/analyze_model_usage.README.md](scripts/analyze_model_usage.README.md).
