# Supported workflows and validation boundaries

Semantic Model Cleaner is a free, MIT-licensed tool that works on local project files. No account or hosted service is required for analysis or cleanup. Start with a copy of your project or a Git branch, choose one semantic model and its reports, and inspect the selected scope before reviewing changes.

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
| `NAMEOF` field parameters | Supported resolved targets; unresolved/ambiguous patterns produce review evidence | A retained parameter definition protects its targets even when the parameter has no report usage. Remove and verify the definition in a separate reviewed plan before deleting its targets. |
| Calculation groups and broader dynamic indirection | Incomplete coverage | Review required; do not interpret absence of a reference as proof of safety |
| Report stale metadata | Stale selectors, formatting rules and supported bookmark projections | Explicit cleanup; broken live references are a separate repair workflow |
| Renames and measure home-table moves | Model/report reference impact | Preview the supported model and selected-report rewrites together |
| Report measure promotion | Origin and report-only dependencies matter | Review the full required dependency set and target identity before applying |

“Unused” means no supported usage was found in the selected scope. It does not mean that every consumer, external report, or dynamic expression has been proven absent. A hidden item can still be required. Hiding changes discoverability; it does not remove the item or its storage.

Legacy direct-write HTTP routes and `smc clean-stale --apply` are withheld in this beta. Use the shared saved-plan workflow from the UI or CLI. Read-only stale-candidate discovery remains available.

## A complete review

1. Choose the semantic model and connected reports. Check exclusions and warnings.
2. Analyze. Inspect Usage, Issues and Cleanup independently.
3. Open a measure, column or table. Read its definition and both dependency directions.
4. Prepare a change. Review exact files and differences, selected scope and validation limits.
5. Apply the reviewed plan. If input files changed after preview, prepare a fresh plan rather than forcing a stale change.
6. Inspect the receipt and refreshed analysis. Resolve remaining findings; static validation does not establish equivalent Power BI runtime behavior.
7. Use guarded recovery when necessary. Recovery must refuse to overwrite subsequent edits.

Review decisions and naming conventions can be saved in the repository; see [review policy](cli/review-policy.md). Schema scope and versions are described in [offline validation](schema-validation.md). For automation, see [CI usage](cli/check.md). Analysis and CI gates should run before automated mutation is considered.

## Installation and reporting problems

Windows users should download the versioned ZIP and checksum from the
[v0.4.0b1 prerelease](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b1),
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
