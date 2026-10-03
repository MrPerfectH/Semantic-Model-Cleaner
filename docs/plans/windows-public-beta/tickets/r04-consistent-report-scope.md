# R04 Use consistent connected Report selection across analysis and automation

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Power BI developer, I get consistent usage evidence from the app and CLI for the same Semantic Model and Reports.

## What to build

Align ordinary analyzer discovery with the connected-report selection already used by the UI, check, and reviewed-plan workflows. Show exclusions and selection limits without contaminating machine-readable stdout. Retain documented explicit diagnostic overrides only where they already exist, clearly distinguished from normal selection.

## Evidence

A synthetic Unrelated.Report bound to Different.SemanticModel appeared in ordinary analyzer output, while smc check correctly excluded it as not_connected.

## Acceptance criteria

- [ ] For equivalent default scope, UI, ordinary CLI, check, and plan choose the same supported bound Reports.
- [ ] A Report bound to another Semantic Model contributes no usage references under default selection.
- [ ] Missing, malformed, ambiguous, local, and supported live-connection bindings receive consistent treatment and visible evidence.
- [ ] Name filters and interactive selection operate on the eligible connected set; an unmatched/empty selection fails clearly.
- [ ] Explicit Report paths in reviewed workflows do not silently authorize unrelated or unverified scope; preserve any stricter mutation checks.
- [ ] Machine-readable output remains parseable and identifies selected scope or documents where exclusions are reported.
- [ ] Regression fixtures compare reference counts and selected identities across entry points without changing the underlying dependency/classification semantics.

## Blocked by

None — can start immediately.

## Verification

Use a synthetic project with one connected Report, one unrelated Report, and invalid binding cases. Compare CLI/UI scope and ensure an unrelated reference cannot change a Cleanup Recommendation.

## Out of scope

Service-wide Report discovery, automatically claiming all external consumers were checked, or changing report-issue grouping decisions.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

