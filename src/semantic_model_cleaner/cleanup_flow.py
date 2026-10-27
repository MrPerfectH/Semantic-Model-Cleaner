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
        for violation in policy['violations']:
            table, name = violation['table'].casefold(), violation['name'].casefold()
            for index, action in enumerate(remaining):
                if (not table or action['table'].casefold() == table) and (
                        not name or action['name'].casefold() == name):
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
