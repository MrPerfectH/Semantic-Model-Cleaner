# R12 Record the release candidate decision and remaining limitations

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: HITL — a human design or acceptance checkpoint is required.
Priority: Release gate.

## User story

As the maintainer, I can make a release decision using verified evidence and a clear list of remaining limitations.

## What to build

Assemble the final candidate evidence, ticket dispositions, known limitations, and fallback scope. Give the maintainer a concrete go/no-go review; the ticket does not authorize publication.

## Acceptance criteria

- [ ] All release-gate acceptance criteria are complete or the release is explicitly blocked; no unresolved file-safety issue is waived silently.
- [ ] Record source revision, candidate artifact hashes, Windows and Linux checks, package/browser evidence, and manual Power BI acceptance.
- [ ] Label each deferred target as deferred, with a reason and follow-up; dependencies are revisited rather than silently skipped.
- [ ] Verify the selected audience, supported formats, Unicode/BOM restrictions, dynamic-metadata limits, unsigned packaging, and recovery behavior are accurately described.
- [ ] A small fresh-user walkthrough confirms users can locate demo/open, understand scope, inspect one finding, and find recovery; report sample size and limitations.
- [ ] Provide a go/no-go recommendation and, if needed, an explicit analysis-only or delayed-launch fallback.
- [ ] Obtain the maintainer's release decision. Tagging, uploading, deployment, announcements, or other publication require a separate explicit instruction.

## Blocked by

- [R10: Verify the actual Windows release package and recovery workflow](r10-windows-release-verification.md)
- [R11: Make the Windows download and public guidance match the candidate](r11-release-guidance.md)

## Verification

Review actual evidence links and artifact identity, not just green task statuses. Record untested conditions and who supplied manual acceptance.

## Out of scope

Automatic publication, closing unrelated existing issues, or claiming product readiness based solely on unit tests.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

