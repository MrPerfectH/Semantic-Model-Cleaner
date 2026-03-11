#!/usr/bin/env python3
"""Compatibility wrapper for packaged TMDL writer helpers."""

from pathlib import Path
import sys


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from semantic_model_cleaner.tmdl_writer import *  # noqa: F403
