# Upcoming Windows beta4 — unpublished candidate

Version **0.4.0b4** extends published beta3. Implementation and verification are complete in [PR #104](https://github.com/MrPerfectH/Semantic-Model-Cleaner/pull/104); beta4 has not been tagged or uploaded. Published download links still point to immutable beta3.

The candidate adds protected analysis exports, consistent connected-Report selection, Windows UTF-8 and cross-drive handling, local HTTP request protection, discoverable CLI commands and JSON errors, explicit project/demo scope review, scoped result summaries, reviewed recovery differences, recent history and keyboard-accessible dialogs. Fonts work offline.

The [release decision and exact artifact identity](../audits/windows-ui-2026-10-05/R12.md) record passing Windows/Linux CI, fresh installed-wheel acceptance, all 16 exact-ZIP checks, separate-runner ZIP verification, native Power BI refresh/apply/restore, real browser 125%/150% zoom and native Windows 125%/150% scaling. The recommendation is to proceed with the scoped public beta.

Screenshots in the [quick start](../quickstart.md) and landing page show this candidate's UI. They were captured at the earlier R01–R09 implementation; subsequent verification screenshots are linked from the decision record.

Boundaries remain: one selected model, selected connected Reports, supported static metadata, dynamic coverage at Review, BOM-prefixed TMDL scopes read-only for saved changes, and an unsigned ZIP. Consumer SmartScreen reputation behavior and independent first-use research are unverified. No PBIX import or automatic runtime-equivalence guarantee is provided.

The [beta4 release notes](0.4.0b4.md) are prepared. Publication will require merging the reviewed change, producing/tagging the release from the accepted source, and updating versioned download links when those assets exist. Do not overwrite beta3.
