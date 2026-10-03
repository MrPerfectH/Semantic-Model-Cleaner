# Windows public beta session execution

The user authorized execution on 2026-10-03. Work is isolated from the original checkout and existing `.claude` worktrees. No release has been published.

Integration worktree: `C:/Users/PrzemekHarazny/Projects/smc-windows-beta-integration` on `codex/windows-beta-integration`.

The original checkout was at `6d29ce2`, six commits behind local `origin/main`. Integration includes the newer `d5a4be7` beta3 baseline and the existing Windows portability commit `d373113`, reused as `4631a9e` after review. Its local full-suite verification passed: **766 passed, 6 skipped** in 80.39 seconds. Remote CI and the packaged EXE are not established by this result.

| Ticket | Session branch | State |
| --- | --- | --- |
| R01 | `codex/r01-protect-exports`; `codex/r01-output-alias-followup` | Integrated ordinary exports (`c57f771`), plan/baseline aliases (`2777546`) and naming exports (`6e6ace9`) |
| R02 | `codex/r02-windows-unicode` | Integrated in `30ecdba`; Unicode lifecycle and malformed-input checks verified |
| R03 | `codex/r03-protect-local-http` | Integrated in `e40a046`; classic and v2 browser apply/recovery and exports pass; background cancellation/package evidence pending |
| R04 | `codex/r04-report-scope` | Integrated in `4721240`; consistent connected scope and exclusion evidence verified |
| R05 | Existing Windows fix reused | Local Windows suite passed; Windows CI lane present; remote CI still pending |
| R06 | `codex/r06-cli-contract` | Integrated in `0453888`; command guide/version, structured JSON errors and opt-in plan JSON mode |
| R07 | `codex/r07-first-run` | Integrated in `3c9736f`; source walkthroughs pass; human review and packaged UI acceptance pending |
| R08–R09 | Pending human/visual work | Follow R07 with sequential visual review |
| R10–R12 | Pending | Package evidence and human release acceptance still required |
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

## Next session and remaining acceptance

R07 is integrated locally. Open Power BI Project/Try demo are visible, connected scope is reviewed before explicit Analyze, and multiple models require a choice. Invalid inputs and separate roots retain a usable path. Human review of the [captured flow](../../audits/windows-ui-2026-10-03/R07.md) is the next checkpoint before R08 implementation. Actual package acceptance remains R10. R08/R09 remain sequential. Browser-tool authorization is resolved and must not be requested again.

R03's classic browser lifecycle passed on MSI, including authenticated downloads, reviewed apply, verification, byte-exact restore, and policy save; [evidence](../../audits/windows-ui-2026-10-03/r03-classic/README.md). V2 exports, preview cancellation, apply and restore also passed. Background-analysis cancellation and v2 policy save remain unverified in the browser. Existing v2 recovery-review/verification parity and classic stale pending status are recorded for R08/R10 assessment. R05 still needs remote Linux/Windows CI evidence, including symlinks on a capable runner. R10/R11 remain dependent on the settled UI, and R12 remains a human release decision. No Windows ZIP was rebuilt or published in these implementation sessions. R13 stays deferred.

All implementation worktrees are siblings under `C:/Users/PrzemekHarazny/Projects/`: `smc-r01-protect-exports`, `smc-r02-windows-unicode`, `smc-r03-protect-local-http`, `smc-r04-report-scope`, `smc-r01-output-alias-followup`, `smc-r06-cli-contract`, and `smc-r07-first-run`. Their work has been integrated locally; original application source and unrelated `.claude` worktrees are preserved.
