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
A cleanup recommendation meaning no supported scanned metadata indicates that the item is required and no shared Analysis Limitation applies.
_Avoid_: Unused, deletable

**No Use Found In Scope**:
The usage statement for an item with no Live Report Reference in the selected reports and no supported model dependency. When Analysis Limitations keep coverage incomplete, it is not a claim of global non-use.
_Avoid_: Globally unused, proven unused

**Review**:
A cleanup recommendation meaning a human should inspect the item because evidence is incomplete, ambiguous, unsupported, or caution-worthy.
_Avoid_: Maybe safe, warning

**Unsupported Metadata**:
Documented Power BI, TMDL, or PBIR metadata that the app can detect or encounter but does not yet fully analyze. Detected only from actual TMDL declarations, never from words in names, descriptions, comments, or expressions.
_Avoid_: Unknown metadata, edge case

**Analysis Limitation**:
One concrete gap in what the app checked for the selected scope: a specific Unsupported Metadata construct with its owning object and source location, or a report file it could not read. It states what was checked, what remains unchecked, and the effect on the Cleanup Recommendation. A shared limitation keeps every item with no use found in scope at Review; a targeted limitation affects only the items it references. Limitations are counted as distinct limitations and affected items, never once per repeated warning.
_Avoid_: Warning occurrence, report problem, unsupported warning

**Analysis Limitations**:
The product surface that lists Analysis Limitations separately from Report Health.
_Avoid_: Unsupported Metadata group, Report Health warnings

**Parent-Table Consumer**:
A retained DAX expression outside a table that references the table itself (for example `ALL('Table')`) rather than one of its items. It blocks whole-table deletion and is shown separately from direct DAX consumers and Report References.
_Avoid_: Column consumer, usage

**Calculation Group Selector**:
The string column of a calculation group table that report authors place in slicers or filters to pick a calculation item.
_Avoid_: Calc group column, field

**Perspective Membership**:
Concrete model metadata stating that a table, measure, column, or hierarchy belongs to a named perspective. It is evidence for a reviewed change, not proof that a report executes the item, and not an Analysis Limitation.
_Avoid_: Perspective usage, perspective dependency

**Translation Membership**:
Concrete culture metadata stating that a table, measure, column, or hierarchy has a translated caption, description, or display folder in a named culture, read from the `translations` block of a culture TMDL file with its source location. It is informational evidence only: it tells the user which translations are removed together with the item, but a translation is just a translation, never a reason to keep an item, so it does not change the Cleanup Recommendation. It is not proof that a report uses the item and not an Analysis Limitation. A culture's `linguisticMetadata` payload is not Translation Membership; it remains an Analysis Limitation owned by the culture.
_Avoid_: Translation usage, translation reference, culture dependency

**Report Health**:
The product surface that explains PBIR problems, stale references, invalid report JSON, and repair opportunities. Model Analysis Limitations are not part of it.
_Avoid_: Warnings, issues list

**Cleanup Action**:
A local change the app can apply to semantic model or report files, such as hiding, moving, renaming, deleting, or repairing references.
_Avoid_: Fix, mutation

**Report Extension Measure**:
A report-level measure defined in PBIR report extension metadata rather than in the semantic model.
_Avoid_: Local measure, report measure
