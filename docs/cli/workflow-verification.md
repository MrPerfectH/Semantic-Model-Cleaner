# Core CLI workflow verification

This audit covers one local Semantic Model and connected PBIR Reports. It does
not evaluate calculation results, refresh a model, render Reports or discover
service consumers. Tests use synthetic projects and public CLI subprocesses.

## Existing coverage retained

- `tests/test_cli_insights.py` covers public usage queries, direct/indirect
  dependencies, retained dependencies, stale versus live locations, Report
  identity, narrowed scope, read-only output, and dead measure groups. Lower-level
  graph tests were not duplicated.
- `tests/test_cli_contract.py` covers CLI streams/exit codes, output protection,
  Unicode and the saved-plan apply/verify/restore lifecycle, including stale-plan
  refusal. `tests/test_operations_contract.py` covers operation schema validation
  and invalid requests before source writes.
- `tests/test_plan_refactors.py` covers model table/measure/column renames across
  same-named Reports, dependency-closed promotion and same-name ownership.
  `tests/test_plan_write_boundaries.py` covers the shared engine and legacy write
  shortcuts. These engine/API checks remain the detailed refactoring regression
  suite; new CLI tests focus on integration boundaries.
- `tests/test_cli_path_selection.py` covers consistent exact selection from a
  different terminal directory, legacy behavior, bindings and missing paths.

## Public CLI gaps filled

`tests/test_cli_core_workflows.py` adds end-to-end journeys through canonical
PROJECT-relative selectors and the public module entry point:

- Rename a measure: review a plan/diff, apply it, inspect the rewritten PBIR
  property, and query the renamed model item to confirm Report usage.
- Move a measure: inspect its usage under the new home table after applying
  the supported model/Report rewrites.
- Promote a Report Extension Measure: establish a real Report consumer, move
  the same-name measure into the model, confirm the Report-local declaration is
  removed, and query the consumer against the model-owned measure. The current
  promotion contract preserves the name/home table; an unchanged PBIR field
  reference can correctly resolve to the newly model-owned item.
- Clean stale metadata: build a saved-plan operation from public discovery
  output, apply it, confirm no stale candidates remain and the live visual query
  is unchanged. Usage of its live measure must still be reported.
- Each change journey verifies preview does not modify inputs, apply writes the
  reviewed result, verify reports the applied state, and restore recovers every
  original project byte. A fresh check must report no new broken references.
- Usage/cleanup evidence: query a measure with direct and indirect consumers,
  identify an unused candidate without claiming external consumers were checked,
  and introduce a broken Report Reference to confirm a blocking source finding.
- Incomplete analysis: unreadable Report JSON lowers an unused candidate to
  Review and prevents a deletion plan from being produced or writing source files.

## CI configuration and presentation

`tests/test_ci_gate.py` checks configurable gates, preservation of fingerprints,
baseline/review-decision precedence, expiry/staleness, protected failures, unknown
configuration and the check/review agreement. `tests/test_ci_summary.py` checks
Markdown/JSON agreement, failure summaries, metadata escaping, bounded output,
review visibility and export boundaries including aliases and hard links.

Run all of these with the repository's normal `python -m pytest` command. No
Power BI Desktop, live tenant, credentials or production model is required.
