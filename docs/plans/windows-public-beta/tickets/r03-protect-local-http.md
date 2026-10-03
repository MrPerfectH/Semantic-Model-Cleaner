# R03 Protect local file operations from foreign browser requests

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a desktop user, opening another website cannot authorize changes to my local Power BI Project.

## What to build

Protect the local HTTP surface with trusted-host validation and a tested browser request boundary. Use a per-launch token or a documented equivalent that blocks cross-origin/simple-form mutations and unsafe embedding. Audit every state-changing route, including demo setup, plans, restore, review policy, and cancellation. Update both layouts, launcher behavior, and smoke clients together.

## Evidence

The Flask test client received directory information for an unrelated Host and Origin. A form POST with a cross-site Origin applied a known disposable saved plan. These reproduce missing application checks; a complete browser exploit was not demonstrated.

## Acceptance criteria

- [ ] Untrusted Host values cannot access filesystem or plan APIs; reject cross-origin and null-origin browser mutation attempts before route side effects.
- [ ] Simple form submissions and requests missing whatever protection the chosen design requires cannot apply, restore, or modify local files.
- [ ] Both supported layouts can still discover, demo, analyze/cancel, export, prepare, apply, verify, restore, and save review decisions through legitimate requests.
- [ ] CLI file-based commands continue working without a browser session.
- [ ] Remote binding is either rejected for this local-only beta or protected by an explicit reviewed access design; remove the unqualified 0.0.0.0 quick-start example.
- [ ] Add negative tests for Host, Origin, browser fetch metadata, form content types, and absent/invalid tokens if used; positive tests cover normal UI requests.
- [ ] Document the chosen boundary, browser assumptions, and compatibility for local scripted HTTP clients; keep secrets out of logs and URLs.

## Blocked by

None — can start immediately.

## Verification

Repeat the audit probes against disposable plans and confirm unchanged source bytes. Exercise both layouts and the packaged smoke client's legitimate request path; use the real browser when available.

## Out of scope

Cloud authentication, user accounts, hosted multi-user access, or publishing exploit details.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

