"""Stable CLI dispatch; existing analyzer commands retain their behavior."""
import sys

from . import analyzer


def main(argv: list[str] | None = None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"policy", "naming"}:
        from .policy_cli import main as policy_main
        raise SystemExit(policy_main(args))
    if args and args[0] == "check":
        from .ci import main as check_main
        raise SystemExit(check_main(args[1:]))
    if args and args[0] in {"plan", "apply", "verify", "diff", "history", "restore", "recover-lock"}:
        from .plan_cli import main as plan_main
        raise SystemExit(plan_main(args))
    return analyzer.main(args)


__all__ = ["main"]
