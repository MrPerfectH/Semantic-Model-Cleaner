"""Repository change plans: stage, inspect, fingerprint, apply and recover.

Plans contain only selected artifact metadata. No writer executes against originals
until staging and reference checks succeed. Local plans are review artifacts, not a
remote command protocol. They must never be accepted from an untrusted source.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import uuid

from . import __version__, analyzer, report_writer, tmdl_writer

SUFFIXES = {'.tmdl', '.json', '.pbir', '.pbism'}
SCHEMA_VERSION = 1


class PlanError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _encoded(value):
    return None if value is None else base64.b64encode(value).decode('ascii')


def _decoded(value):
    return None if value is None else base64.b64decode(value, validate=True)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _seal(plan):
    return _digest(_canonical({k: v for k, v in plan.items() if k != 'digest'}))


def _roots(model_path, report_paths):
    paths = [Path(model_path).resolve(), *sorted({Path(p).resolve() for p in report_paths})]
    if not paths[0].is_dir() or not (paths[0] / 'definition').is_dir():
        raise PlanError('Select an existing TMDL .SemanticModel folder with a definition directory.')
    if len(paths) < 2:
        raise PlanError('Select at least one PBIR report; plans must state their report scope.')
    if any(not p.is_dir() or not (p / 'definition').is_dir() for p in paths[1:]):
        raise PlanError('Every selected report must have an existing PBIR definition directory.')
    if len(set(paths)) != len(paths) or any(a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i+1:]):
        raise PlanError('Artifact roots must be distinct and must not contain one another.')
    return {('model' if i == 0 else f'report-{i}'): p for i, p in enumerate(paths)}


def _inventory(roots):
    inventory = {}
    for artifact, root in roots.items():
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise PlanError(f'Symlinks are not supported in change-plan scope: {path}')
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                inventory[f'{artifact}/{path.relative_to(root).as_posix()}'] = path.read_bytes()
    return inventory


def _path(roots, key):
    parts = PurePosixPath(key).parts
    if len(parts) < 2 or parts[0] not in roots or any(p in ('.', '..') for p in parts) or '\\' in key:
        raise PlanError(f'Invalid artifact-relative path: {key}')
    root = roots[parts[0]]
    target = root.joinpath(*parts[1:])
    if target.suffix.lower() not in SUFFIXES or not target.resolve().is_relative_to(root.resolve()):
        raise PlanError(f'Path escapes the metadata scope: {key}')
    if target.is_symlink() or any(p.is_symlink() for p in target.parents if p.is_relative_to(root)):
        raise PlanError(f'Symlink target is not supported: {key}')
    return target


def _hashes(inventory):
    return {k: _digest(v) for k, v in sorted(inventory.items())}


def _result(result):
    if isinstance(result, list):
        if not all(r.get('ok') for r in result):
            raise PlanError('; '.join(str(r.get('error', 'Operation failed')) for r in result if not r.get('ok')))
    elif not result.get('ok'):
        raise PlanError(result.get('error') or '; '.join(map(str, result.get('errors', []))) or 'Operation failed')
    return result


def _remap(value, originals, staged):
    if isinstance(value, list):
        return [_remap(v, originals, staged) for v in value]
    if isinstance(value, dict):
        return {k: _remap(v, originals, staged) for k, v in value.items()}
    if isinstance(value, str):
        for key, root in originals.items():
            if value == str(root) or value.startswith(str(root) + os.sep):
                return str(staged[key]) + value[len(str(root)):]
    return value


def _validate_operation_paths(value, roots):
    if isinstance(value, list):
        for child in value:
            _validate_operation_paths(child, roots)
    elif isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and ("path" in key.lower() or "file" in key.lower()):
                path = Path(child)
                if key in {'report_path', 'source_file', 'sourceFile', 'file_path'} and child and not path.is_absolute():
                    raise PlanError(f'Explicit writer paths must be absolute within selected artifacts: {key}')
                if ".." in path.parts:
                    raise PlanError(f"Parent-relative source paths are not allowed: {key}")
                if path.is_absolute() and not any(path.resolve().is_relative_to(p.resolve()) for p in roots.values()):
                    raise PlanError(f"Operation path is outside staged artifacts: {key}")
            _validate_operation_paths(child, roots)


def _execute(op, roots):
    model = roots['model']
    reports = [p for k, p in roots.items() if k != 'model']
    if op.get('report_paths'):
        selected = [Path(p) for p in op['report_paths']]
        if any(p not in reports for p in selected):
            raise PlanError('Operation reports must belong to the plan scope.')
        if op.get('kind') in {'rename', 'move'} and set(selected) != set(reports):
            raise PlanError('Model rename and move must propagate through every report in the plan scope.')
        reports = selected
    kind = op.get('kind')
    if kind == 'actions':
        return _result(tmdl_writer.apply_actions(model, op.get('actions', [])))
    if kind == 'rename':
        kwargs = {k: op[k] for k in ('table_renames', 'measure_renames', 'column_renames') if op.get(k)}
        _result(tmdl_writer.rename_model_metadata(model, **kwargs))
        return _result(report_writer.rewrite_model_reference_changes(report_paths=reports, **kwargs))
    if kind == 'move':
        _result(tmdl_writer.move_measures_to_tables(model, op.get('moves', [])))
        return _result(report_writer.rewrite_measure_table_references(report_paths=reports, moves=op.get('moves', [])))
    if kind == 'promote':
        if not op.get('report_path') and len(reports) != 1:
            raise PlanError('Promotion requires an exact report_path when multiple reports are selected.')
        report = Path(op.get('report_path') or reports[0])
        if report not in reports:
            raise PlanError('Promotion report must belong to the plan scope.')
        return _result(report_writer.migrate_measure_to_model(
            model_path=model, report_path=report, entity_name=op.get('table', ''),
            measure_name=op.get('name', ''), target_table=op.get('target_table'),
            target_name=op.get('target_name'), include_dependencies=bool(op.get('include_dependencies')),
            allow_metadata_loss=bool(op.get('allow_metadata_loss'))))
    if kind == 'dax':
        return _result(tmdl_writer.set_dax_expression(model_path=model, **{
            k: op[k] for k in ('table', 'name', 'item_type', 'dax_expression', 'source_file') if k in op}))
    if kind in ('clean_stale', 'report_issues'):
        entries = op.get('entries', [])
        for entry in entries:
            entry_report = Path(str(entry.get('report_path', '')))
            artifact = Path(str(entry.get('artifact_path', '')))
            if not entry_report.is_absolute() or entry_report not in reports:
                raise PlanError('Every report action must identify an exact selected report by absolute path.')
            if artifact.is_absolute() or '..' in artifact.parts or not (entry_report / artifact).resolve().is_relative_to(entry_report):
                raise PlanError('Report action artifact must stay inside its selected report.')
            # Row operations must not point outside copied metadata, even if a
            # malicious row supplied an absolute path in a nested field.
            for k, value in entry.items():
                if isinstance(value, str) and ('path' in k.lower() or 'file' in k.lower()) and Path(value).is_absolute():
                    if not any(Path(value).resolve().is_relative_to(p.resolve()) for p in reports):
                        raise PlanError(f'Report action path is outside selected reports: {k}')
        writer = report_writer.cleanup_stale_metadata_selectors if kind == 'clean_stale' else report_writer.apply_report_issue_actions
        return _result(writer(entries=entries, dry_run=False))
    if kind == 'report_repair':
        return _result(report_writer.rewrite_model_reference_changes(report_paths=reports, **{
            k: op[k] for k in ('table_renames', 'measure_renames', 'column_renames') if op.get(k)}))
    raise PlanError(f'Unsupported operation kind: {kind}')


def _analyze(roots):
    try:
        reports = {k: p for k, p in roots.items() if k != 'model'}
        result = analyzer.analyze(roots['model'].parent, model_paths=[roots['model']],
                                  report_paths=list(reports.values()))
        # Report display names are not unique. Analyze report issues separately
        # so identical visual paths in distinct artifacts never hide new errors.
        result['_report_issues_by_artifact'] = {}
        for key, path in reports.items():
            single = result if len(reports) == 1 else analyzer.analyze(
                roots['model'].parent, model_paths=[roots['model']], report_paths=[path])
            result['_report_issues_by_artifact'][key] = single.get('report_issues', [])
        return result
    except SystemExit as exc:
        raise PlanError('Analysis could not read the selected TMDL/PBIR scope.') from exc


def _mapped_identity(table, name, operations, item_type=None):
    for op in operations or []:
        old_table = table
        for rename in op.get('table_renames', []) if op.get('kind') == 'rename' else []:
            if table.casefold() == str(rename.get('table', '')).casefold():
                table = rename.get('target_table', table)
        renames = op.get('measure_renames', []) if item_type == 'Measure' else op.get('column_renames', []) if item_type in {'Column', 'Calculated Column'} else []
        for rename in renames if op.get('kind') == 'rename' else []:
            if str(rename.get('table', '')).casefold() in {str(table).casefold(), str(old_table).casefold()} and name.casefold() == str(rename.get('name', '')).casefold():
                name = rename.get('target_name', name)
        for move in op.get('moves', []) if op.get('kind') == 'move' and item_type == 'Measure' else []:
            if table.casefold() == str(move.get('table', '')).casefold() and name.casefold() == str(move.get('name', '')).casefold():
                table = move.get('target_table', table)
    return table, name


def _problems(results, operations=None):
    # Compare exact error locations and map owners through reviewed refactors.
    # Equal counts alone would miss a newly broken visual with an existing error.
    found = set()
    for row in results.get('items', []):
        item = row['item']
        table, name = _mapped_identity(item.table, item.name, operations, item.item_type)
        for ref in row.get('broken_dax_refs', []):
            found.add(('model', item.source_artifact, table, name, str(ref)))
    issue_sets = results.get('_report_issues_by_artifact', {'report': results.get('report_issues', [])})
    for artifact_id, issues in issue_sets.items():
        for issue in issues:
          if issue.get('severity') == 'error':
              table, name = _mapped_identity(str(issue.get('table', '')), str(issue.get('name', '')),
                                             operations, issue.get('refType'))
              found.add(('report', artifact_id, *(str(issue.get(key, '')) for key in (
                  'report', 'page', 'issueType', 'artifactPath', 'sourcePath', 'visualId', 'refType')),
                  table, name, str(issue.get('message', '')) if not issue.get('issueType') else ''))
    return found


def _validate_json(inventory, *, tolerate_existing=None):
    errors = []
    for key, content in inventory.items():
        if Path(key).suffix.lower() not in {'.json', '.pbir', '.pbism'}:
            continue
        try:
            obj = json.loads(content)
            if not isinstance(obj, dict):
                raise ValueError('Expected a JSON object')
        except (ValueError, UnicodeError) as exc:
            if tolerate_existing is not None and tolerate_existing.get(key) == content:
                continue
            errors.append(f'{key}: {exc}')
    if errors:
        raise PlanError('Incomplete or invalid metadata: ' + '; '.join(errors))


def create_plan(model_path, report_paths, operations):
    """Preview only; no input files or backups are written."""
    if not isinstance(operations, list) or not operations or any(not isinstance(o, dict) for o in operations):
        raise PlanError('operations must be a nonempty list of objects.')
    originals = _roots(model_path, report_paths)
    before = _inventory(originals)
    # Destructive/refactoring plans cannot claim complete propagation while a
    # selected document is unreadable. Non-reference metadata edits can proceed.
    strict = any(o.get('kind') in {'rename', 'move', 'promote', 'report_repair', 'dax'} or
                 any(a.get('action') in {'delete', 'delete_table'} for a in o.get('actions', [])) for o in operations)
    bindings = [analyzer.report_binding_status(p, originals['model']) for key, p in originals.items() if key != 'model']
    if strict:
        _validate_json(before)
        if any(binding['status'] not in analyzer.BOUND_REPORT_STATUSES for binding in bindings):
            raise PlanError('Refactoring requires reports bound to the selected model; verify definition.pbir and selected scope.')
    from .cleanup_policy import evaluate_deletion_policy
    actions = [a for op in operations if op.get('kind') == 'actions' for a in op.get('actions', [])]
    policy = evaluate_deletion_policy(originals['model'], list(originals.values())[1:], actions)
    if not policy['ok']:
        raise PlanError('; '.join(policy['errors']))
    from . import metadata_validation
    schema_before = metadata_validation.validate_metadata(before)
    baseline = _analyze(originals)
    if strict and not baseline.get('coverage', {}).get('complete', True):
        raise PlanError('Refactoring requires complete supported scan coverage. Resolve metadata limitations first.')
    with tempfile.TemporaryDirectory(prefix='smc-plan-') as temp:
        staged = {k: Path(temp).resolve() / k / p.name for k, p in originals.items()}
        for path in staged.values():
            path.mkdir(parents=True)
        for key, content in before.items():
            path = _path(staged, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for op in operations:
            mapped = _remap(op, originals, staged)
            # Validate explicit source files before allowing writer access.
            source = mapped.get('source_file')
            if source and not Path(source).resolve().is_relative_to(staged['model']):
                raise PlanError('Source file is outside selected model.')
            _validate_operation_paths(mapped, staged)
            _execute(mapped, staged)
        after = _inventory(staged)
        _validate_json(after, tolerate_existing=None if strict else before)
        schema_after = metadata_validation.validate_metadata(after)
        schema_comparison = metadata_validation.compare_validation(schema_before, schema_after)
        if schema_comparison["new_errors"] or schema_comparison["lost_validation"] or schema_comparison["truncated"]:
            raise PlanError("Change introduces schema errors, loses declared schema validation, or exceeds the schema error limit. Repair the metadata before applying.")
        analysis = _analyze(staged)
        added = _problems(analysis) - _problems(baseline, operations)
        if added:
            raise PlanError('Change introduces unresolved references: ' + '; '.join(str(x) for x in sorted(added)))
    if _hashes(_inventory(originals)) != _hashes(before):
        raise PlanError('Input changed while preview was being prepared; re-analyze and retry.')
    changes = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        changes.append({'artifact': key.split('/')[0], 'path': key,
                        'change': 'added' if old is None else 'deleted' if new is None else 'modified',
                        'before': _encoded(old), 'after': _encoded(new),
                        'diff': ''.join(difflib.unified_diff(
                            (old or b'').decode('utf-8-sig').splitlines(keepends=True),
                            (new or b'').decode('utf-8-sig').splitlines(keepends=True),
                            fromfile='a/' + key, tofile='b/' + key))})
    plan = {'schema_version': SCHEMA_VERSION, 'tool_version': __version__, 'id': uuid.uuid4().hex,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'scope': {k: str(p) for k, p in originals.items()},
            'coverage': {'reports': [{k: b.get(k) for k in ('name', 'status', 'message')} for b in bindings],
                         'analysis': baseline.get('coverage', {})}, 'operations': operations,
            'inputs': _hashes(before), 'outputs': _hashes(after), 'changes': changes,
            'validation': {'json_syntax': 'passed' if strict else 'changed files passed',
                           'reference_integrity': 'no new unresolved references',
                           'existing_problem_count': len(_problems(baseline)),
                           'remaining_problem_count': len(_problems(analysis)),
                           'pbir_schema': {'before': schema_before['counts'], 'after': schema_after['counts'],
                                           'comparison_complete': schema_comparison['comparison_complete'],
                                           'changed_not_validated': schema_comparison['changed_not_validated'],
                                           'bundle_commit': schema_after['bundle'].get('commit')},
                           'limitations': ['Static analysis of selected TMDL/PBIR only.',
                                           'Only supported declared PBIR schemas are validated; TMDL/DAX engine validation is not performed.']}}
    plan['digest'] = _seal(plan)
    return plan


def _atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        path.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix='.smc-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_plan(plan, directory):
    directory = Path(directory)
    _atomic(directory / f'{plan["id"]}.plan.json', json.dumps(plan, indent=2).encode())
    return directory / f'{plan["id"]}.plan.json'


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    _check(plan)
    return plan


def _check(plan):
    if plan.get('schema_version') != SCHEMA_VERSION or plan.get('digest') != _seal(plan):
        raise PlanError('Unsupported or edited plan. Generate a fresh preview.')
    if not isinstance(plan.get('id'), str) or len(plan['id']) != 32 or any(c not in '0123456789abcdef' for c in plan['id']):
        raise PlanError('Invalid plan identity.')
    scope = plan.get('scope', {})
    roots = _roots(scope['model'], [v for k, v in scope.items() if k != 'model'])
    if {k: str(v) for k, v in roots.items()} != scope:
        raise PlanError('Invalid or reordered artifact scope.')
    keys = set()
    expected = dict(plan['inputs'])
    for change in plan['changes']:
        key = change['path']
        _path(roots, key)
        if key in keys:
            raise PlanError('Duplicate change path.')
        keys.add(key)
        old, new = _decoded(change['before']), _decoded(change['after'])
        if expected.get(key) != (None if old is None else _digest(old)):
            raise PlanError('Change content does not match input fingerprint.')
        if new is None:
            expected.pop(key, None)
        else:
            expected[key] = _digest(new)
    if expected != plan['outputs']:
        raise PlanError('Change set does not match output fingerprint.')
    return roots


@contextmanager
def _lock(roots, directory):
    directory = Path(directory).resolve()
    if any(directory.is_relative_to(root) or root.is_relative_to(directory) and directory == root for root in roots.values()):
        raise PlanError('The journal directory must be outside selected model/report artifacts.')
    directory.mkdir(parents=True, exist_ok=True)
    # Per-model lock covers differing report scopes for the same semantic model.
    path = directory / (_digest(str(roots['model']).encode()) + '.lock')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PlanError(f'Another operation is active or interrupted. Inspect the journal and lock before retrying: {path}') from exc
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump({'pid': os.getpid(), 'model': str(roots['model']), 'created_at': datetime.now(timezone.utc).isoformat()}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        path.unlink(missing_ok=True)


def _receipt(plan, status, **extra):
    return {'id': plan['id'], 'plan_id': plan['id'], 'status': status, 'scope': plan['scope'],
            'changed_files': [c['path'] for c in plan['changes']],
            'validation': plan['validation'], 'updated_at': datetime.now(timezone.utc).isoformat(), **extra}


def apply_plan(plan, directory):
    roots = _check(plan)
    journal = Path(directory) / f'{plan["id"]}.receipt.json'
    with _lock(roots, directory):
        if journal.exists():
            raise PlanError('This operation already has a receipt. Inspect it or generate a new plan.')
        if _hashes(_inventory(roots)) != plan['inputs']:
            raise PlanError('Stale plan: selected files changed. Generate a new preview; nothing was written.')
        save_plan(plan, directory)
        receipt = _receipt(plan, 'applying', completed=[])
        _atomic(journal, json.dumps(receipt, indent=2).encode())
        completed = []
        try:
            for change in plan['changes']:
                path = _path(roots, change['path'])
                current = path.read_bytes() if path.exists() else None
                if current != _decoded(change['before']):
                    raise PlanError(f'Concurrent edit detected: {change["path"]}')
                _atomic(path, _decoded(change['after']))
                completed.append(change)
                receipt['completed'] = [c['path'] for c in completed]
                _atomic(journal, json.dumps(receipt, indent=2).encode())
            if _hashes(_inventory(roots)) != plan['outputs']:
                raise PlanError('Files changed during apply; verification failed.')
            receipt = _receipt(plan, 'applied', completed=[c['path'] for c in completed])
        except Exception as exc:
            errors = []
            for change in reversed(completed):
                path = _path(roots, change['path'])
                try:
                    if (path.read_bytes() if path.exists() else None) != _decoded(change['after']):
                        raise PlanError('File changed externally; refusing to overwrite it')
                    _atomic(path, _decoded(change['before']))
                except Exception as rollback_exc:
                    errors.append(f'{change["path"]}: {rollback_exc}')
            receipt = _receipt(plan, 'recovery_required' if errors else 'rolled_back', error=str(exc), recovery_errors=errors,
                               completed=[c['path'] for c in completed])
        _atomic(journal, json.dumps(receipt, indent=2).encode())
        return {'ok': receipt['status'] == 'applied', 'receipt': receipt}


def restore_plan(plan, directory):
    """Restore applied/interrupted files only if they still match reviewed bytes."""
    roots = _check(plan)
    journal = Path(directory) / f'{plan["id"]}.receipt.json'
    with _lock(roots, directory):
        if not journal.exists():
            raise PlanError('No apply receipt exists for this plan.')
        receipt = json.loads(journal.read_text())
        if receipt['status'] not in {'applied', 'applying', 'recovery_required', 'restoring'}:
            raise PlanError('This operation is not awaiting restoration.')
        pending = []
        for change in plan['changes']:
            path = _path(roots, change['path'])
            current = path.read_bytes() if path.exists() else None
            if current == _decoded(change['before']):
                continue
            if current != _decoded(change['after']):
                raise PlanError(f'Cannot restore over subsequent edits: {change["path"]}')
            pending.append(change)
        receipt['status'] = 'restoring'
        _atomic(journal, json.dumps(receipt, indent=2).encode())
        try:
            for change in reversed(pending):
                path = _path(roots, change['path'])
                if (path.read_bytes() if path.exists() else None) != _decoded(change['after']):
                    raise PlanError(f'Concurrent edit detected during restore: {change["path"]}')
                _atomic(path, _decoded(change['before']))
            receipt = _receipt(plan, 'restored')
        except Exception as exc:
            receipt = _receipt(plan, 'recovery_required', error=str(exc))
        _atomic(journal, json.dumps(receipt, indent=2).encode())
        return {'ok': receipt['status'] == 'restored', 'receipt': receipt}


def verify_plan(plan):
    roots = _check(plan)
    current = _hashes(_inventory(roots))
    state = 'applied' if current == plan['outputs'] else 'original' if current == plan['inputs'] else 'changed'
    return {'ok': state == 'applied', 'state': state, 'validation': plan['validation'],
            'changed_since_plan': sorted(k for k in current.keys() | plan['outputs'].keys() if current.get(k) != plan['outputs'].get(k))}


def recover_interrupted_lock(plan, directory):
    """Explicit recovery for an abandoned POSIX lock; never removes a live lock."""
    roots = _check(plan)
    directory = Path(directory).resolve()
    lock = directory / (_digest(str(roots['model']).encode()) + '.lock')
    journal = directory / f'{plan["id"]}.receipt.json'
    if not journal.exists():
        raise PlanError('A matching operation receipt is required before lock recovery.')
    if os.name != 'posix':
        raise PlanError('Automatic abandoned-lock recovery is available on POSIX only. On Windows verify the recorded process has exited before removing the lock, then use restore.')
    try:
        data = json.loads(lock.read_text())
        pid = int(data['pid'])
        if pid <= 0 or data.get('model') != str(roots['model']):
            raise PlanError('Invalid lock owner record; inspect it manually.')
        os.kill(pid, 0)
    except ProcessLookupError:
        # Do not remove a lock replaced since inspection.
        if json.loads(lock.read_text()) != data:
            raise PlanError('Lock changed during recovery.')
        lock.unlink()
        return {'ok': True, 'state': 'lock_recovered', 'next': 'Inspect the receipt, then restore the original files.'}
    except PermissionError as exc:
        raise PlanError('Cannot establish that the lock owner has exited; lock retained.') from exc
    raise PlanError('Lock owner is still running; stop that operation before recovery.')
