# Semantic Model Cleaner

Semantic Model Cleaner is the product context for analyzing local Power BI Project files, explaining semantic model usage, and preparing cautious cleanup actions. This glossary defines the project language agents should use when planning or changing the repository.

## Language

**Semantic Model Cleaner**:
The local tool that analyzes Power BI Project files and helps practitioners understand semantic model usage before applying cleanup actions.
_Avoid_: Cleaner app, analyzer app

**Power BI Project**:
A folder-based Power BI workspace representation containing a semantic model, one or more reports, or both.
_Avoid_: Workspace, PBIX, project folder

**Semantic Model**:
The Power BI model artifact that contains tables, columns, measures, relationships, roles, and model metadata.
_Avoid_: Dataset, data model

**Report**:
The Power BI report artifact that contains pages, visuals, filters, bookmarks, report extensions, and references back to a semantic model.
_Avoid_: Dashboard, PBIX report

**TMDL**:
The Tabular Model Definition Language representation of semantic model metadata.
_Avoid_: Model text, table file format

**PBIR**:
The Power BI report folder format used to represent report metadata as schema-backed JSON files.
_Avoid_: Report JSON, report definition files

**Semantic Model Item**:
A model object that can be analyzed for usage and cleanup risk, such as a measure, column, calculated column, hierarchy level, relationship, table, or role-backed dependency.
_Avoid_: Field, object, asset

**Report Reference**:
A report-side reference from PBIR metadata to a semantic model item.
_Avoid_: Usage, dependency, link

**Live Report Reference**:
A report reference that contributes to current report behavior and should make the referenced semantic model item count as used.
_Avoid_: Active usage, real usage

**Stale Report Reference**:
A report reference that remains in PBIR metadata but no longer contributes to current report behavior.
_Avoid_: Dead usage, orphaned metadata

**Cleanup Recommendation**:
The app's user-facing judgment about whether a semantic model item can be changed or deleted safely.
_Avoid_: Cleanup status, delete status

**Safe**:
A cleanup recommendation meaning no supported scanned metadata indicates that the item is required.
_Avoid_: Unused, deletable

**Review**:
A cleanup recommendation meaning a human should inspect the item because evidence is incomplete, ambiguous, unsupported, or caution-worthy.
_Avoid_: Maybe safe, warning

**Unsupported Metadata**:
Documented Power BI, TMDL, or PBIR metadata that the app can detect or encounter but does not yet fully analyze.
_Avoid_: Unknown metadata, edge case

**Report Health**:
The product surface that explains PBIR problems, stale references, invalid report JSON, and repair opportunities.
_Avoid_: Warnings, issues list

**Cleanup Action**:
A local change the app can apply to semantic model or report files, such as hiding, moving, renaming, deleting, or repairing references.
_Avoid_: Fix, mutation

**Report Extension Measure**:
A report-level measure defined in PBIR report extension metadata rather than in the semantic model.
_Avoid_: Local measure, report measure
