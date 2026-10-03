# R05 Run the full unit suite on Windows with portable fixtures

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a maintainer, I see Windows regressions before distributing a Windows release.

## What to build

Add a Windows unit-test lane alongside Linux and repair the audited portability failures without suppressing genuine product regressions. Preserve the separate downloaded-package verification workflow.

## Evidence

The audited Windows run had 694 passing, 13 failing, and 4 skipped tests. UTF-8 mode resolved nine test decoding failures; four remained due to POSIX path assumptions or missing Windows symlink privileges.

## Acceptance criteria

- [ ] The existing Linux coverage remains and at least one supported Python version runs the complete suite on Windows.
- [ ] Source fixtures and JavaScript files are read with explicit encodings where applicable.
- [ ] Logical path comparisons work on Windows and POSIX without hiding real path-identity bugs.
- [ ] Symlink tests use capability-aware skips only when the platform cannot create the link, and still run in a CI environment that supports it.
- [ ] The normal Windows test run passes without globally enabling UTF-8 mode to hide the original regressions.
- [ ] Ruff and packaging/wheel checks continue running on their intended platforms; shell/glob behavior works in each lane.
- [ ] Record the Python/OS matrix and distinguish executed checks from remote CI checks not yet run.

## Blocked by

- [R02: Preserve Unicode through Windows startup and reviewed CLI changes](r02-windows-unicode.md)

## Verification

Run the full local Windows suite and lint. Review or execute the Linux/Windows CI matrix when available, preserving evidence for any capability skips.

## Out of scope

Replacing the test framework, weakening writer safety tests, or claiming packaged EXE coverage from unit tests.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

