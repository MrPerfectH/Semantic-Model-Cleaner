# Plan: Semantic Model Analyzer Improvements

Enhance `analyze_model_usage.py` to close 12 gaps across TMDL parsing, report scanning, and output quality. The script currently misses `sortByColumn` refs, hierarchies, `isKey`/`isHidden`/inferred columns, page-level filters, drillthrough targets, and `HierarchyLevel` JSON refs. Output lacks table-level summaries, visibility indicators, and safe-to-remove classification.

### Phase 1: TMDL Parsing Enhancements

1. **Extend `ModelItem` dataclass** — Add `is_hidden`, `is_key`, `is_inferred`, `sort_by_column` fields (~line 26)
2. **Parse new column/measure properties** — Extract `isHidden`, `isKey`, `isNameInferred`, `isDataTypeInferred`, `sortByColumn` from the 2-tab-indent property blocks (~lines 164–228)
3. **Parse hierarchies** — New function to extract hierarchy→column mappings from TMDL (`hierarchy` blocks with `level` / `column:` lines)
4. **Track `sortByColumn` as indirect usage** — If Column A is used and sorted by Column B, mark B as `USED (Sort Column)` *(depends on 2)*
5. **Track `isKey` columns as implicitly used** — Key columns get `USED (Key Column)` regardless of report refs *(depends on 2)*
6. **Track hierarchy-level columns** — If a hierarchy is referenced in a report, mark its backing columns as `USED (Hierarchy: <name>)` *(depends on 3 & 8)*

### Phase 2: Report Scanning Enhancements

7. **Scan page-level filters** — Currently `page.json` is only read for `visualInteractions` AND excluded from fallback — page filters fall through both paths entirely. Fix by scanning full `page.json` with `_find_json_refs`, context `"Page Filter"` (~line 322)
8. **Scan `HierarchyLevel` references** — Extend `_find_json_refs` to recognize `HierarchyLevel` JSON objects alongside `Measure`/`Column` (~line 224)
9. **Scan drillthrough target columns** — Parse drillthrough config from `page.json`, emit refs with context `"Drillthrough"` *(depends on 7)*

### Phase 3: Output Enhancements

10. **Add hidden/visible indicator** — New "Hidden" column in `format_full` and `format_unused`; `"isHidden"` in JSON output *(depends on 2)*
11. **Add table-level summary** — New section showing per-table usage percentages, highlighting 0%-usage tables as entirely removable
12. **Add safe-to-remove classification** — New `removal_risk` per item:
    - **Safe**: unused + hidden + not key + not inferred
    - **Likely safe**: unused + visible + no DAX dependents
    - **Caution**: unused + has downstream DAX refs
    - **Do not remove**: inferred columns (auto-generated, can't be manually deleted)

### Relevant files
- `scripts/analyze_model_usage.py` — all code changes
- `scripts/analyze_model_usage.README.md` — documentation updates

### Verification
1. Run on existing TMDL + PBIR files — no regressions in full/unused/json output
2. `sortByColumn`: month-name sorted by month-number → sort column shows `USED (Sort Column)`
3. Hierarchies: date hierarchy in visual → backing columns marked used
4. Page filters: page-level filtered column marked USED
5. Drillthrough: target field columns marked USED
6. `isKey`: key columns show `USED (Key Column)`
7. Table summary: 0%-usage tables highlighted
8. Removal risk: hidden unused → "Safe", inferred → "Do not remove"
9. JSON output includes new fields
10. Unused format: sorted by risk level

### Decisions
- **Folder selection**: `--models-path` / `--reports-path` are sufficient — no CLI changes needed
- **Inferred columns**: annotated "Do not remove" rather than excluded from output
- **Deferred**: `summarizeBy`, field parameters (NAMEOF), `--output` flag — future iteration
