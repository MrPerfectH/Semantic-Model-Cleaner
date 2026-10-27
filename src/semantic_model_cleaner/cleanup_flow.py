"""Batch deletion candidates checked against the same policy as reviewed plans."""
from . import analyzer
from .cleanup_policy import _evaluate_deletion_policy


def checked_subset(model, reports, actions, analysis):
    """Prune blockers to a fixed point; retaining an owner can retain its targets."""
    remaining = list(actions)
    kept = {}
    while remaining:
        policy = _evaluate_deletion_policy(model, reports, remaining, analysis=analysis)
        if policy['ok']:
            break
        blocked = set()
        named_tables = {v['table'].casefold() for v in policy['violations'] if v['name']}
        for violation in policy['violations']:
            table, name = violation['table'].casefold(), violation['name'].casefold()
            matches = [(index, action) for index, action in enumerate(remaining)
                       if (not table or action['table'].casefold() == table)
                       and (not name or action['name'].casefold() == name or action['item_type'] == 'Table')]
            if table and not name:
                explicit = [(index, action) for index, action in matches if action['item_type'] == 'Table']
                if explicit:
                    matches = explicit
                elif table in named_tables:
                    # Named blockers already retain this table. Recheck after
                    # retaining those items rather than rejecting every sibling.
                    continue
                elif matches:
                    # Retain a stable table anchor, preferring a physical column.
                    matches = [min(matches, key=lambda pair: (pair[1]['item_type'] != 'Column', pair[1]['name'].casefold()))]
            for index, action in matches:
                blocked.add(index)
                key = analyzer.normalize_key(action['table'], action['name'])
                reasons = kept.setdefault(key, [])
                if violation not in reasons:
                    reasons.append(violation)
        if not blocked:
            # A policy problem that cannot be assigned is a scope-wide blocker.
            for index, action in enumerate(remaining):
                blocked.add(index)
                kept[analyzer.normalize_key(action['table'], action['name'])] = policy['violations']
        remaining = [action for index, action in enumerate(remaining) if index not in blocked]
    return {'actions': remaining, 'kept': kept}


def calculated_tables(model):
    """Names with declared calculated partitions, from TMDL structure only."""
    from .tmdl_declarations import scan_tmdl_declarations
    tables = {}
    for path in sorted((model / 'definition/tables').glob('*.tmdl')):
        declarations = scan_tmdl_declarations(path.read_text(encoding='utf-8'))
        for declaration in declarations:
            if declaration.keyword == 'partition' and declaration.expression.casefold() == 'calculated':
                owner = declaration.owner('table')
                if owner:
                    source = declaration.child('source')
                    tables.setdefault(owner.name, []).append((path, source.expression if source else ''))
    return tables


def table_actions(model, analysis, *, include_review=False):
    grouped = {}
    for row in analysis['items']:
        if row['item'].source_kind == 'model':
            grouped.setdefault(row['item'].table.casefold(), []).append(row)
    actions = []
    for table in calculated_tables(model):
        children = grouped.get(table.casefold(), [])
        if not children or any(analyzer.row_usage_status(row) != 'NOT USED' or row.get('structural_unit')
                               or row.get('analysis_limitation_ids') or row['item'].is_key for row in children):
            continue
        if any(row['removal_risk'] == 'Review' and set(row['review_triggers']) != {'Item is hidden'} for row in children):
            continue
        if any(row['item'].is_hidden for row in children) and not include_review:
            continue
        action = dict(action='delete', table=table, name=table, item_type='Table')
        if include_review and any(row['item'].is_hidden for row in children):
            action['allow_hidden'] = True
        actions.append(action)
    return actions


def cleanup_actions(query, *, cascade=False, include_review=False):
    if not cascade and not include_review:
        candidates = list(query._safe_cleanup()['actions'])
    else:
        candidates = []
        for key, row in query.rows.items():
            if key[0] != 'model' or analyzer.row_usage_status(row) != 'NOT USED':
                continue
            hidden_only = row['removal_risk'] == 'Review' and set(row['review_triggers']) == {'Item is hidden'}
            if row['removal_risk'] not in {'Safe', 'Caution'} and not (include_review and hidden_only):
                continue
            if not cascade and query._basic_recommendation(key) not in {'Safe', 'Review'}:
                continue
            action = dict(action='delete', table=key[2], name=key[3], item_type=key[1])
            if hidden_only:
                action['allow_hidden'] = True
            candidates.append(action)
    tables = table_actions(query.model, query.result, include_review=include_review)
    replacing = {action['table'].casefold() for action in tables}
    # One table action replaces every item action for it, including inferred columns.
    candidates = [a for a in candidates if a['table'].casefold() not in replacing] + tables
    return checked_subset(query.model, query.reports, candidates, query.result)


def create_cleanup_plan(project, model, reports, *, cascade=False, include_review=False, **options):
    from . import change_plan, insights
    query = insights.Insights(*insights.select_scope(project, model, reports))
    selected = cleanup_actions(query, cascade=cascade, include_review=include_review)
    actions = selected['actions']
    removed = {analyzer.normalize_key(a['table'], a['name']) for a in actions if a['item_type'] != 'Table'}
    tables = {a['table'].casefold() for a in actions if a['item_type'] == 'Table'}
    kept = []
    for key, row in query.rows.items():
        if key[0] != 'model' or analyzer.row_usage_status(row) != 'NOT USED' or (analyzer.normalize_key(key[2], key[3]) in removed or key[2].casefold() in tables):
            continue
        reasons = query._kept_because(key)
        for violation in selected['kept'].get(analyzer.normalize_key(key[2], key[3]), []):
            reason = dict(rule_id=violation['rule_id'], reason=violation['message'],
                          location=violation.get('location', {'file': row['item'].source_file}),
                          dependency=violation.get('dependency', {}))
            if reason not in reasons:
                reasons.append(reason)
        if not reasons:
            reasons = [dict(rule_id='SMC-D006', reason='A retained declaration or consumer blocks this deletion group.',
                            location={'file': row['item'].source_file}, dependency={})]
        kept.append({**query.identity(key), 'kept_because': reasons})
    plan = change_plan.create_plan(model, reports, [dict(kind='actions', actions=actions)], project_path=project, **options)
    plan['cleanup'] = dict(mode='unused', cascade=cascade, include_review=include_review, action_count=len(actions),
        deleted_items=sum(1 for row in query.result['items'] if row['item'].source_kind == 'model'
                          and (analyzer.normalize_key(*row['item'].key) in removed or row['item'].table.casefold() in tables)),
        deleted_tables=sorted(a['table'] for a in actions if a['item_type'] == 'Table'), kept=kept,
        held_back_hidden=sum(set(row['review_triggers']) == {'Item is hidden'} and analyzer.row_usage_status(row) == 'NOT USED'
                             and analyzer.normalize_key(*row['item'].key) not in removed and row['item'].table.casefold() not in tables
                             for row in query.result['items'] if row['item'].source_kind == 'model'))
    plan['digest'] = change_plan._seal(plan)
    return plan
