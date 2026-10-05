# R06 Make the existing CLI discoverable and predictable for automation

Status: Implemented, reviewed and integrated as `0453888` on 2026-10-03. Local ticket, not a published GitHub issue.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a CLI or AI-agent user, I can discover supported commands and reliably distinguish successful analysis, findings, and invalid input.

## What to build

Expose a complete top-level command guide and version output, then document and normalize machine-readable success/error behavior for existing analysis, check, and plan commands. Preserve existing no-subcommand analysis syntax and avoid silently changing flag meaning.

## Evidence

Top-level help hides most commands, --version is rejected, and analyzer JSON mode emits plain-text errors with different exit conventions from check. Model-selection flags also have different meanings across command families.

## Acceptance criteria

- [x] Top-level help lists check, stale discovery, plans/diff/apply/verify/history/restore/recover-lock, policy, and naming, with working examples.
- [x] A version command/flag works for installed aliases and the documented module entry point.
- [x] Document stdout/stderr, encoding, and exit-code contracts; JSON-mode runtime/input failures use a documented parseable envelope.
- [x] Help clearly distinguishes current exact-path flags from name filters and their path bases; preserve compatibility or provide an explicit migration path.
- [x] Success output changes are additive or versioned; existing check finding fingerprints and plan schema/digest behavior remain stable.
- [x] A short synthetic workflow demonstrates check, reviewed plan/diff, approved apply, verify, and restore without interactive prompts.
- [x] Regression tests cover help/version, missing input, no eligible Reports, protected output, stale plan, and successful JSON parsing.

## Blocked by

- [R01: Protect Semantic Model and Report files from analysis exports](r01-protect-analysis-exports.md)
- [R02: Preserve Unicode through Windows startup and reviewed CLI changes](r02-windows-unicode.md)
- [R04: Use consistent connected Report selection across analysis and automation](r04-consistent-report-scope.md)

## Verification

Run commands in subprocesses and parse stdout as documented. Compare existing fixtures and documented legacy invocations before and after.

### Implementation evidence (2026-10-03)

- Started from `2777546`, containing R01/R02/R04 prerequisites and R03. A separately committed R01 naming-output companion (`6e6ace9`) closes the last direct CLI export alias gap without mixing it into this CLI contract change.
- Top-level help now lists all supported commands, examples, exact-path versus name-filter meanings, and CWD/PROJECT path bases. `--version` uses the package version through the module and both installed CLI aliases.
- Analysis JSON adds version/command/ok metadata while retaining existing fields. JSON input/runtime failures, including argument syntax, return a stdout envelope and exit 2. JSON file exports return a stdout JSON receipt. Check retains its existing envelope/fingerprints and now emits it for JSON argument errors too.
- Plan-family `--format json` is opt-in: versioned stdout responses/errors and structured saved-plan diffs. Omitting the flag retains legacy text diffs, JSON success fields/formatting, and stderr JSON errors. Saved-plan schema and digest are unchanged. Help/version stay text; other command families' argument-error behavior is documented accurately.
- Added `docs/cli/README.md`, linked it from the main README, and aligned check/plans docs. It documents streams, UTF-8, exit codes, compatibility changes, path bases, and a disposable Windows check/plan/diff/apply/verify/history/restore example.
- Added 17 subprocess cases using UTF-8 mode disabled and cp1252 redirected streams: installed alias/module help/version, missing input, parser errors, runtime errors with non-BMP text, no eligible Reports, protected outputs, successful JSON export receipts, verify state, stale-plan refusal, legacy diff/error compatibility, and byte-exact restoration. R04's empty-selection test now checks the structured error without weakening its binding assertions.
- Windows Python 3.13, `PYTHONUTF8=0`: affected CLI/scope/export/check/Unicode/stale/plan/policy suite — **229 passed, 4 skipped** in 41.80 seconds. Command: `pytest tests/test_cli_contract.py tests/test_connected_scope_entrypoints.py tests/test_analysis_exports.py tests/test_automation_export_safety.py tests/test_ci_check.py tests/test_windows_unicode.py tests/test_clean_stale_cli.py tests/test_change_plans.py tests/test_plan_write_boundaries.py tests/test_review_policy.py -q --tb=short`. Existing skips concern symlink privileges/POSIX permissions.
- `ruff check src tests` and `git diff --check` passed. Full integrated suite remains the integrator's check; no release or real project mutations occurred. R13's operations schema and new AI integrations remain deferred.

## Out of scope

MCP, embedded AI chat, broad flag redesign, and the new operations-schema endpoint reserved for R13.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

