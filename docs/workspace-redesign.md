# Cleaner workspace redesign

The workspace has one supported layout. Standalone setup walks through model,
report selection (including explicit model-only scope), and scope review before
analysis. In VS Code, the native Analysis Scope sidebar owns that selection.
Settings remain separate from scope.

Items, Tables, Reports and Changes are the primary views. Reports describes
metadata findings and schema coverage, not runtime performance or visual quality.
Zero-impact analysis limitations remain available in collapsed scan details.
Cleanup recommendations and conservative unknown/shared coverage are preserved.

Dependencies lists all downstream measures reachable through supported references,
including calculated columns, with owning table and Direct/Indirect classification.
Direct wins, cycles are deduplicated, and search/pagination retain closure totals.
Unresolved or unsupported coverage remains visible in supporting evidence.

Definition offers a syntax-colored reader, optional DAX formatting, exact-source
copy, explicit formatted copy, and a separate edit draft. Formatting does not
change source or drafts. See [Viewer reuse](viewer-code-reuse.md) for provenance
and the retained MIT license. There is no M formatter.

## Verification and acceptance

Windows verification of the integrated source passed 1,261 Python tests with 8
skips, focused dependency and schema/scope regressions, JavaScript syntax checks,
and standalone plus sidebar-owned page browser checks. A later CSS-only change
passed a focused narrow-viewport check. Dependency tests cover branching, long
chains, cycles, direct/indirect overlap, table ownership and calculated columns.
Reader tests cover comments, Unicode, escaped identifiers and large M input.

Private source-backed validation and audit artifacts are deliberately excluded
from this repository. Source and browser proof do not establish installed native
webview acceptance. The local preview was approved by the user. Independent review and installed
native verification remain release gates; this change does not publish an extension or apply model/report
changes. A combined Viewer/Cleaner product remains discovery only.

Review follow-up preserves discovered connected-report candidates on model changes,
allows explicit model-only refresh, lists analyzed reports with zero findings and
per-report schema coverage, and scopes measure coloring to model/report identity.
The packaging smoke follows the setup wizard and compact detail layout.

The final narrow review follow-up preserves explicit model-only mode only for the same model, restores UTF-8 setup labels, and isolates report-inventory columns from findings-grid preferences. Focused scope/encoding regressions and rendered inventory checks passed at 1280 px and 720 px; all six metadata columns remain available. The reusable browser assertion is `tests/browser/report-inventory.cjs` (call with an analyzed Reports page). The full 1,261-pass suite was recorded before this narrow follow-up; installed native visual verification remains pending.
