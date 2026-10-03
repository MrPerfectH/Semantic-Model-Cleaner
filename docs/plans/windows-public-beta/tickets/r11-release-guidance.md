# R11 Make the Windows download and public guidance match the candidate

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: HITL — a human design or acceptance checkpoint is required.
Priority: Release gate for accurate guidance; promotional polish is optional.

## User story

As a new Power BI developer, I can find the correct Windows download, understand supported inputs, and get useful help without installing Python.

## What to build

Align the landing page, quick start, release notes, and support guidance with the candidate and the Windows-first audience. Present one recommended public beta download, a short supported-input explanation, and a real product demonstration. Keep CLI guidance as a supported secondary workflow.

## Acceptance criteria

- [ ] The primary download clearly identifies the actual public beta version and links to its checksum; no stable-release recommendation contradicts available releases.
- [ ] Windows guidance covers complete ZIP extraction, unsigned-package expectations, launch, demo, supported PBIR/TMDL input, and recovery.
- [ ] PBIX-only users receive accurate guidance for obtaining supported project formats; no binary import support is implied.
- [ ] Use screenshots of the final candidate flow, labeled to match the UI; no placeholder or stale screenshots are presented as current.
- [ ] CLI examples use verified commands from R06 and link to a concise automation workflow.
- [ ] Support instructions request version, scope, errors, and synthetic reproductions while warning users not to publish private metadata.
- [ ] Validate candidate links/assets and obtain human review of public wording; record links that cannot be verified until publication.

## Blocked by

- [R06: Make the existing CLI discoverable and predictable for automation](r06-cli-discovery-and-errors.md)
- [R09: Make the core desktop flow keyboard accessible and readable](r09-keyboard-and-visual-polish.md)

## Verification

Follow the instructions as a first-time Windows user and check every local documentation link. Compare public claims with the support matrix and candidate screenshots.

## Out of scope

Publishing a website, announcing to communities, buying code signing, or inventing performance/storage savings.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

