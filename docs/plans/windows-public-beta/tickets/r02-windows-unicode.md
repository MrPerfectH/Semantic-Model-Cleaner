# R02 Preserve Unicode through Windows startup and reviewed CLI changes

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Windows user, I can launch the app and use non-English names without crashes or silent corruption.

## What to build

Make input and output encodings explicit across supported Windows entry points and user-authored operations JSON. Define UTF-8/BOM handling for JSON separately from the existing restriction on BOM-prefixed TMDL writes. Keep the desktop launcher's working behavior covered.

## Evidence

A UTF-8 operations file requesting display folder Zażółć produced a successful plan with corrupted text when Python UTF-8 mode was disabled. The Python web command also crashed printing its Unicode banner to cp1252 stdout; desktop launcher behavior differs.

## Acceptance criteria

- [ ] UTF-8 operations JSON preserves Polish characters, accented text, and a non-BMP character through plan, diff, apply, verify, and byte-exact restore.
- [ ] A documented JSON BOM policy is implemented and tested; it does not enable unsupported TMDL writes.
- [ ] Malformed encodings fail with an actionable error and no source writes.
- [ ] CLI, web, and desktop startup work with redirected stdout/stderr without requiring PYTHONUTF8 or a console-code-page change.
- [ ] Machine-readable JSON remains valid when output is redirected; non-BMP characters do not become invalid JSON escapes.
- [ ] Tests exercise a non-UTF-8 default environment and Windows paths containing spaces/non-ASCII characters.

## Blocked by

None — can start immediately.

## Verification

Run the operation workflow in a subprocess with UTF-8 mode disabled and a deliberate non-UTF-8 stdio setup. Parse output bytes using the documented encoding and compare original/recovered metadata bytes.

## Out of scope

General localization, translating labels, or removing the beta TMDL BOM restriction.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

