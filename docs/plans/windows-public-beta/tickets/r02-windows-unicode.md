# R02 Preserve Unicode through Windows startup and reviewed CLI changes

Status: Implemented and locally verified on 2026-10-03 in `codex/r02-windows-unicode`; awaiting integration review. Local ticket, not a published GitHub issue.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Windows user, I can launch the app and use non-English names without crashes or silent corruption.

## What to build

Make input and output encodings explicit across supported Windows entry points and user-authored operations JSON. Define UTF-8/BOM handling for JSON separately from the existing restriction on BOM-prefixed TMDL writes. Keep the desktop launcher's working behavior covered.

## Evidence

A UTF-8 operations file requesting display folder Zażółć produced a successful plan with corrupted text when Python UTF-8 mode was disabled. The Python web command also crashed printing its Unicode banner to cp1252 stdout; desktop launcher behavior differs.

## Acceptance criteria

- [x] UTF-8 operations JSON preserves Polish characters, accented text, and a non-BMP character through plan, diff, apply, verify, and byte-exact restore.
- [x] A documented JSON BOM policy is implemented and tested; it does not enable unsupported TMDL writes.
- [x] Malformed encodings fail with an actionable error and no source writes.
- [x] CLI, web, and desktop startup work with redirected stdout/stderr without requiring PYTHONUTF8 or a console-code-page change.
- [x] Machine-readable JSON remains valid when output is redirected; non-BMP characters do not become invalid JSON escapes.
- [x] Tests exercise a non-UTF-8 default environment and Windows paths containing spaces/non-ASCII characters.

## Blocked by

None — can start immediately.

## Verification

Run the operation workflow in a subprocess with UTF-8 mode disabled and a deliberate non-UTF-8 stdio setup. Parse output bytes using the documented encoding and compare original/recovered metadata bytes.

### Implementation evidence (2026-10-03)

- Baseline: integration revision `4631a9e`, containing beta3 and the existing Windows fixes from `d373113`. Reused those explicit UTF-8 file reads/writes and web/desktop startup fixes.
- New subprocess tests reproduced five remaining failures on that baseline: CLI diff and JSON stdout encoding failures, rejected UTF-8 BOM operations, and two malformed-encoding cases without actionable file-specific guidance.
- Extracted the existing console setup into a lightweight shared module and applied it to CLI dispatch and the legacy analyzer entry point. Desktop retains its buffering setup and the web helper remains import-compatible.
- Operations accept UTF-8 with an optional BOM, report decoding failures with the filename and save-as-UTF-8 guidance, and leave source/output files untouched on failure. The JSON and output encoding contract is documented in `docs/cli/plans.md`.
- Windows Python 3.13, `PYTHONUTF8=0`: `pytest tests/test_windows_unicode.py tests/test_windows_launcher.py tests/test_bom_plan_boundary.py tests/test_change_plans.py -q` — **36 passed, 1 skipped** (existing POSIX permission-bit test). `ruff check src tests` passed.
- The new tests force `PYTHONIOENCODING=cp1252:strict` in child processes, verify UTF-8 mode is disabled, and run in paths containing spaces, Polish/accented characters, and a non-BMP rocket. Both UTF-8 operations variants pass plan/diff/apply/verify/history/restore with byte-exact recovery. Ordinary JSON output and the legacy script output parse correctly.
- Web and desktop startup exercise real argument parsing, runtime configuration, and banners in subprocesses; only long-running server/browser boundaries are replaced. Packaged EXE and clean-machine acceptance remain R10 work.

## Out of scope

General localization, translating labels, or removing the beta TMDL BOM restriction.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

