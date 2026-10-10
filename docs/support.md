# Supported workflows and validation boundaries

Semantic Model Cleaner is a free, MIT-licensed tool that works on local project files. No account or hosted service is required for analysis or cleanup. Start with a copy of your project or a Git branch, choose one semantic model and its reports, and inspect the selected scope before reviewing changes.

The current public beta is [0.4.0b7](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b7). See the [release notes](releases/0.4.0b7.md) for fixes and verification boundaries.

## Inputs

| Input | Support |
| --- | --- |
| TMDL `.SemanticModel` plus PBIR `.Report` folders | Primary workflow: one selected model and one or more selected reports. Invalid folders and unreadable TMDL are rejected before analysis. Valid empty model/table declarations are supported. |
| UTF-8 BOM-prefixed TMDL | Read-only analysis is supported. All saved changes in a model scope containing a BOM-prefixed TMDL file are withheld in this beta because writer handling is incomplete; older saved previews are also refused. |
| Different model/report directory roots | Supported through explicit path selection |
| Report extension measures | Analyzed separately from semantic model measures; promotion is an explicit workflow |
| PBIX binaries | Not an input format; save the project in the supported text formats first |
| Declared PBIR JSON schemas | Offline checks against a pinned Microsoft schema bundle; unknown/missing declarations remain not validated |
| Legacy report layout without expanded PBIR `definition/` | Incomplete coverage; unsupported format is reported explicitly |
| Service-wide report discovery | Not provided; conclusions cover the reports you select |

## Analysis and editing are different capabilities

