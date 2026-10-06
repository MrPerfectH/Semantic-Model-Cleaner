# Issues #96 and #99 verification

Verified on Windows on 2026-10-05, against `t3code/issues-96-99-metadata-cleanup`.
Only synthetic model/report copies were used. No private model was opened or transferred.

## Automated checks

- Full suite: **1,105 passed, 8 skipped** (`python -m pytest -q`).
- Ruff: passed (`python -m ruff check .`).
- Source distribution and wheel: built successfully (`python -m build`).
- Independent review reproduced and then verified fixes for opaque culture
  annotation text being mistaken for model items or retained table declarations.
- Regression coverage includes multiline/fenced calculated-column kinds,
  browser payloads, JSON/XLSX exports, retained dependency guards, deletion and
  combined renames, LF/CRLF byte preservation, empty translation tables,
  whole-table cleanup, malformed structure, API blocking, and recovery.

## Rendered browser checks

Used the T3 collaborative browser at `http://localhost:5099/`, with the actual
local web app and its default layout. The synthetic project was generated with
`project()` from `tests/test_membership_cleanup.py`, which extends the perspective
and culture fixture from `calculation_group_dependencies`, plus
`MULTILINE_COLUMNS` from `tests/test_dependency_explanations.py`.

1. Opened scope and ran Analyze. Inventory showed 10 items; `Multi`, `Fenced`,
   and `Inline` each displayed **T · Calculated Column**. The source `Base`
   stayed **T · Column**, with cleanup **Blocked** by its retained consumers.
2. Opened `Sales[Revenue]`. Its properties showed perspective **Executive** and
   translation **pl-PL**, while cleanup remained **Safe**.
3. Entered `Net Revenue` and reviewed the rename. The dialog showed **3 file
   change(s)**: `cultures/pl-PL.tmdl`, `perspectives/Executive.tmdl`, and
   `tables/Sales.tmdl`. The culture diff changed the declaration name and
   preserved its translated caption. Apply completed and refreshed analysis.
   Structural re-reading of the applied files found no dangling memberships.
4. Opened Changes & history, reviewed recovery, and restored the rename.
   The UI reported **Original files restored**; file fingerprints matched the
   saved original inputs exactly.
5. Queued deletion of `Sales[Revenue]` and reviewed all three file diffs. They
   removed the model measure, perspective member, and translation block.
   Apply removed Revenue from the rendered inventory; structural re-reading
   found no dangling memberships. Recovery restored the original fingerprints.
6. Added an invalid line to the disposable culture file and requested another
   rename preview. The dialog displayed:

   `Blocked: cannot safely edit definition/cultures/pl-PL.tmdl: line 29: unrecognized TMDL syntax`

   Apply was disabled and the status read **Preview did not succeed. No changes
   applied.** The invalid fixture line was then removed; all original file
   fingerprints matched again.

Browser evidence was inspected through rendered DOM text and the live controls.
T3 `preview_snapshot` repeatedly failed with `PreviewAutomationExecutionError`,
so no screenshot or visual-layout verification is claimed.

## Limits

The writer accepts a conservative subset of perspective/culture structure and
blocks unfamiliar declarations. This is not TOM deserialization or DAX/runtime
validation. Linguistic metadata and annotation expression payloads stay opaque
and unchanged; existing analysis limitations and deletion guards remain in force.
Measure home-table moves are outside these two issues.
