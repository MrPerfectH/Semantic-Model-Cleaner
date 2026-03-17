# Contributing

Thanks for contributing to Semantic Model Cleaner.

## Development Setup

Install the project in editable mode with development dependencies:

```bash
python -m pip install -e .[dev]
```

## Running the Tool

CLI analyzer:

```bash
semantic-model-cleaner . --format full
semantic-model-cleaner . --format json -o analysis.json
semantic-model-cleaner . --format xlsx -o analysis.xlsx
```

Local web app:

```bash
semantic-model-cleaner-web .
```

Compatibility wrappers still work from a clone:

```bash
python3 scripts/analyze_model_usage.py .
python3 scripts/app.py .
```

Desktop launcher:

```bash
semantic-model-cleaner-desktop .
```

## Checks

Run tests:

```bash
python3 -m pytest
```

Run lint:

```bash
python3 -m ruff check .
```

Build distributions:

```bash
python3 -m build
```

## Contribution Expectations

- Keep changes scoped to a single concern when possible
- Add or update tests for behavior changes
- Preserve the local-first workflow and avoid introducing hosted-service assumptions
- Document user-visible behavior changes in the README when they affect setup or usage

## Repo Hygiene

- Do not commit generated analysis exports such as `*_usage_analysis.json` or `*_usage_analysis.xlsx`
- Do not commit personal editor workspace files such as `*.code-workspace`
- Do not commit Python cache or build artifacts such as `__pycache__/`, `*.pyc`, `dist/`, or `build/`
