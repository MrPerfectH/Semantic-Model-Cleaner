# Windows public beta implementation plan

Prepare Semantic Model Cleaner for a broader public beta aimed primarily at **Power BI developers on Windows**. Installation and the main cleanup flow should require no Python knowledge. CLI support remains a supported secondary workflow for automation and AI coding agents.

The user approved this breakdown on 2026-10-03 and then authorized execution with “Split work into sessions an go.” Implementation uses isolated ticket worktrees, preserving the agreed dependencies and human checkpoints. See [session execution and evidence](EXECUTION.md) for current status. This package contains 13 local tickets; it has not created GitHub issues or a pull request.

The source evidence is the [release readiness audit](../../audits/release-readiness-2026-10-02.md) of revision `6d29ce2`. Its runtime findings are reproduced defects; its visual recommendations remain code-grounded proposals because the shared browser could not reach the Windows-hosted app. Every implementation session must recheck the current code and any existing GitHub issue before acting.

## Release scope

The complete user outcome is: download and extract the Windows package, launch, choose a Power BI Project or demo, review the Semantic Model and connected Reports, understand evidence and limitations, preview a Cleanup Action, apply a reviewed plan, and recover original bytes when needed.

Release gates cover source-file protection, Windows text handling, local HTTP protection, connected Report scope, Windows CI, baseline CLI usability, accessible core interactions, real packaged-artifact verification, accurate public guidance, and a human release decision. First-run and result presentation improvements are launch targets whose scope may be reduced explicitly. The operations-schema work is a follow-up. Existing analysis semantics, report-issue grouping restrictions, exact plan previews, and guarded recovery remain intact.

No ticket introduces automatic deletion, inferred bulk broken-reference repair, hosted access, cloud integration, embedded AI chat, a new frontend framework, or a promise that static checks prove Power BI runtime equivalence. Code signing and an installer can be evaluated separately; neither is silently assumed available for next week.

## Ticket breakdown

AFK means sufficiently specified for an implementation session after dependencies are satisfied. HITL means a session can prepare the work, but a human design or acceptance checkpoint remains. Neither label grants permission to merge or publish beyond the instructions of the assigned session.

1. **[R01: Protect Semantic Model and Report files from analysis exports](tickets/r01-protect-analysis-exports.md)** — AFK; blocked by nothing.
   User story: As a Power BI developer, I can export analysis without accidentally replacing my project metadata.

2. **[R02: Preserve Unicode through Windows startup and reviewed CLI changes](tickets/r02-windows-unicode.md)** — AFK; blocked by nothing.
   User story: As a Windows user, I can launch the app and use non-English names without crashes or silent corruption.

3. **[R03: Protect local file operations from foreign browser requests](tickets/r03-protect-local-http.md)** — AFK; blocked by nothing.
   User story: As a desktop user, opening another website cannot authorize changes to my local Power BI Project.

4. **[R04: Use consistent connected Report selection across analysis and automation](tickets/r04-consistent-report-scope.md)** — AFK; blocked by nothing.
   User story: As a Power BI developer, I get consistent usage evidence from the app and CLI for the same Semantic Model and Reports.

5. **[R05: Run the full unit suite on Windows with portable fixtures](tickets/r05-windows-ci.md)** — AFK; blocked by [R02](tickets/r02-windows-unicode.md).
   User story: As a maintainer, I see Windows regressions before distributing a Windows release.

6. **[R06: Make the existing CLI discoverable and predictable for automation](tickets/r06-cli-discovery-and-errors.md)** — AFK; blocked by [R01](tickets/r01-protect-analysis-exports.md), [R02](tickets/r02-windows-unicode.md), [R04](tickets/r04-consistent-report-scope.md).
   User story: As a CLI or AI-agent user, I can discover supported commands and reliably distinguish successful analysis, findings, and invalid input.

7. **[R07: Give Windows users a clear first analysis path](tickets/r07-first-run.md)** — HITL; blocked by [R03](tickets/r03-protect-local-http.md), [R04](tickets/r04-consistent-report-scope.md).
   User story: As a first-time Windows user, I can try a demo or open a Power BI Project and understand the analysis scope without reading setup documentation.

