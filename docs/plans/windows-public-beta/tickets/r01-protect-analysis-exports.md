# R01 Protect Semantic Model and Report files from analysis exports

Status: Implemented on 2026-10-03 in `codex/r01-protect-exports`; ready for integration review. Local ticket, not a published GitHub issue.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Power BI developer, I can export analysis without accidentally replacing my project metadata.

## What to build

Protect every ordinary analyzer export format, including default Excel destinations, from writing inside discovered or selected Semantic Model and Report artifacts. Apply the rule to explicit paths, excluded artifacts, and resolved aliases. Preserve normal exports to an external directory.

## Evidence

On a disposable bundled-demo copy, JSON export to the existing Sales.tmdl source returned success and replaced TMDL with JSON. Saved-plan and baseline outputs already have stronger boundaries.

## Acceptance criteria

- [x] Text, JSON, and Excel exports reject destinations inside selected or discovered artifacts before writing; rejection preserves all original bytes and creates no recovery receipt.
- [x] Default Excel output is also protected when the current directory is inside an artifact.
- [x] Symlink/junction aliases cannot bypass protection; address hard-linked output files explicitly without weakening normal exports. Windows junction and hard-link cases passed; symbolic-link runtime checks remain skipped on this account (see below).
- [x] External output directories still work, including Windows paths with spaces and non-ASCII characters.
- [x] The error explains how to choose a valid destination and returns a nonzero input-error exit status.
- [x] Regression checks run only on disposable synthetic projects and cover at least selected model, selected report, excluded artifact, and external success.

## Blocked by

None — can start immediately.

## Verification

Reproduce the original JSON overwrite attempt on a copy and compare a full byte snapshot before/after. Exercise each supported output format and supported filesystem alias mechanism.

### Implementation evidence — 2026-10-03

- Reproduced the original JSON overwrite and a text overwrite against synthetic `Sales.tmdl` before the fix: both returned success rather than an input error.
- The analyzer retains discovery results before selection filters and validates explicit/default export destinations before analysis. Resolved destinations inside selected/discovered artifacts and named artifact folders are refused with exit code 2.
- Existing multiply-linked output files are refused because a hard link may alias metadata outside the selected scope. Ordinary external files can still be replaced; new external paths, non-ASCII directory names, and parent traversal out of an artifact work.
- Added `tests/test_analysis_exports.py`: full file-byte/directory snapshots cover every format, selected and excluded artifacts, existing/new destinations, default Excel paths, explicit artifact roots, Windows junctions, hard links, and normal external exports. An excluded discovered Report junction also protects its unnamed target directory.
- After integrating the updated beta3 source and Windows portability fix (`4631a9e`), ran `python -m pytest tests/test_analysis_exports.py tests/test_clean_stale_cli.py tests/test_analyze_model_usage.py -q`: **112 passed, 2 skipped**. The two skips are file/directory symbolic-link creation, unavailable under this Windows account's privileges; junction and hard-link checks passed. These symbolic-link tests remain runnable on Linux or Windows with symlink privileges.
- Ran Ruff on the changed Python files: **passed**. Used the shared virtual environment with `PYTHONPATH` set to this worktree's `src`; no real Power BI Projects were mutated.
- Remaining validation: integration review and symbolic-link execution in a capable environment. No cleanup writers, analysis semantics, recovery machinery, or format contents changed.

## Out of scope

Changing cleanup writers, adding backups to analysis, or redesigning export formats.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

