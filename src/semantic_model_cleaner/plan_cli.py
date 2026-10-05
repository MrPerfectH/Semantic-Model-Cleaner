"""Headless interface to the same reviewed plans used by the local UI."""
from functools import partial
import json
import os
from pathlib import Path
import sys

from . import analyzer, change_plan, model_compare
from .analysis_export import validate_export_destination
from .cli_contract import ArgumentParser, emit_json, json_requested
from .operations_contract import parse_operations


def _directory():
    return Path(os.environ.get('SMC_USER_DIR', str(Path.home() / '.semantic-model-cleaner'))) / 'plans'


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    machine = json_requested(argv)
    parser = ArgumentParser(description='Review, apply and verify local TMDL/PBIR changes.',
                            json_errors=machine)
    sub = parser.add_subparsers(dest='command', required=True,
                               parser_class=partial(ArgumentParser, json_errors=machine))
    plan = sub.add_parser('plan', help='Stage operations on copies and export exact file diffs; never edit inputs.')
    plan.add_argument('project_path', nargs='?', default='.')
    plan.add_argument('--model', help='Exact .SemanticModel path relative to CWD; otherwise discover one under project_path.')
    plan.add_argument('--report', action='append', default=[], help='Exact .Report path relative to CWD; repeat for each report.')
    plan.add_argument('--operations', required=True, help='UTF-8 JSON file (optional BOM) containing an operations array or {operations:[...]}.')
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
    for command_parser in sub.choices.values():
        command_parser.add_argument('--format', choices=['json'],
            help='Opt into UTF-8 JSON stdout for success and errors; omission preserves legacy output.')
    scope = None
    try:
        args = parser.parse_args(argv)
        def emit(payload):
            if machine:
                emit_json(args.command, payload)
            else:
                print(json.dumps(payload, indent=None if args.command == 'plan' else 2))
        if args.command == 'plan':
            root = Path(args.project_path).resolve()
            models = [Path(args.model).resolve()] if args.model else analyzer.discover_models([root])
            if len(models) != 1:
                raise change_plan.PlanError('Select exactly one semantic model with --model.')
            if args.report:
                reports = [Path(p).resolve() for p in args.report]
                scope = {"mode": "explicit", "reports": [
                    analyzer.report_binding_status(report, models[0]) for report in reports]}
            else:
                scope = analyzer.report_binding_scope(models[0], analyzer.discover_reports([root]))
                reports = [Path(row['path']) for row in scope['selected']]
                if not reports:
                    raise change_plan.PlanError('No connected Reports found; inspect definition.pbir and selected scope.')
            target = validate_export_destination(args.output, [
                *models, *reports, *analyzer.discover_models([root]), *analyzer.discover_reports([root])
            ], allow_missing_parent=True)
            if target == Path(args.operations).resolve():
                raise change_plan.PlanError('Plan output must not replace the operations file. Choose a separate external output file.')
            try:
                raw = json.loads(Path(args.operations).read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError as exc:
                raise change_plan.PlanError(
                    f'Cannot read operations file {args.operations!r}: save it as UTF-8 '
                    '(with or without a UTF-8 BOM), then retry.'
                ) from exc
            operations = parse_operations(raw)
            result = change_plan.create_plan(models[0], reports, operations)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + '\n', encoding="utf-8")
            emit({'ok': True, 'plan_file': str(target), 'id': result['id'],
                              'reportBinding': scope,
                              'changed_files': len(result['changes']), 'validation': result['validation']})
        elif args.command == 'history':
            emit({'receipts': [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.journal_dir).glob('*.receipt.json'))]})
        elif args.command == 'diff':
            if args.candidate:
                emit(model_compare.compare_models(Path(args.baseline), Path(args.candidate)))
            else:
                result = change_plan.load_plan(args.baseline)
                diff_text = ''.join(c['diff'] for c in result['changes'])
                if machine:
                    emit({'id': result['id'], 'diff': diff_text,
                          'changes': [{'path': c['path'], 'diff': c['diff']} for c in result['changes']]})
                else:
                    print(diff_text)
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
            emit(result)
            return 0 if result.get('ok') else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        error = {'ok': False, 'error': str(exc)}
        if scope is not None:
            error['reportBinding'] = scope
        if machine:
            emit_json(argv[0] if argv else 'plan', error)
        else:
            print(json.dumps(error), file=sys.stderr)
        return 2
