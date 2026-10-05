# R04 Use consistent connected Report selection across analysis and automation

Status: Implemented, reviewed and integrated as `4721240` on 2026-10-03. Local ticket, not a published GitHub issue.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Power BI developer, I get consistent usage evidence from the app and CLI for the same Semantic Model and Reports.

## What to build

Align ordinary analyzer discovery with the connected-report selection already used by the UI, check, and reviewed-plan workflows. Show exclusions and selection limits without contaminating machine-readable stdout. Retain documented explicit diagnostic overrides only where they already exist, clearly distinguished from normal selection.

## Evidence

A synthetic Unrelated.Report bound to Different.SemanticModel appeared in ordinary analyzer output, while smc check correctly excluded it as not_connected.

## Acceptance criteria

- [x] For equivalent default scope, UI, ordinary CLI, check, and plan choose the same supported bound Reports.
- [x] A Report bound to another Semantic Model contributes no usage references under default selection.
- [x] Missing, malformed, ambiguous, local, and supported live-connection bindings receive consistent treatment and visible evidence.
- [x] Name filters and interactive selection operate on the eligible connected set; an unmatched/empty selection fails clearly.
- [x] Explicit Report paths in reviewed workflows do not silently authorize unrelated or unverified scope; preserve any stricter mutation checks.
- [x] Machine-readable output remains parseable and identifies selected scope or documents where exclusions are reported.
- [x] Regression fixtures compare reference counts and selected identities across entry points without changing the underlying dependency/classification semantics.

## Blocked by

None — can start immediately.

## Verification

Use a synthetic project with one connected Report, one unrelated Report, and invalid binding cases. Compare CLI/UI scope and ensure an unrelated reference cannot change a Cleanup Recommendation.

### Implementation evidence (2026-10-03)

- Started from `30ecdba`, with R01 and R02 integrated. Reproduced the current discrepancy on a disposable demo copy: the integration CLI selected TestReport and Unrelated with 16 references; this change selected TestReport only with 8 references.
- Ordinary CLI and implicit Python analysis now classify discovered Report bindings before filtering names or offering interactive choices. The app delegates its existing selection/evidence wrapper to the same helper. Exact Python `report_paths` remains the diagnostic override; `clean-stale --all-reports` remains unchanged.
- Missing, malformed, remote/unrelated, and ambiguous dual-form bindings are excluded with identities and messages. The bundled Microsoft definitionProperties schema specifies exactly one of `byPath` or `byConnection`; supported local bindings and existing published-name live matching retain their meaning.
- Ordinary JSON adds `reportBinding`; check binding rows add messages and survive invalid/empty scope; plan command summaries/errors add binding evidence without changing saved-plan digests. Exclusions and interactive prompts use stderr. Scan coverage, Analysis Limitations, classification rules, and finding fingerprints are unchanged.
- Seven new cross-entrypoint regressions cover selected identities, reference counts, unrelated-only usage, empty/name/interactive selection, strict explicit refactoring rejection, clean JSON stdout, and export protection for excluded Reports.
- Legacy metadata tests now build valid local bindings (including three static fixtures), retaining implicit-discovery coverage. Only the intentionally invalid-definition diagnostic uses explicit Report paths.
- Windows Python 3.13 with `PYTHONUTF8=0`: full `pytest -q --tb=short` — **829 passed, 8 skipped** in 79.83 seconds. `ruff check src tests` and `git diff --check` passed. No public release, remote writes, or real project mutation.
- Remaining integration review should combine the shared web helper change with R03's independent HTTP boundary changes. Packaged acceptance remains R10.

## Out of scope

Service-wide Report discovery, automatically claiming all external consumers were checked, or changing report-issue grouping decisions.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

