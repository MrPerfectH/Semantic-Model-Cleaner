"""Headless interface to the same reviewed plans used by the local UI."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import analyzer, change_plan, model_compare


def _directory():
    return Path(os.environ.get('SMC_USER_DIR', str(Path.home() / '.semantic-model-cleaner'))) / 'plans'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Review, apply and verify local TMDL/PBIR changes.')
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan', help='Stage operations on copies and export exact file diffs; never edit inputs.')
    plan.add_argument('project_path', nargs='?', default='.')
    plan.add_argument('--model', help='Exact .SemanticModel folder; otherwise discover one under project_path.')
    plan.add_argument('--report', action='append', default=[], help='Explicit .Report folder; repeat for each report.')
    plan.add_argument('--operations', required=True, help='JSON file containing an operations array or {operations:[...]}.')
    plan.add_argument('-o', '--output', required=True, help='Reviewable local plan JSON.')
    for name in ('apply', 'verify', 'restore', 'recover-lock'):
        cmd = sub.add_parser(name)
        cmd.add_argument('plan_file')
        cmd.add_argument('--journal-dir', default=str(_directory()))
    diff = sub.add_parser('diff', help='Show reviewed plan diff, or compare two semantic models.')
    diff.add_argument('baseline')
    diff.add_argument('candidate', nargs='?')
    hist = sub.add_parser('history', help='List local operation receipts.')
    hist.add_argument('--journal-dir', default=str(_directory()))
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            root = Path(args.project_path).resolve()
            models = [Path(args.model).resolve()] if args.model else analyzer.discover_models([root])
            if len(models) != 1:
                raise change_plan.PlanError('Select exactly one semantic model with --model.')
            if args.report:
                reports = [Path(p).resolve() for p in args.report]
            else:
                reports = analyzer.filter_reports_bound_to_model(analyzer.discover_reports([root]), models[0])
            target = Path(args.output).resolve()
            if any(target.is_relative_to(p.resolve()) for p in [*models, *reports, *analyzer.discover_models([root]), *analyzer.discover_reports([root])]) or target == Path(args.operations).resolve():
                raise change_plan.PlanError('Plan output must be outside discovered or selected artifacts and must not replace the operations file.')
            raw = json.loads(Path(args.operations).read_text())
            operations = raw.get('operations') if isinstance(raw, dict) else raw
            result = change_plan.create_plan(models[0], reports, operations)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'ok': True, 'plan_file': str(target), 'id': result['id'],
                              'changed_files': len(result['changes']), 'validation': result['validation']}))
        elif args.command == 'history':
            print(json.dumps({'receipts': [json.loads(p.read_text()) for p in sorted(Path(args.journal_dir).glob('*.receipt.json'))]}, indent=2))
        elif args.command == 'diff':
            if args.candidate:
                print(json.dumps(model_compare.compare_models(Path(args.baseline), Path(args.candidate)), indent=2))
            else:
                result = change_plan.load_plan(args.baseline)
                print(''.join(c['diff'] for c in result['changes']))
        else:
            plan = change_plan.load_plan(args.plan_file)
            if args.command == 'verify':
                result = change_plan.verify_plan(plan)
            elif args.command == 'recover-lock':
                result = change_plan.recover_interrupted_lock(plan, args.journal_dir)
            elif args.command == 'apply':
                result = change_plan.apply_plan(plan, args.journal_dir)
            else:
                result = change_plan.restore_plan(plan, args.journal_dir)
            print(json.dumps(result, indent=2))
            return 0 if result.get('ok') else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        return 2
