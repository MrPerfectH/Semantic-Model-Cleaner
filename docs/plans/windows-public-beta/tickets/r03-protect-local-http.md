# R03 Protect local file operations from foreign browser requests

Status: Implemented, reviewed and integrated as `e40a046`; automated verification complete, rendered-browser acceptance pending. Local ticket, not a published GitHub issue.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a desktop user, opening another website cannot authorize changes to my local Power BI Project.

## What to build

Protect the local HTTP surface with trusted-host validation and a tested browser request boundary. Use a per-launch token or a documented equivalent that blocks cross-origin/simple-form mutations and unsafe embedding. Audit every state-changing route, including demo setup, plans, restore, review policy, and cancellation. Update both layouts, launcher behavior, and smoke clients together.

## Evidence

The Flask test client received directory information for an unrelated Host and Origin. A form POST with a cross-site Origin applied a known disposable saved plan. These reproduce missing application checks; a complete browser exploit was not demonstrated.

## Acceptance criteria

- [x] Untrusted Host values cannot access filesystem or plan APIs; reject cross-origin and null-origin browser mutation attempts before route side effects.
- [x] Simple form submissions and requests missing whatever protection the chosen design requires cannot apply, restore, or modify local files.
- [ ] Both supported layouts can still discover, demo, analyze/cancel, export, prepare, apply, verify, restore, and save review decisions through legitimate requests. Authenticated route round trips, shared JavaScript, cancellation and review-policy tests pass; complete rendered-browser acceptance remains pending.
- [x] CLI file-based commands continue working without a browser session.
- [x] Remote binding is either rejected for this local-only beta or protected by an explicit reviewed access design; remove the unqualified 0.0.0.0 quick-start example.
- [x] Add negative tests for Host, Origin, browser fetch metadata, form content types, and absent/invalid tokens if used; positive tests cover normal UI requests.
- [x] Document the chosen boundary, browser assumptions, and compatibility for local scripted HTTP clients; keep secrets out of logs and URLs.

## Blocked by

None — can start immediately.

## Verification

Repeat the audit probes against disposable plans and confirm unchanged source bytes. Exercise both layouts and the packaged smoke client's legitimate request path; use the real browser when available.

### Implementation evidence — 2026-10-03

- Reproduced both audited failures before the fix using disposable data: unrelated Host/Origin browsing returned 200, and a foreign-origin form submission applied a saved plan with 200.
- Added a central request boundary in `local_http.py`: exact trusted Hosts, loopback peers, exact Origin including port, browser Fetch Metadata checks, per-launch token for every API route (including state-changing GET discovery), and JSON-only mutation requests. `/api/session` is the same-origin bootstrap; foreign hosts, origins, null origins, embeddings, and preflights cannot obtain it. Responses prohibit framing and cross-origin inclusion and keep HTML/API responses out of caches.
- Both layouts and shared analysis, classic-plan, and review-policy JavaScript send the token through `local-http.js`. Exports use authenticated fetch/blob downloads; tokens never enter download URLs. Launchers reject remote binding before runtime setup. Updated README and [HTTP client/boundary documentation](../../../local-http-security.md).
- `tests/test_local_http_security.py` exercises every mutation route before dispatch, hostile headers, missing/invalid tokens, simple-form types, token rotation, launcher arguments, and both layouts' HTML bootstrap plus actual demo/analyze/export/plan/apply/verify/restore route round trips. Snapshots confirm rejected operations preserve bytes and successful restore recovers original bytes. Authenticated cancellation is also exercised.
- `tests/test_local_http_client.py` executes the shared JavaScript in Node and verifies token headers, rejection of foreign origins/ports, bodyless DELETE headers, and blob downloads. Existing classic-plan and review-policy tests exercise legitimate protected calls.
- Updated wheel and Windows package smoke clients. `test_packaged_http_client_bootstraps_and_calls_protected_api` ran the Windows smoke client's actual urllib bootstrap and protected demo/history calls against a real loopback HTTP server.
- Full Windows suite on the R01/R02-integrated base `30ecdba` plus R03: **965 passed, 8 skipped in 81.81 seconds**. Ruff on source, tests, and changed smoke scripts: **passed**. Existing CLI tests passed without browser credentials. All destructive tests use disposable projects/user-state directories.
- Merged the R04-integrated branch at `9a132ae` without conflicts, then reran the shared HTTP security/client, package-client, app API, analysis-jobs, classic-plan, review-policy, connected-scope, CI-check, and clean-stale suites: **278 passed, 1 skipped in 16.75 seconds**. Ruff and `git diff --check` passed after integration.
- Validation limit: these are Flask route, real HTTP-client, and Node checks. T3's shared preview cannot reach the Windows loopback app in this session; no complete real-browser walkthrough or rebuilt Windows-package acceptance is claimed. Those checks remain pending for integration/R10.

## Local browser follow-up on MSI

The user authorized local browser automation. On source revision `7c145f3`, local Edge on MSI Summit E15 A11SCST completed the classic-layout demo/analyze, authenticated JSON/Excel downloads, reviewed Hide/apply, history verification, review/restore, and policy-decision save. All ten original project files restored byte-for-byte; policy save preserved their bytes; no page errors occurred. See [captures and exact limits](../../../audits/windows-ui-2026-10-03/r03-classic/README.md). Current v2 lifecycle, rendered cancellation, and rebuilt-package acceptance remain pending.

## Out of scope

Cloud authentication, user accounts, hosted multi-user access, or publishing exploit details.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

