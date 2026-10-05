# Windows public beta session execution

The user authorized execution on 2026-10-03. Work is isolated from the original checkout and existing `.claude` worktrees. No release has been published.

Integration worktree: `C:/Users/PrzemekHarazny/Projects/smc-windows-beta-integration` on `codex/windows-beta-integration`.

The original checkout was at `6d29ce2`, six commits behind local `origin/main`. Integration includes the newer `d5a4be7` beta3 baseline and the existing Windows portability commit `d373113`, reused as `4631a9e` after review. Its local full-suite verification passed: **766 passed, 6 skipped** in 80.39 seconds. Remote CI and the packaged EXE are not established by this result.

| Ticket | Session branch | State |
| --- | --- | --- |
| R01 | `codex/r01-protect-exports`; `codex/r01-output-alias-followup` | Integrated ordinary exports (`c57f771`), plan/baseline aliases (`2777546`) and naming exports (`6e6ace9`) |
| R02 | `codex/r02-windows-unicode` | Integrated in `30ecdba`; Unicode lifecycle and malformed-input checks verified |
| R03 | `codex/r03-protect-local-http` | Integrated in `e40a046`; classic/v2 browser lifecycle, cancellation, policy save and actual ZIP request-protection checks pass |
| R04 | `codex/r04-report-scope` | Integrated in `4721240`; consistent connected scope and exclusion evidence verified |
| R05 | Existing Windows fix reused | Local Windows suite passed; Windows CI lane present; remote CI still pending |
| R06 | `codex/r06-cli-contract` | Integrated in `0453888`; command guide/version, structured JSON errors and opt-in plan JSON mode |
| R07 | `codex/r07-first-run` | Integrated in `3c9736f`; source and actual ZIP walkthroughs pass; routine UI review delegated to agent on 2026-10-05 |
| R08 | `codex/r08-result-clarity` | Integrated `d26934e`; scope/results clarity and both-layout reviewed recovery pass |
| R09 | `codex/r09-keyboard-polish` | Integrated `687060e`; keyboard/offline/readability pass; true browser zoom and Windows 125% scaling remain open |
| R10 | `codex/r10-package-verification` | Integrated `fa5d1b8` and `7412885`; exact ZIP automation passes; native visual and clean-machine acceptance remain open |
| R11 | `codex/r11-release-guidance` | Integrated `9ac7457`; candidate guidance and links verified locally |
| R12 | Integration evidence | Agent records **NO-GO** under delegated verification; see release decision and remaining gates |
| R13 | Deferred | Operations schema follows release gates |

Use the [approved plan](README.md) and its individual tickets for acceptance criteria. A passing unit suite does not authorize release publication or mark visual/package checks complete.

## Integrated verification

- `30ecdba`, Windows Python 3.13 with `PYTHONUTF8=0`: export and Unicode regression suite **56 passed, 2 skipped** (symlink privileges); Ruff passed.
- Full suite on that revision: **821 passed, 8 skipped, 1 failed** in 92.22 seconds. The existing asynchronous job test exceeded its three-second completion deadline. Its focused rerun passed all five job tests, with the affected test taking 1.06 seconds. This is recorded as intermittent timing evidence, not a clean full-suite result; rerun after the next integration batch.
- R04 implementation `1a02dd5` (integrated as `4721240`) passed the full Windows suite with `PYTHONUTF8=0`: **829 passed, 8 skipped** in 79.83 seconds; Ruff passed. The earlier job timeout did not recur.
- R03 full suite before its R04 merge: **965 passed, 8 skipped**. After integrating R04, shared security/API/client/smoke/scope checks: **278 passed, 1 skipped**; Ruff passed. Real loopback HTTP and Node checks passed; these are not rendered-browser or packaged-EXE acceptance.
- R01 plan/baseline alias follow-up `2777546`, including R03/R04: **172 passed, 4 existing skips** across affected exports/check/plan/scope tests; Ruff passed.
- R06 and naming-export companion, integrated in `0453888`: **229 targeted tests passed, 4 existing skips**. Both installed aliases and the module entry point passed captured UTF-8 help/version and JSON-contract tests.
- **Final combined verification on `0453888`: 1,015 passed, 8 skipped in 91.57 seconds.** Ran `python -m pytest -q -ra` on Windows Python 3.13 with `PYTHONUTF8=0` and `PYTHONPATH` pointing to integration `src`. Seven skips are unavailable symbolic-link privileges and one is POSIX permission bits. Windows junction and hard-link tests passed. `python -m ruff check .` and `git diff --check` passed. The earlier asynchronous timeout did not recur; no test deadline was weakened. Subsequent integration changes only update these planning records.
- Shared T3 preview cannot reach the Windows loopback app. The user subsequently authorized local browser automation, preferring the MSI machine. `COMPUTERNAME=MSI`, manufacturer Micro-Star International, model Summit E15 A11SCST were verified locally. Edge runs on that machine in isolated browser contexts against disposable data. This enables UI capture; it does not constitute final human acceptance or packaged-EXE verification.
- R07 `7f32ef3`, integrated as `3c9736f`: **1,020 passed, 8 skipped** in 181.93 seconds on final source; Ruff passed. Integration source/tests/scripts match that tested revision exactly. Ten fresh-context browser scenarios across both layouts and two stale-response checks passed. Independent v2 browser export/preview-cancel/apply/restore passed, restoring ten original files byte-for-byte. [R07 captures and limits](../../audits/windows-ui-2026-10-03/R07.md), [v2 lifecycle evidence](../../audits/windows-ui-2026-10-03/r03-v2/README.md).