8. **[R08: Make analysis results explain coverage and the next Cleanup Action](tickets/r08-result-clarity.md)** — HITL; blocked by [R04](tickets/r04-consistent-report-scope.md), [R07](tickets/r07-first-run.md).
   User story: As a Power BI developer, I can understand what was checked and why an item has a Cleanup Recommendation before preparing a change.

9. **[R09: Make the core desktop flow keyboard accessible and readable](tickets/r09-keyboard-and-visual-polish.md)** — HITL; blocked by [R07](tickets/r07-first-run.md), [R08](tickets/r08-result-clarity.md).
   User story: As a Windows user at normal or enlarged display scaling, I can complete analysis and reviewed changes with the keyboard and read the evidence comfortably.

10. **[R10: Verify the actual Windows release package and recovery workflow](tickets/r10-windows-release-verification.md)** — HITL; blocked by [R01](tickets/r01-protect-analysis-exports.md), [R02](tickets/r02-windows-unicode.md), [R03](tickets/r03-protect-local-http.md), [R04](tickets/r04-consistent-report-scope.md), [R05](tickets/r05-windows-ci.md), [R06](tickets/r06-cli-discovery-and-errors.md), [R09](tickets/r09-keyboard-and-visual-polish.md).
   User story: As a Windows user without Python installed, I can download the release and complete a recoverable cleanup.

11. **[R11: Make the Windows download and public guidance match the candidate](tickets/r11-release-guidance.md)** — HITL; blocked by [R06](tickets/r06-cli-discovery-and-errors.md), [R09](tickets/r09-keyboard-and-visual-polish.md).
   User story: As a new Power BI developer, I can find the correct Windows download, understand supported inputs, and get useful help without installing Python.

12. **[R12: Record the release candidate decision and remaining limitations](tickets/r12-release-decision.md)** — HITL; blocked by [R10](tickets/r10-windows-release-verification.md), [R11](tickets/r11-release-guidance.md).
   User story: As the maintainer, I can make a release decision using verified evidence and a clear list of remaining limitations.

13. **[R13: Publish a machine-readable operations contract for AI agents](tickets/r13-agent-operations-contract.md)** — AFK; blocked by [R06](tickets/r06-cli-discovery-and-errors.md).
   User story: As an AI-agent or automation author, I can discover supported operations and produce valid reviewed plans without guessing fields.

## Recommended session order

The dependencies above describe functional prerequisites. The batches below also account for likely code overlap. Use at most two implementation sessions at once, consistent with the repository's release-workstream guidance.

| Batch | Session A | Session B | Why this order |
| --- | --- | --- | --- |
| 1 | [R01](tickets/r01-protect-analysis-exports.md) export protection | [R02](tickets/r02-windows-unicode.md) Windows Unicode | Independent user outcomes; avoid simultaneous edits to CLI dispatch/analyzer entry points by agreeing ownership first |
| 2 | [R03](tickets/r03-protect-local-http.md) local HTTP protection | [R04](tickets/r04-consistent-report-scope.md) Report selection | Review both diffs for shared web entry points; R01 is integrated before more analyzer edits |
| 3 | [R05](tickets/r05-windows-ci.md) Windows CI | [R06](tickets/r06-cli-discovery-and-errors.md) CLI discovery/errors | Core scope and encoding behavior has settled; keep fixture edits coordinated |
| 4 | [R07](tickets/r07-first-run.md) first-run flow | No competing frontend work | Human walkthrough determines the actual UI changes |
| 5 | [R08](tickets/r08-result-clarity.md) result clarity | Documentation outline only, if useful | Reuse the settled entry flow; avoid parallel template rewrites |
| 6 | [R09](tickets/r09-keyboard-and-visual-polish.md) keyboard/readability | No competing frontend work | Verify the combined flow and finish focused polish |
| 7 | [R10](tickets/r10-windows-release-verification.md) actual Windows package | [R11](tickets/r11-release-guidance.md) release guidance | Test and describe the same frozen candidate; screenshots may be shared |
| 8 | [R12](tickets/r12-release-decision.md) release decision | — | Evaluate package evidence and public claims together |
| Later | [R13](tickets/r13-agent-operations-contract.md) agent operations schema | — | Optional after release gates; no need to delay the Windows launch for this |

