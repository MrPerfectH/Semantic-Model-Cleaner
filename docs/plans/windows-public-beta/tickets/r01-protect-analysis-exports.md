# R01 Protect Semantic Model and Report files from analysis exports

Status: Ordinary exports integrated in `c57f771`; plan/baseline alias follow-up implemented and locally verified in `codex/r01-output-alias-followup`, awaiting integration review. Local ticket, not a published GitHub issue.
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

## Integration follow-up: plan and baseline aliases

On integration revision `40275a4`, disposable demo probes showed that an external hard link to `Sales.tmdl` bypasses the separate plan/baseline output guards. `plan -o` returned 0 and overwrote the linked source; `check --write-baseline` returned the normal findings status 1 and also overwrote it. The ordinary analyzer guard correctly rejects this case.

Keep this fix under R01: apply consistent alias/hard-link protection to these existing metadata-export destinations, preserve the plan command's supported creation of external parent directories, and preserve its prohibition on replacing the operations input. Check safety before creating output directories or writing files. Regression evidence must compare source/input bytes and show normal external outputs still work. This follow-up does not change plan digests, cleanup writers, or release-ticket ordering.

### Follow-up evidence (2026-10-03)

- On starting revision `4721240`, 10 regression cases failed: hard-linked outputs to selected/excluded Semantic Model and Report metadata were overwritten by both commands; plan output also created a named but undiscovered Report directory and could overwrite a hard-link alias of operations JSON. Thirteen existing-safe and external-success cases passed.
- Both plan and baseline outputs now use the shared export boundary. It rejects resolved artifact aliases and multiply-linked destinations, including excluded artifacts and named artifact folders. Plan validates before staged generation or parent creation and retains operations-input protection. It alone opts into missing external parent directories; baseline/ordinary exports still require an existing parent.
- Normal external overwrites and nested external plan destinations work. Error wording now refers to export output so it applies to all three callers; invalid destinations return input-error status 2 without source/input changes. Saved-plan digests and finding fingerprints are unchanged.
- `pytest tests/test_automation_export_safety.py tests/test_analysis_exports.py tests/test_ci_check.py tests/test_change_plans.py tests/test_plan_write_boundaries.py tests/test_plan_review_regressions.py tests/test_connected_scope_entrypoints.py -q --tb=short` under Windows Python 3.13 with `PYTHONUTF8=0`: **172 passed, 4 skipped** in 21.01 seconds. Skips are existing symbolic-link privilege and POSIX-permission checks; hard links and junctions passed.
- All **23** new automation-export cases pass, including byte/directory snapshots on refusal, operations hard links, normal existing external output, and missing-parent plan output. `ruff check src tests` and `git diff --check` pass.
- Merged integration revision `e40a046` (R03 authenticated Flask boundary) and reran the affected command above: **172 passed, 4 skipped** in 20.05 seconds. Ruff passed on the combined sources/tests.
- CLI discovery review found the same boundary gap in `naming preview -o`. Its two new hard-link regressions first reproduced overwrites of model metadata and policy JSON. Naming plan exports now share the validator while preserving their output shape, policy-input protection, and external parent creation. `pytest tests/test_review_policy.py tests/test_automation_export_safety.py -q --tb=short`: **40 passed**; targeted Ruff passed. This companion fix is separate from R06's CLI contract work.

## Out of scope

Changing cleanup writers, adding backups to analysis, or redesigning export formats.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

