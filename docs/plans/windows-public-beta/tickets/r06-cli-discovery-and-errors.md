# R06 Make the existing CLI discoverable and predictable for automation

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a CLI or AI-agent user, I can discover supported commands and reliably distinguish successful analysis, findings, and invalid input.

## What to build

Expose a complete top-level command guide and version output, then document and normalize machine-readable success/error behavior for existing analysis, check, and plan commands. Preserve existing no-subcommand analysis syntax and avoid silently changing flag meaning.

## Evidence

Top-level help hides most commands, --version is rejected, and analyzer JSON mode emits plain-text errors with different exit conventions from check. Model-selection flags also have different meanings across command families.

## Acceptance criteria

- [ ] Top-level help lists check, stale discovery, plans/diff/apply/verify/history/restore/recover-lock, policy, and naming, with working examples.
- [ ] A version command/flag works for installed aliases and the documented module entry point.
- [ ] Document stdout/stderr, encoding, and exit-code contracts; JSON-mode runtime/input failures use a documented parseable envelope.
- [ ] Help clearly distinguishes current exact-path flags from name filters and their path bases; preserve compatibility or provide an explicit migration path.
- [ ] Success output changes are additive or versioned; existing check finding fingerprints and plan schema/digest behavior remain stable.
- [ ] A short synthetic workflow demonstrates check, reviewed plan/diff, approved apply, verify, and restore without interactive prompts.
- [ ] Regression tests cover help/version, missing input, no eligible Reports, protected output, stale plan, and successful JSON parsing.

## Blocked by

- [R01: Protect Semantic Model and Report files from analysis exports](r01-protect-analysis-exports.md)
- [R02: Preserve Unicode through Windows startup and reviewed CLI changes](r02-windows-unicode.md)
- [R04: Use consistent connected Report selection across analysis and automation](r04-consistent-report-scope.md)

## Verification

Run commands in subprocesses and parse stdout as documented. Compare existing fixtures and documented legacy invocations before and after.

## Out of scope

MCP, embedded AI chat, broad flag redesign, and the new operations-schema endpoint reserved for R13.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

