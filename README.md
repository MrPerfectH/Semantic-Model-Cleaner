# Semantic Model Cleaner

Internal tool for analyzing Power BI PBIR + TMDL projects, finding unused semantic model items across selected reports, and applying cleanup actions locally.

## Repo Status

- Intended audience: internal team using a private GitHub repo
- Current shape: script-based CLI plus local Flask web app
- Packaging: not installable yet in this iteration

## What It Does

- Scans exactly one `.SemanticModel` and one or more `.Report` folders
- Detects direct report usage plus supported indirect/model-backed usage
- Surfaces warnings for unresolved or ambiguous dynamic references
- Lets you review results in a local web UI and apply cleanup actions safely

## Python Requirement

- Python `3.11+`

## Setup

Runtime only:

```bash
pip install -r requirements.txt
```

Development setup:

```bash
pip install -r requirements-dev.txt
```

## Analysis Surfaces

### CLI analyzer

The analyzer supports:

- `--format full`
- `--format unused`
- `--format json`
- `--format xlsx`

Examples:

```bash
python3 scripts/analyze_model_usage.py . --format full
python3 scripts/analyze_model_usage.py . --format json -o analysis.json
python3 scripts/analyze_model_usage.py . --format xlsx -o analysis.xlsx
```

You can also use explicit paths:

```bash
python3 scripts/analyze_model_usage.py \
  --models-path /path/to/Model.SemanticModel \
  --reports-path /path/to/Report.Report \
  --format unused
```

### Web app

Start the local UI:

```bash
python3 scripts/app.py .
```

Open `http://127.0.0.1:5001`.

The web app supports:

- browse/select model and reports
- analyze and review results
- export the latest analysis as `json` or `xlsx`
- apply cleanup actions such as move to folder, hide/unhide, and delete

Optional flags:

```bash
python3 scripts/app.py . --port 8080
python3 scripts/app.py . --host 0.0.0.0
python3 scripts/app.py . --debug
```

## Supported Exports

### CLI exports

- `json`
- `xlsx`

### Web UI exports

- `Export JSON`
- `Export Excel`

Both web exports download the latest completed analysis without re-running it.

## Safety Notes

- The workflow is intentionally `1 semantic model -> 1 or more reports`
- The app creates a backup before destructive edits when requested
- Field parameters backed by `NAMEOF(...)` are supported
- Remaining caveats include calculation groups, broader metadata indirection, and malformed or skipped JSON

## Development

Run tests:

```bash
python3 -m pytest
```

Run lint:

```bash
python3 -m ruff check .
```

## Repo Layout

- `scripts/analyze_model_usage.py`: CLI analyzer and export logic
- `scripts/analyze_model_usage.README.md`: analyzer-specific behavior and limits
- `scripts/app.py`: Flask app and API
- `scripts/tmdl_writer.py`: TMDL edit engine
- `scripts/templates/index.html`: single-page web UI
- `tests/`: automated tests and fixtures

## Roadmap

Planned follow-up work is tracked in [BACKLOG.md](BACKLOG.md).

## More Detail

Analyzer-specific usage and caveats are documented in [scripts/analyze_model_usage.README.md](scripts/analyze_model_usage.README.md).
