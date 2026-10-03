# R09 Make the core desktop flow keyboard accessible and readable

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: HITL — a human design or acceptance checkpoint is required.
Priority: Release gate for keyboard access and core-flow readability.

## User story

As a Windows user at normal or enlarged display scaling, I can complete analysis and reviewed changes with the keyboard and read the evidence comfortably.

## What to build

Finish focused usability and visual verification of the settled flow, especially scope selection and nested dialogs. Reuse the existing native change-review dialog pattern where appropriate. Improve small/faint essential text and stable offline font rendering without redesigning the app.

## Evidence

The scope drawer open/close functions only toggle a body class; its markup is an offscreen aside. The template uses small supporting text, faint colors, and external Google Fonts. These are code findings; rendered behavior requires verification.

## Acceptance criteria

- [ ] Closed drawer/modal controls are not keyboard focus targets; opening moves focus appropriately, modal focus is contained, and closing restores it.
- [ ] Escape closes the topmost applicable layer without accidentally dismissing underlying work; controls have useful accessible names.
- [ ] Keyboard users can open a project/demo, analyze, inspect evidence, review/apply a disposable change, and reach recovery.
- [ ] Essential text, labels, focus indicators, and statuses have measured adequate contrast; color is not the only signal.
- [ ] Check at representative 1280x800 and 1366x768 laptop viewports, browser zoom, and actual Windows 125/150 percent display scaling where available; no core controls become unreachable.
- [ ] Offline startup remains usable with intentional typography; if fonts are bundled, preserve license notices.
- [ ] Save current screenshots and keyboard/scale observations for human acceptance, explicitly separating tested behavior from remaining screen-reader or OS-scaling gaps.

## Blocked by

- [R07: Give Windows users a clear first analysis path](r07-first-run.md)
- [R08: Make analysis results explain coverage and the next Cleanup Action](r08-result-clarity.md)

## Verification

Walk through the full core flow with keyboard only on synthetic data. Measure relevant colors and inspect screenshots at the specified sizes; don't substitute CSS viewport changes for OS scaling evidence.

## Out of scope

A full accessibility certification, dark mode, mobile redesign, or new theme system.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

