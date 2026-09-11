"""Manage local review decisions and preview naming conventions."""
import argparse
import json
from pathlib import Path

from . import analyzer, review_policy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="smc", description="Repository review policy and naming previews.")
    commands = parser.add_subparsers(dest="command", required=True)
    policy = commands.add_parser("policy")
    policy.add_argument("action", choices=("show", "validate", "init", "add", "remove"))
    policy.add_argument("project_path", nargs="?", default=".")
    policy.add_argument("--file", help="Policy path inside the project (default .smc-policy.json).")
    policy.add_argument("--finding", help="Finding fingerprint from smc check.")
    policy.add_argument("--model", help="Model path relative to project_path.")
    policy.add_argument("--report", action="append", help="Exact report path relative to project_path.")
    policy.add_argument("--disposition", choices=sorted(review_policy.DISPOSITIONS))
    policy.add_argument("--reason")
    policy.add_argument("--owner")
    policy.add_argument("--expires-on")
    policy.add_argument("--id", help="Decision ID to remove.")
    naming = commands.add_parser("naming")
    naming.add_argument("action", choices=("preview",))
    naming.add_argument("project_path", nargs="?", default=".")
    naming.add_argument("--file", help="Policy path inside the project.")
    naming.add_argument("--model", help="Model path relative to project_path.")
    naming.add_argument("--report", action="append", help="Exact report path relative to project_path.")
    naming.add_argument("-o", "--output", help="Optional existing change-plan JSON for smc diff/apply.")
    args = parser.parse_args(argv)
    root = Path(args.project_path).resolve()
    try:
        if not root.is_dir():
            raise review_policy.PolicyError("Project directory does not exist.")
        if args.file and not (root / args.file).is_file() and not (args.command == "policy" and args.action == "init"):
            raise review_policy.PolicyError("Explicit policy file does not exist.")
        if args.command == "policy" and args.action == "validate" and not (root / (args.file or review_policy.POLICY_FILENAME)).is_file():
            raise review_policy.PolicyError("Policy file does not exist; initialize it first.")
        if args.command == "policy" and args.action in {"show", "validate", "init", "remove"}:
            current = review_policy.load_policy(root, args.file)
            if args.action == "init":
                target = root / (args.file or review_policy.POLICY_FILENAME)
                if target.exists():
                    raise review_policy.PolicyError("Policy already exists; inspect it with policy show.")
                current = review_policy.save_policy(root, current, args.file)
            elif args.action == "remove":
                if not args.id:
                    raise review_policy.PolicyError("policy remove requires --id.")
                current = review_policy.remove_decision(root, args.id, args.file)
            print(json.dumps({"ok": True, "policy": current}, indent=2))
            return 0
        models = [(root / args.model).resolve()] if args.model else analyzer.discover_models([root])
        if len(models) != 1:
            raise review_policy.PolicyError("Select exactly one Semantic Model using --model.")
        reports = [(root / path).resolve() for path in args.report] if args.report else analyzer.filter_reports_bound_to_model(analyzer.discover_reports([root]), models[0])
        if args.command == "policy":
            if not all((args.finding, args.disposition, args.reason, args.owner, args.expires_on)):
                raise review_policy.PolicyError("policy add requires --finding, --disposition, --reason, --owner, and --expires-on.")
            from .ci import run_check
            _, checked = run_check(root, model_path=models[0], report_paths=reports,
                                  policy=review_policy.load_policy(root, args.file))
            if checked["errors"]:
                raise review_policy.PolicyError("; ".join(checked["errors"]))
            finding = next((row for row in checked["findings"] if row["fingerprint"] == args.finding), None)
            if not finding:
                raise review_policy.PolicyError("Finding no longer exists in this scope; run smc check again.")
            result = review_policy.add_decision(root, finding, checked["scope"], disposition=args.disposition,
                reason=args.reason, owner=args.owner, expires_on=args.expires_on, path=args.file)
            print(json.dumps({"ok": True, "policy": result}, indent=2))
        else:
            result = review_policy.naming_preview(root, models[0], reports, policy=review_policy.load_policy(root, args.file))
            if args.output and result.get("plan"):
                target = Path(args.output).resolve()
                protected = [*models, *reports, *analyzer.discover_models([root]), *analyzer.discover_reports([root])]
                if any(target.is_relative_to(path.resolve()) for path in protected) or target == (root / (args.file or review_policy.POLICY_FILENAME)).resolve():
                    raise review_policy.PolicyError("Naming plan output must be outside artifacts and must not replace policy.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result["plan"], indent=2) + "\n", encoding="utf-8")
                result["plan_file"] = str(target)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
