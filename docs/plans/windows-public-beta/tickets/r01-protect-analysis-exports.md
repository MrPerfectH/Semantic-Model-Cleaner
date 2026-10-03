# R01 Protect Semantic Model and Report files from analysis exports

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Release gate.

## User story

As a Power BI developer, I can export analysis without accidentally replacing my project metadata.

## What to build

Protect every ordinary analyzer export format, including default Excel destinations, from writing inside discovered or selected Semantic Model and Report artifacts. Apply the rule to explicit paths, excluded artifacts, and resolved aliases. Preserve normal exports to an external directory.

## Evidence

On a disposable bundled-demo copy, JSON export to the existing Sales.tmdl source returned success and replaced TMDL with JSON. Saved-plan and baseline outputs already have stronger boundaries.

## Acceptance criteria

- [ ] Text, JSON, and Excel exports reject destinations inside selected or discovered artifacts before writing; rejection preserves all original bytes and creates no recovery receipt.
- [ ] Default Excel output is also protected when the current directory is inside an artifact.
- [ ] Symlink/junction aliases cannot bypass protection; address hard-linked output files explicitly without weakening normal exports.
- [ ] External output directories still work, including Windows paths with spaces and non-ASCII characters.
- [ ] The error explains how to choose a valid destination and returns a nonzero input-error exit status.
- [ ] Regression checks run only on disposable synthetic projects and cover at least selected model, selected report, excluded artifact, and external success.

## Blocked by

None — can start immediately.

## Verification

Reproduce the original JSON overwrite attempt on a copy and compare a full byte snapshot before/after. Exercise each supported output format and supported filesystem alias mechanism.

## Out of scope

Changing cleanup writers, adding backups to analysis, or redesigning export formats.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

