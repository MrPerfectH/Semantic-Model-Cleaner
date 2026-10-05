# Upcoming Windows beta — unpublished candidate

This work extends published 0.4.0b3. It has **not** been tagged, uploaded or deployed. Local verification archives retain the development version 0.4.0b3 and must not replace the immutable published files. A new version and corresponding links must be selected before publication.

The candidate adds protected analysis exports, consistent connected-Report selection, Windows UTF-8 handling, local HTTP request protection, discoverable CLI commands and JSON errors, explicit project/demo scope review, a scoped result summary, reviewed recovery differences, and keyboard-accessible dialogs. Fonts work offline.

Screenshots in the [quick start](../quickstart.md) and landing page come from the locally built Windows artifact at source `fa5d1b8`, including R01–R09 and the package verification harness. They demonstrate the candidate, not the older published download.

Windows source checks passed 1,020 tests with eight platform/privilege skips. The actual ZIP passed checksum, Python-free process PATH, spaces/non-ASCII extraction, port fallback, both layouts and assets, JSON/Excel exports, request protection, stale-plan rejection, UTF-8 rename and byte-exact recovery. A fresh wheel install also passed. These checks do not replace remote Linux/Windows CI, clean-machine reputation checks, or Power BI runtime acceptance. The [release decision](../audits/windows-ui-2026-10-05/R12.md) is **no-go** and records outstanding gates, including visual errors in the synthetic Power BI baseline before any cleaner change.

Known boundaries remain: one selected model, selected connected Reports only, supported static metadata, dynamic coverage at Review, BOM-prefixed TMDL scopes read-only for saved changes, and an unsigned Windows ZIP. No hosted discovery, PBIX import or automatic runtime-equivalence guarantee is provided.

Publication checklist: settle remaining gates, assign a new version, rebuild and verify that exact artifact, update versioned ZIP/checksum/wheel links and screenshots if needed, then obtain separate publication authorization.