| Construct or workflow | Analysis | Change review |
| --- | --- | --- |
| Measures and columns | Direct report references plus supported transitive DAX dependencies | Display folder, visibility and deletion actions; DAX editing for measures/calculated columns |
| Tables | Child items, relationship roles and report usage | Table rename, group annotation and dependency-aware cleanup. Removing the last item in one split file preserves a table retained elsewhere; ambiguous final deletion is blocked. |
| Model relationships, keys, sorting, hierarchies and RLS | Retention/dependency evidence for supported metadata | Inspect dependency impact before removal; unsupported rewrites must not be treated as validated |
| `NAMEOF` field parameters | Supported resolved targets; unresolved/ambiguous patterns produce review evidence | A retained parameter definition protects its targets even when the parameter has no report usage. Remove and verify the definition in a separate reviewed plan before deleting its targets. A parameter that nothing uses is Review by entity type: one reason, and a plan that removes the whole parameter asks for confirmation instead of citing its hidden columns. |
| Calculation groups | Recognized from the `calculationGroup` declaration: table type, calculation items, selector column, perspective membership and retained parent-table DAX consumers are shown. Calculation item expressions, their format strings and selection expressions are listed as Analysis Limitations because they apply to arbitrary measures at runtime | Whole-group deletion is blocked while retained consumers reference the table; a coordinated plan that removes the whole group and every retained consumer is evaluated against the proposed final state, so the group's own dynamic items no longer trip the coverage guard. Dynamic items of any retained group still block, and item-specific reasons (report use) still require review; absence of a reference is not proof of safety. A group that nothing uses is Review by entity type with one reason; a plan that removes the whole group asks for confirmation and does not cite the always-hidden Ordinal column. Deleting a single group column keeps the item-alone reasons |
| KPIs, detail rows, dynamic format strings, data coverage definitions | Detected from actual TMDL declarations only, never from words in names, descriptions or comments. Direct item references inside the expressions are resolved and listed as evidence on the referenced item (a KPI target, status or trend reference is not a DAX dependency of the KPI's measure); the expressions themselves are not evaluated | Referenced items stay at Review; unresolved references keep every unused item at Review |
| Perspectives | Membership is concrete metadata evidence naming the perspective and member; it is informational, not an Analysis Limitation, and not proof of report use | Membership never blocks Safe; an unused member is classified like any other unused item, and removal also removes the perspective member |
| Cultures and translations | `cultures/*.tmdl` is read structurally. Each translated table, measure, column or hierarchy under `translations` (with a translated caption, description or display folder) is Translation Membership: concrete evidence naming the object, the culture and `file:line`. It is informational only: not an Analysis Limitation, not proof of report use, and never a reason to keep an item. Names in captions, descriptions or comments never produce evidence. A `linguisticMetadata` block is an Analysis Limitation owned by its culture; its JSON payload is not parsed and never yields item references | A translation never changes the Cleanup Recommendation; the evidence lists which translations are removed with the item. Linguistic metadata changes no Cleanup Recommendation. Renames and deletions do not yet rewrite culture files; review them after applying |
| Report stale metadata | Stale selectors, formatting rules and supported bookmark projections | Explicit cleanup; broken live references are a separate repair workflow |
| Renames and measure home-table moves | Model/report reference impact | Preview the supported model and selected-report rewrites together |
| Report measure promotion | Origin and report-only dependencies matter | Review the full required dependency set and target identity before applying |

“Unused” means no supported usage was found in the selected scope. It does not mean that every consumer, external report, or dynamic expression has been proven absent. A hidden item can still be required. Hiding changes discoverability; it does not remove the item or its storage.

Analysis limitations are listed on their own surface, separately from Report Health. Each one names the feature, the owning object and source location, what was checked, what remains unchecked and how it affects the Cleanup Recommendation. Counts are distinct limitations and affected items. A shared limitation (for example a calculation item that applies to whichever measure is selected) keeps every item with no use found in scope at Review; a targeted limitation affects only the items it references. They are analysis gaps, not report problems and not invalid Power BI configuration.

Legacy direct-write HTTP routes and `smc clean-stale --apply` are withheld in this beta. Use the shared saved-plan workflow from the UI or CLI. Read-only stale-candidate discovery remains available.

## A complete review

1. Choose the semantic model and connected reports. Check exclusions and warnings.
2. Analyze. Inspect Usage, Issues and Cleanup independently.
3. Open a measure, column or table. Read its definition and both dependency directions.
4. Prepare a change. Review exact files and differences, selected scope and validation limits.
5. Apply the reviewed plan. If input files changed after preview, prepare a fresh plan rather than forcing a stale change.
6. Inspect the receipt and refreshed analysis. Resolve remaining findings; static validation does not establish equivalent Power BI runtime behavior.
7. Use guarded recovery when necessary. Recovery must refuse to overwrite subsequent edits.

Review decisions and naming conventions can be saved in the repository; see [review policy](cli/review-policy.md). Schema scope and versions are described in [offline validation](schema-validation.md). For automation and AI agents, see the [CLI output contract and disposable workflow](cli/README.md) and [CI usage](cli/check.md). Analysis and CI gates should run before automated mutation is considered.

## Installation and reporting problems

Windows users should download the versioned ZIP and checksum from the
[v0.4.0b7 prerelease](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b7),
verify the SHA-256 value, extract the entire ZIP, and run the executable from
the extracted folder. The app opens a local browser UI. Preserve the adjacent
packaged files, including the release manifest, static assets, schemas, and demo
workspace. This public beta is unsigned.

Python users can install the wheel or a source checkout with `python -m pip install .`;
use Python 3.11 or newer. Release CI installs the wheel with
resolved dependencies into a fresh environment outside the checkout and invokes
the shipped `smc` and `smc-web` entry points.

Windows CI builds the ZIP in one job, downloads it outside the checkout in a
separate job, verifies its checksum and launches the EXE without Python on the
child `PATH`. A real browser checks both layouts and their assets, demo
analysis, port fallback, spaces and non-ASCII paths, JSON export, and
plan/apply/verify/restore with byte-exact recovery. Logs, screenshots, checksum
proof, and a machine-readable result are retained as workflow artifacts.

When reporting a problem, include the app version, input format, selected scope, exact error, and a small synthetic reproduction if possible. Do not publish confidential model expressions, report data, credentials, or private file paths. See [security reporting](../SECURITY.md) for vulnerabilities.
