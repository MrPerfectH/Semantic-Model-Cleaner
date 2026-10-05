"""Consistent text output for command-line and desktop entry points."""
import sys


def configure_console_output() -> None:
    """Emit UTF-8 through consoles and redirected pipes regardless of locale.

    Keep embedded hosts' fixed/closed streams intact. Reconfigure existing
    wrappers rather than replacing them, preserving capture and buffering.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, TypeError, ValueError):
            continue
