# Semantic Model Cleaner

Internal tool for analyzing Power BI PBIR + TMDL projects, finding unused semantic model items across selected reports, and applying cleanup actions locally.

## Repo Status

- Intended audience: internal team using a private GitHub repo
- Current shape: installable Python package with CLI plus local Flask web app
- Entry points: `semantic-model-cleaner`, `semantic-model-cleaner-web`, `smc`, and `smc-web`

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
python -m pip install .
```

Development setup:

```bash
python -m pip install -e .[dev]
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
semantic-model-cleaner . --format full
semantic-model-cleaner . --format json -o analysis.json
semantic-model-cleaner . --format xlsx -o analysis.xlsx
```

Short aliases:

```bash
smc . --format full
```

You can also use explicit paths:

```bash
semantic-model-cleaner \
  --models-path /path/to/Model.SemanticModel \
  --reports-path /path/to/Report.Report \
  --format unused
```

Compatibility note:

```bash
python3 scripts/analyze_model_usage.py .
```

still works from a cloned repo, but the packaged command is now the preferred entrypoint.

Module entrypoint:

```bash
python3 -m semantic_model_cleaner . --format full
```

### Web app

Start the local UI:

```bash
semantic-model-cleaner-web .
```

Short alias:

```bash
smc-web .
```

Open `http://127.0.0.1:5001`.

The web app supports:

- browse/select model and reports
- analyze and review results
- export the latest analysis as `json` or `xlsx`
- apply cleanup actions such as move to folder, hide/unhide, and delete

Optional flags:

```bash
semantic-model-cleaner-web . --port 8080
semantic-model-cleaner-web . --host 0.0.0.0
semantic-model-cleaner-web . --debug
```

Module entrypoint:

```bash
python3 -m semantic_model_cleaner.web .
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

## Backlog Worktrees

Use one linked worktree per backlog item so feature work, reviews, and interrupts do not share
uncommitted changes.

Create a worktree:

```bash
python3 scripts/worktree_backlog.py create "item 123 refresh toggle"
```

Installed command:

```bash
smc-backlog create "item 123 refresh toggle"
```

By default the helper:

- creates a branch named `backlog/<slug>`
- creates the worktree under the current repo worktree home when already inside a linked worktree
- otherwise creates worktrees in a sibling folder named `<repo>-worktrees`
- fetches `origin` and branches from `origin/main`

Useful commands:

```bash
python3 scripts/worktree_backlog.py list
python3 scripts/worktree_backlog.py remove item-123-refresh-toggle --delete-branch
python3 scripts/worktree_backlog.py prune
```

Optional override:

```bash
SMC_WORKTREE_HOME=/path/to/worktrees python3 scripts/worktree_backlog.py create "item 123"
```

## Repo Layout

- `src/semantic_model_cleaner/analyzer.py`: CLI analyzer and export logic
- `src/semantic_model_cleaner/backlog_worktree.py`: backlog-focused git worktree helper CLI
- `src/semantic_model_cleaner/webapp.py`: Flask app and API
- `src/semantic_model_cleaner/tmdl_writer.py`: TMDL edit engine
- `src/semantic_model_cleaner/templates/index.html`: single-page web UI template
- `scripts/analyze_model_usage.py`: compatibility wrapper for the packaged CLI
- `scripts/analyze_model_usage.README.md`: analyzer-specific behavior and limits
- `scripts/app.py`: compatibility wrapper for the packaged web app
- `scripts/worktree_backlog.py`: compatibility wrapper for the backlog worktree CLI
- `tests/`: automated tests and fixtures

## Roadmap

Planned follow-up work is tracked in [BACKLOG.md](BACKLOG.md).

## More Detail

Analyzer-specific usage and caveats are documented in [scripts/analyze_model_usage.README.md](scripts/analyze_model_usage.README.md).