Integrate a completed batch before starting dependent sessions. If R01 and R02 both need the same CLI function, integrate R01 first and rebase R02 before finishing. Similarly coordinate web initialization changes in R03/R04. Do not treat separate worktrees as protection from semantic conflicts.

This is a work order, not a promise that all 13 tickets fit into seven days. Review the remaining time after batch 3. If time is short, explicitly reduce R07/R08 to the minimum clear existing flow; update R09 acceptance to that retained flow and record the deferred enhancements. Never bypass safety gates or count a failed browser/package check as passed. If release gates cannot be met, delay or separately agree a narrower analysis-only release; disabling edits is itself work requiring verification.

## Rules for each implementation session

1. Assign exactly one ticket and start from a revision containing its completed dependencies. Use a separate worktree/branch, such as `release/r01-protect-exports`; the branch name is a suggestion, not an existing branch.
2. Read repository agent instructions, the domain glossary, applicable ADRs, this plan, and the ticket. Use synthetic copies for mutations. Verify the original failure before claiming a fix.
3. Keep scope within the ticket, including all affected entry points and documentation. Record a newly discovered blocker instead of expanding into another session's ownership.
4. Run meaningful regression checks for the changed behavior. For UI tickets, capture the actual running interface and get the stated human review. A tool-access failure remains an explicit validation gap.
5. Hand back a concise summary, commit/branch or PR if requested, checks executed, evidence paths, compatibility changes, and remaining acceptance. PR creation, merging, or publishing follows the assigned session's authorization.
6. The integrator reviews the combined diff, reruns relevant shared checks, and records the integrated revision before making dependent tickets available.

Copy this prompt into a new session:

> Implement ticket RXX from docs/plans/windows-public-beta/tickets/ in this repository. Read its full body and the release plan first. Confirm all dependencies are integrated, use a separate worktree/branch, and keep the work within this ticket. Reproduce the issue on disposable synthetic data, implement the complete behavior, run the specified checks, and report evidence and any remaining human acceptance. Do not publish a release or mutate real Power BI Projects. If the ticket is HITL, prepare concrete screenshots or verification evidence for review.

## Publication and tracking

Local IDs R01–R13 are planning identifiers, not GitHub issue numbers. The repository's tracker is GitHub at MrPerfectH/Semantic-Model-Cleaner. The breakdown review required by `to-issues` was completed on 2026-10-03. No further breakdown approval is needed before publication.

GitHub CLI remains unavailable on PATH and in the checked standard installation locations as of 2026-10-03. Publication is blocked only by GitHub tooling/access, not by approval. Before publication, restore access to an authenticated `gh` CLI, list existing issues to avoid duplicates, and reconcile overlap. Do not infer tracker status from this local snapshot.

When GitHub access is available, publish blockers first using the exact ticket text through a body file. Replace local dependency links with actual GitHub issue links, add any needed real issue dependency metadata, and keep the local-to-GitHub mapping here. Use the repository's `ready-for-agent` vocabulary for approved AFK work only once blockers are resolved; keep blocked work labeled/tracked as blocked rather than implying it can start. HITL work uses the human-review queue. Do not close or modify unrelated parent issues.

## Definition of release readiness

The final candidate has passing relevant checks on Windows and Linux, verified downloadable artifacts with matching hashes, a successful plan/apply/verify/restore round trip on synthetic data, protection against the audited unsafe cases, and documented manual Windows/Power BI acceptance. First-time users can identify scope, inspect one finding, and locate recovery. The public download, support matrix, and screenshots describe that exact candidate.

The maintainer makes the final release decision in R12. Creating these documents or completing a ticket does not publish anything.

