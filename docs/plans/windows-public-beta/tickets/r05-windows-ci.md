# R05 Run the full unit suite on Windows with portable fixtures

Status: Existing implementation reused as `4631a9e`; R02 integrated as `30ecdba`. Full local Windows validation passed after R04; remote CI remains pending. Local ticket, not a published GitHub issue.
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
- [x] Source fixtures and JavaScript files are read with explicit encodings where applicable.
- [x] Logical path comparisons work on Windows and POSIX without hiding real path-identity bugs.
- [ ] Symlink tests use capability-aware skips only when the platform cannot create the link, and still run in a CI environment that supports it.
- [x] The normal Windows test run passes without globally enabling UTF-8 mode to hide the original regressions.
- [ ] Ruff and packaging/wheel checks continue running on their intended platforms; shell/glob behavior works in each lane.
- [x] Record the Python/OS matrix and distinguish executed checks from remote CI checks not yet run.

## Blocked by

- [R02: Preserve Unicode through Windows startup and reviewed CLI changes](r02-windows-unicode.md)

## Verification

Run the full local Windows suite and lint. Review or execute the Linux/Windows CI matrix when available, preserving evidence for any capability skips.

## Implementation evidence (2026-10-03)

Reused existing commit `d373113` rather than duplicating its Windows portability fixes. `.github/workflows/ci.yml` retains Ubuntu Python 3.11/3.13 and adds Windows Python 3.13, with lint and the complete unit suite. Ubuntu 3.11 retains distribution build and installed-wheel smoke checks. The separate Windows ZIP build/download/verification workflow is preserved.

Fixture reads are explicit UTF-8; path comparisons use platform paths; symlink tests skip when creation is unavailable. The integration baseline passed **766 tests with 6 platform/privilege skips**. After R01/R02, with `PYTHONUTF8=0`, the full suite had **821 passes, 8 skips, and one three-second asynchronous job timeout**. All five job tests passed on focused rerun. Ruff passed. Remote Linux/Windows lanes and capable-environment symlink execution have not run in this session. A final combined suite remains required after integration.

After R04, full Windows Python 3.13 validation with `PYTHONUTF8=0` passed: **829 passed, 8 skipped** in 79.83 seconds on `1a02dd5`, integrated as `4721240`. The job timeout did not recur. This confirms local unit behavior; remote CI, wheel and packaged-EXE checks remain separate evidence.

## Out of scope

Replacing the test framework, weakening writer safety tests, or claiming packaged EXE coverage from unit tests.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

