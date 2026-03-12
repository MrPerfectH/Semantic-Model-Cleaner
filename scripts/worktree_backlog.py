#!/usr/bin/env python3
"""Compatibility wrapper for the packaged backlog worktree CLI."""

from pathlib import Path
import sys


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from semantic_model_cleaner.backlog_worktree import main


if __name__ == "__main__":
    raise SystemExit(main())
