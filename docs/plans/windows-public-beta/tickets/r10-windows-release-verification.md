# R10 Verify the actual Windows release package and recovery workflow

Status (2026-10-05): Package automation passed; native visual comparison and clean-machine acceptance remain open. [Evidence](../../../audits/windows-ui-2026-10-05/R10.md). Local ticket, not a published GitHub issue.
Type: Originally HITL. The user delegated routine verification/review to the agent on 2026-10-05; independent-user and environment evidence remain separate requirements.
Priority: Release gate.

## User story

As a Windows user without Python installed, I can download the release and complete a recoverable cleanup.

## What to build

Build or obtain the candidate Windows ZIP and validate that exact artifact outside the source checkout. Extend the existing release smokes for the fixed regressions, then perform the Windows and Power BI checks automation cannot establish.

## Acceptance criteria

- [x] Verify the candidate version and SHA-256 checksum; record the artifact identity and source revision.
- [x] Extract into a path with spaces and non-ASCII characters and launch without Python on the app process PATH.
- [x] Verify browser opening, occupied-port fallback, both supported layouts, static assets, offline usability, and absence of startup tracebacks.
- [x] Analyze synthetic projects, export JSON/Excel, prepare/apply/verify a reviewed change, reject a stale plan, and restore byte-exact originals.
- [x] Exercise supported UTF-8 operations and the request protection from R02/R03 against the packaged runtime.
- [ ] A human opens the changed synthetic project in Power BI and checks the intended report behavior; preserve limitations of static validation.
- [x] Capture logs/screenshots/results and explicitly record unsigned-package prompts, antivirus/SmartScreen observations, and any untested clean-machine condition.
- [x] Failures create targeted follow-up tickets and block release; do not replace failed evidence with source-only checks.

## Blocked by

- [R01: Protect Semantic Model and Report files from analysis exports](r01-protect-analysis-exports.md)
- [R02: Preserve Unicode through Windows startup and reviewed CLI changes](r02-windows-unicode.md)
- [R03: Protect local file operations from foreign browser requests](r03-protect-local-http.md)
- [R04: Use consistent connected Report selection across analysis and automation](r04-consistent-report-scope.md)
- [R05: Run the full unit suite on Windows with portable fixtures](r05-windows-ci.md)
- [R06: Make the existing CLI discoverable and predictable for automation](r06-cli-discovery-and-errors.md)
- [R09: Make the core desktop flow keyboard accessible and readable](r09-keyboard-and-visual-polish.md)

## Verification

Use the downloaded ZIP in a clean Windows VM or equivalent controlled machine. Run existing package smokes plus manual acceptance, recording exact artifact hashes.

## Out of scope

Publishing the release, promising no SmartScreen warning, obtaining a signing certificate, or changing the release tag.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

