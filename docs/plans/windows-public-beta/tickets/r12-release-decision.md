# R12 Record the release candidate decision and remaining limitations

Status (2026-10-05): Delegated engineering decision: recommend scoped beta4; publication remains a separate action. Independent-user research is explicitly deferred. [Final evidence](../../../audits/windows-ui-2026-10-05/R12.md). Local ticket, not a published GitHub issue.
Type: Originally HITL. The user delegated routine verification/review to the agent on 2026-10-05; independent-user and environment evidence remain separate requirements.
Priority: Release gate.

## User story

As the maintainer, I can make a release decision using verified evidence and a clear list of remaining limitations.

## What to build

Assemble the final candidate evidence, ticket dispositions, known limitations, and fallback scope. Give the maintainer a concrete go/no-go review; the ticket does not authorize publication.

## Acceptance criteria

- [x] Technical release-gate acceptance is complete; research/distribution limitations are explicit and no unresolved file-safety issue is waived.
- [x] Record source revision, candidate artifact hashes, Windows and Linux checks, package/browser evidence, and manual Power BI acceptance.
- [x] Label each deferred target as deferred, with a reason and follow-up; dependencies are revisited rather than silently skipped.
- [x] Verify the selected audience, supported formats, Unicode/BOM restrictions, dynamic-metadata limits, unsigned packaging, and recovery behavior are accurately described.
- [ ] Deferred research: independent first-use walkthrough (0 participants). The user delegated routine verification; automated first-use, scope, finding and recovery checks pass but are not an independent usability study.
- [x] Provide a go/no-go recommendation and, if needed, an explicit analysis-only or delayed-launch fallback.
- [x] Record the delegated release decision (scoped beta recommended). Tagging, uploading, deployment, announcements, or other publication require a separate explicit instruction.

## Blocked by

- [R10: Verify the actual Windows release package and recovery workflow](r10-windows-release-verification.md)
- [R11: Make the Windows download and public guidance match the candidate](r11-release-guidance.md)

## Verification

Review actual evidence links and artifact identity, not just green task statuses. Record untested conditions and who supplied manual acceptance.

## Out of scope

Automatic publication, closing unrelated existing issues, or claiming product readiness based solely on unit tests.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

