# R08 Make analysis results explain coverage and the next Cleanup Action

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: HITL — a human design or acceptance checkpoint is required.
Priority: Launch target; reduce scope if release gates need time.

## User story

As a Power BI developer, I can understand what was checked and why an item has a Cleanup Recommendation before preparing a change.

## What to build

Improve the existing result entry point and item explanation. Present selected scope, limitations, cleanup candidates, and Report Health distinctly, with a clear route to supporting evidence and an exact change preview. Retain canonical Safe, Review, and other existing semantics, explaining their limits in plain language.

## Acceptance criteria

- [ ] Capture the current analyzed UI and review the intended hierarchy before changing it.
- [ ] The result entry point identifies the selected Semantic Model, checked Reports, and material coverage limitations.
- [ ] A user can distinguish found usage, Cleanup Recommendation, and Report Health without interpreting color alone.
- [ ] Safe is visibly defined relative to supported scanned metadata and selected scope; no copy promises universal deletion safety or runtime equivalence.
- [ ] A user can open one candidate, inspect dependency/evidence details, prepare a change, and locate Changes & history.
- [ ] Report issue grouping remains presentation-only under the accepted ADR; no inferred rename or group repair is introduced.
- [ ] Human review covers normal results, incomplete coverage, no candidates, and a project with broken references.

## Blocked by

- [R04: Use consistent connected Report selection across analysis and automation](r04-consistent-report-scope.md)
- [R07: Give Windows users a clear first analysis path](r07-first-run.md)

## Verification

Use the bundled demo and richer synthetic QA project. Capture scope/result/item/preview states and verify that classifications and mutation permissions have not changed.

## Out of scope

Changing analysis rules, renaming canonical domain concepts without a separate decision, or implementing automatic broken-reference repair.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

