# Windows public beta session execution

The user authorized execution on 2026-10-03. Work is isolated from the original checkout and existing `.claude` worktrees. No release has been published.

Integration worktree: `C:/Users/PrzemekHarazny/Projects/smc-windows-beta-integration` on `codex/windows-beta-integration`.

The original checkout was at `6d29ce2`, six commits behind local `origin/main`. Integration includes the newer `d5a4be7` beta3 baseline and the existing Windows portability commit `d373113`, reused as `4631a9e` after review. Its local full-suite verification passed: **766 passed, 6 skipped** in 80.39 seconds. Remote CI and the packaged EXE are not established by this result.

| Ticket | Session branch | State |
| --- | --- | --- |
| R01 | `codex/r01-protect-exports`; `codex/r01-output-alias-followup` | Ordinary exports integrated in `c57f771`; plan/baseline alias follow-up integrated in `2777546`; naming-preview guard companion underway |
| R02 | `codex/r02-windows-unicode` | Integrated in `30ecdba`; Unicode lifecycle and malformed-input checks verified |
| R03 | `codex/r03-protect-local-http` | Integrated in `e40a046`; automated boundary/lifecycle checks pass; rendered-browser acceptance pending |
| R04 | `codex/r04-report-scope` | Integrated in `4721240`; consistent connected scope and exclusion evidence verified |
| R05 | Existing Windows fix reused | Local Windows suite passed; Windows CI lane present; remote CI still pending |
| R06 | `codex/r06-cli-contract` | Implementing command guide/version and documented machine-output/error contracts |
| R07–R09 | Pending human/visual work | Shared browser cannot reach Windows loopback; actual flow capture is still required |
| R10–R12 | Pending | Package evidence and human release acceptance still required |
| R13 | Deferred | Operations schema follows release gates |

Use the [approved plan](README.md) and its individual tickets for acceptance criteria. A passing unit suite does not authorize release publication or mark visual/package checks complete.

## Integrated verification

- `30ecdba`, Windows Python 3.13 with `PYTHONUTF8=0`: export and Unicode regression suite **56 passed, 2 skipped** (symlink privileges); Ruff passed.
- Full suite on that revision: **821 passed, 8 skipped, 1 failed** in 92.22 seconds. The existing asynchronous job test exceeded its three-second completion deadline. Its focused rerun passed all five job tests, with the affected test taking 1.06 seconds. This is recorded as intermittent timing evidence, not a clean full-suite result; rerun after the next integration batch.
- R04 implementation `1a02dd5` (integrated as `4721240`) passed the full Windows suite with `PYTHONUTF8=0`: **829 passed, 8 skipped** in 79.83 seconds; Ruff passed. The earlier job timeout did not recur.
- R03 full suite before its R04 merge: **965 passed, 8 skipped**. After integrating R04, shared security/API/client/smoke/scope checks: **278 passed, 1 skipped**; Ruff passed. Real loopback HTTP and Node checks passed; these are not rendered-browser or packaged-EXE acceptance.
- R01 plan/baseline alias follow-up `2777546`, including R03/R04: **172 passed, 4 existing skips** across affected exports/check/plan/scope tests; Ruff passed.
- Shared T3 preview cannot reach the Windows loopback app. A request to use local browser automation is pending; no alternative browser has been used and no visual acceptance has been claimed.
