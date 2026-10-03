# Windows public beta session execution

The user authorized execution on 2026-10-03. Work is isolated from the original checkout and existing `.claude` worktrees. No release has been published.

Integration worktree: `C:/Users/PrzemekHarazny/Projects/smc-windows-beta-integration` on `codex/windows-beta-integration`.

The original checkout was at `6d29ce2`, six commits behind local `origin/main`. Integration includes the newer `d5a4be7` beta3 baseline and the existing Windows portability commit `d373113`, reused as `4631a9e` after review. Its local full-suite verification passed: **766 passed, 6 skipped** in 80.39 seconds. Remote CI and the packaged EXE are not established by this result.

| Ticket | Session branch | State |
| --- | --- | --- |
| R01 | `codex/r01-protect-exports` | Implementing and testing export protection in its own worktree |
| R02 | `codex/r02-windows-unicode` | Implementing remaining Unicode/CLI gaps on top of reused fixes |
| R03–R04 | Pending next batch | Start after integrating and checking R01/R02 |
| R05 | Existing Windows fix reused | Local Windows suite passed; Windows CI lane present; remote CI still pending |
| R06 | Pending | Requires integrated R01/R02/R04 |
| R07–R09 | Pending human/visual work | Shared browser cannot reach Windows loopback; actual flow capture is still required |
| R10–R12 | Pending | Package evidence and human release acceptance still required |
| R13 | Deferred | Operations schema follows release gates |

Use the [approved plan](README.md) and its individual tickets for acceptance criteria. A passing unit suite does not authorize release publication or mark visual/package checks complete.

