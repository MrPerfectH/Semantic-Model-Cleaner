# Item Details Layout Proposals

Three focused alternatives for the selected item details surface.

The goal is to replace the current grid of equal blocks with layouts that help a user decide:

- whether the item is used
- why cleanup is safe or blocked
- what depends on it
- where it appears in reports
- which cleanup action is appropriate

Expression and Power Query / M source are intentionally hidden behind technical-detail buttons in all three proposals.

Files:

- `index.html`: comparison and entry point
- `proposal-01-decision-summary.html`: recommended default
- `proposal-02-evidence-inspector.html`: best for investigation
- `proposal-03-action-workbench.html`: best for cleanup-heavy sessions

Recommendation: start with Proposal 1 for the live UI. It gives the user a clear answer first, keeps evidence visible, and avoids making DAX/M source dominate the page.
