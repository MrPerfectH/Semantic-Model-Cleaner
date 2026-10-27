"""Data-only blockers shared by plan errors and cleanup explanations."""
from pathlib import Path


def location(reference):
    return {'artifact': reference.artifact_kind, 'report': reference.report,
            'report_path': reference.report_path, 'page': reference.page,
            'visual': reference.visual_id, 'file': str(Path(reference.report_path) / reference.artifact_path),
            'json_path': reference.source_path}


def policy_blockers(violations, operations):
    output = []
    for violation in violations:
        matches = []
        for operation_index, operation in enumerate(operations):
            for action_index, action in enumerate(operation.get('actions', [])):
                if action.get('action') != 'delete':
                    continue
                if violation['table'] and action['table'].casefold() != violation['table'].casefold():
                    continue
                if violation['name'] and action.get('item_type', '').casefold() != 'table' \
                        and action['name'].casefold() != violation['name'].casefold():
                    continue
                matches.append((operation_index, action_index, action))
        for operation_index, action_index, action in matches or [(None, None, violation)]:
            output.append({'rule_id': violation['rule_id'], 'operation_index': operation_index,
                'action_index': action_index, 'table': action.get('table', ''), 'name': action.get('name', ''),
                'item_type': action.get('item_type', ''), 'reason': violation['message'],
                'location': {**dict.fromkeys(('artifact', 'report', 'page', 'visual', 'file', 'json_path'), ''),
                             **violation.get('location', {})}, 'dependency': violation.get('dependency'),
                'resolution': 'Remove this action; retain the item and its required table, or first remove its retained consumer in a reviewed plan.'})
    return output


def reference_blockers(problems, operations):
    output = []
    for problem in sorted(problems):
        if problem[0] == 'report':
            _, artifact, report, page, issue, file, path, visual, kind, table, name, message = problem
            reason = message or f'Report {report}, page {page}, visual {visual}: {issue} for {table}[{name}] ({file}: {path}).'
            where = dict(artifact=artifact, report=report, page=page, visual=visual, file=file, json_path=path)
        else:
            _, artifact, table, name, message = problem
            kind, reason = '', f'Retained {table}[{name}] has an unresolved reference: {message}.'
            where = dict(artifact=artifact, report='', page='', visual='', file='', json_path='')
        matches = []
        for operation_index, operation in enumerate(operations):
            for action_index, action in enumerate(operation.get('actions', [])):
                if action.get('action') == 'delete' and action['table'].casefold() == table.casefold():
                    matches.append((operation_index, action_index, action))
        if not matches:
            matches = [(oi, None, {}) for oi, op in enumerate(operations)
                       if op.get('kind') == 'dax' and op.get('table') == table and op.get('name') == name]
        for operation_index, action_index, action in matches or [(0 if len(operations) == 1 else None, None, {})]:
            output.append(dict(rule_id='SMC-PLAN-REFERENCE', operation_index=operation_index,
                action_index=action_index, table=action.get('table', table), name=action.get('name', name),
                item_type=action.get('item_type', kind), reason=reason, location=where,
                resolution='Remove the action that invalidates this reference, or include an explicit supported reference repair.'))
    return output


def summary(blockers, operations):
    all_actions = {(oi, ai) for oi, op in enumerate(operations) for ai, _ in enumerate(op.get('actions', []))}
    blocked = {(b['operation_index'], b['action_index']) for b in blockers if b['action_index'] is not None}
    return {'blockers': blockers, 'blocked_action_count': len(blocked),
            'remaining_action_count': len(all_actions - blocked),
            'blocked_actions': [dict(operation_index=oi, action_index=ai) for oi, ai in sorted(blocked)],
            'remaining_actions': [dict(operation_index=oi, action_index=ai) for oi, ai in sorted(all_actions - blocked)],
            'remaining_actions_require_preview': True}
