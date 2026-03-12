# Contributing

This repository is maintained for internal team use.

## Setup

Runtime only:

```bash
pip install -r requirements.txt
```

Development setup:

```bash
pip install -r requirements-dev.txt
```

## Run the tool

CLI analyzer:

```bash
python3 scripts/analyze_model_usage.py . --format full
python3 scripts/analyze_model_usage.py . --format json -o analysis.json
python3 scripts/analyze_model_usage.py . --format xlsx -o analysis.xlsx
```

Web app:

```bash
python3 scripts/app.py .
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

## Repo hygiene

- Do not commit generated analysis exports such as `*_usage_analysis.json` or `*_usage_analysis.xlsx`.
- Do not commit personal editor workspace files such as `*.code-workspace`.
- Do not commit Python cache artifacts such as `__pycache__/` or `*.pyc`.

## Backlog workflow

Use one git worktree per backlog item.

Create:

```bash
python3 scripts/worktree_backlog.py create "item 123 refresh toggle"
```

List:

```bash
python3 scripts/worktree_backlog.py list
```

Remove after merge:

```bash
python3 scripts/worktree_backlog.py remove item-123-refresh-toggle --delete-branch
```

Notes:

- Branches use the `backlog/<slug>` naming convention by default.
- Run the helper from an existing linked worktree to keep new worktrees in the same shared home.
- Set `SMC_WORKTREE_HOME` if you want a fixed custom worktree root on your machine.