## Current disposition — 2026-10-05

The user delegated verification and routine UI decisions to the agent: “I want you to verify everything. I'm not needed here. And proceed with the work.” Earlier human UI checkpoints no longer block implementation. No independent fresh-user acceptance or publication is implied.

R08/R09 were implemented sequentially and integrated. Both layouts passed keyboard-only demo/analyze/item/action/apply/history/restore at two laptop viewports. Preview cancellation did not mutate files; applied verification and reviewed restore recovered exact originals. Native modal layering fixes Escape, focus and cancellation reachability; local fonts remove network dependence. Scope/results summaries distinguish Safe/Review candidates, coverage limitations and Report Health. [R08 evidence](../../audits/windows-ui-2026-10-05/R08.md), [R09 evidence](../../audits/windows-ui-2026-10-05/R09.md).

Latest full application suite at R09: **1,020 passed, 8 existing skips**, Windows Python 3.13 with PYTHONUTF8=0, in 92.35 seconds; Ruff passed. Later fixture/package regression set: **28 passed, 1 existing skip**. The integrated runtime source matches the packaged build; later changes are verification fixtures, harnesses and documentation.

The actual ZIP was built from clean `fa5d1b8da3e899fd1ceaaf6a5c05575081f088cd` and passed all 16 package smoke checks. SHA-256: `a03f0647b8caa250c85f666ce806cbed5fd7852a1ea407a1de69df636407c70c`. Both UI layouts, exports, local HTTP protection, stale plans, UTF-8 rename, offline schemas and byte-exact recovery passed outside the checkout with Python removed from the child PATH. Isolated automatic Edge launch and a fresh wheel installation passed. [R10 evidence](../../audits/windows-ui-2026-10-05/R10.md).

Native Power BI 2.158.1177.0 opened the corrected synthetic baseline and the packaged changed project. Baseline visuals produced query errors after refresh before any cleaner mutation, so runtime equivalence is **not passed**. Packaged restore nevertheless recovered all project metadata byte-for-byte. Existing user Power BI projects were preserved. Clean-machine SmartScreen/Defender behavior, remote Linux/Windows CI, actual browser zoom/Windows 125% scaling, and independent first-user testing remain unverified.

R11 updates Windows installation, candidate screenshots, CLI and recovery guidance, and distinguishes the candidate from the older published beta3 download. Local links, published assets and the rendered candidate page were verified. [R11 evidence](../../audits/windows-ui-2026-10-05/R11.md).

**Release decision: NO-GO.** [R12](../../audits/windows-ui-2026-10-05/R12.md) records ticket dispositions and six actionable remaining acceptance items. The local archive retains the development version b3 and must not replace published b3; a new version, rebuild and exact-artifact verification are required before any publication. R13 remains deferred. No release, PR, deployment or announcement was published.

Implementation worktrees are siblings under `C:/Users/PrzemekHarazny/Projects/`, with all completed changes integrated on `codex/windows-beta-integration`. The original application checkout and unrelated `.claude` worktrees are preserved. Local evidence supersedes older pending-status statements above while retaining their historical test results.
