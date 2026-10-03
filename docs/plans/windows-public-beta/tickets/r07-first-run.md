# R07 Give Windows users a clear first analysis path

Status: Implemented on 2026-10-03 in `codex/r07-first-run`, based on `7c145f3` with R01–R06 integrated. Source-browser verification passed; human review and packaged-UI acceptance remain pending. Local ticket, not a published GitHub issue.
Type: HITL — a human design or acceptance checkpoint is required.
Priority: Launch target; reduce scope if release gates need time.

## User story

As a first-time Windows user, I can try a demo or open a Power BI Project and understand the analysis scope without reading setup documentation.

## What to build

Improve the existing first-run flow with visible Open Power BI Project and Try demo choices. Reuse discovery to propose one Semantic Model and connected Reports, expose exclusions before analysis, and retain manual selection for ambiguity and separate roots. Preserve the existing visual language.

## Evidence

Code inspection shows the scope drawer opens automatically before analysis, the demo is inside setup, and the welcome card separately asks for folder selection. The original audit could not access a live browser, so capture the current flow before finalizing UI changes.

## Acceptance criteria

- [x] Capture and review the actual current first-run flow before implementation; record any browser-access blocker rather than inventing visual findings.
- [x] A user can enter the disposable demo without supplying project paths.
- [x] Project selection proposes a clear model/report scope and asks for a choice when multiple Semantic Models exist.
- [x] Selected and excluded Reports and incomplete coverage are understandable before Analyze; invalid/PBIX-only folders receive actionable guidance.
- [x] Cancellation and errors preserve a usable setup state; users with separate model/report roots retain a manual path.
- [ ] Complete demo/open -> review scope -> analyze in the packaged UI and capture the result at a common Windows laptop size.
- [ ] Human review confirms the flow is understandable and visually consistent; no original project is modified during setup.

## Blocked by

- [R03: Protect local file operations from foreign browser requests](r03-protect-local-http.md)
- [R04: Use consistent connected Report selection across analysis and automation](r04-consistent-report-scope.md)

## Verification

Run fresh-profile walkthroughs for demo, one-model project, ambiguous models, invalid folder, and separate roots. Obtain user review of the captured flow.

## Out of scope

New dependency inference, drag-and-drop binaries, a complete redesign, or adding cloud selection.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.


## Implementation and verification — 2026-10-03

The user authorized local Edge automation on the verified MSI laptop. Current UI was captured before source changes; the integrator reviewed it and approved the scoped proposal. Both layouts now offer project/demo entry, explicit model choice for ambiguity, and connected/excluded Report review before Analyze. Manual separate-root selection is retained. Invalid/PBIX-only folders, browser errors, cancellation and retry keep setup usable. Older discovery/demo responses cannot overwrite newer selections.

See [R07 browser evidence and captures](../../../audits/windows-ui-2026-10-03/R07.md). Ten fresh-context walkthroughs passed (five required paths in each layout), plus held-response race checks. No JavaScript page errors; synthetic source-file hashes unchanged. Backend full suite: **1020 passed, 8 skipped**; Ruff and diff whitespace checks passed. No cleanup classification or Report binding rules changed.

Demo API behavior is unchanged; browser harnesses must now click Analyze explicitly after loading the demo. The existing packaging API smoke remains compatible.

**Pending:** human clarity/visual review and demo/open → scope → analysis in the actual Windows package. Automated source UI evidence does not close either gate. R08 result presentation and R09 broader keyboard/scaling review remain separate tickets.
