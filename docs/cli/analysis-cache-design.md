# Analysis reuse: current checks and a persistent cache proposal

## Implemented

Compact queries (`usage`, `items`, `summary`, `review`) and plans that do not
remove Report Extension Measures skip their deletion assessment. Full analysis
and web output explicitly request it; a Report Extension Measure deletion plan
assesses its original scope once before allowing the operation. The staged
analysis still checks reference integrity, without reassessing deletion
eligibility for retained measures.

PBIR schema validation stores process-local evidence keyed by a SHA-256 digest
of the decoded document's JSON serialization and the error limit. The schema
registry identity controls the cache lifetime. Validation is independent of the
file path, so a snapshot, deletion assessment and staged copy can share a result.
Results are copied before returning and get the caller's own path. Original-byte
hashes in plan inventories remain unchanged. Strict duplicate-key and non-JSON
numeric checks in deletion assessment still run before cache access.

Only digests and evidence are retained, not source documents. Evidence lives
until process exit or registry replacement; memory therefore grows with distinct
document versions checked by a long-running web process. No disk cache is read
or written. A lock prevents concurrent calls from duplicating a schema check.

Opaque reference matching folds metadata strings once per file and measure
spellings once per Report. It preserves separate strings, Unicode casefolding,
substring matches and escaped closing brackets; combining strings into a blob
could invent references crossing string boundaries.

## Measurements

Single wall-time runs on Linux, Python 3.14, using the same read-only Power BI
Project with one Semantic Model and eight connected Reports. Each command starts
a new process; this is not a persistent-cache speedup. Baseline is `40c5379`
(latest origin/main when the branch was created). Plan output and staging are
outside the fixture, with staging on disk rather than the small `/tmp` tmpfs.

| Command | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| `usage` for one column | 35.225 s | 7.862 s | 77.7% |
| `items` | 32.998 s | 7.647 s | 76.8% |
| `plan` for one column rename | 89.731 s | 40.670 s | 54.7% |

The two compact-query JSON outputs are identical. The rename plans have identical
input and output hashes, 185 file changes, operations, coverage and validation
records. Identity and creation-time fields are naturally different. Timings are
observations on this fixture and machine, not CI performance thresholds.

## Deferred: persistent read-only analysis cache

A cache under `SMC_USER_DIR` could avoid repeated full analysis for agents, but
file size/mtime alone cannot guarantee correctness. An edit can preserve both.
A safe first design should prefer content identity over a quick stat-only hit:

1. Discover the current Semantic Model and Reports and resolve selection before
   lookup. Include canonical roots, selected Reports, known connected Reports,
   excluded/unverified bindings and model-only/partial-scope options in the key.
   Adding or removing a Report or changing its binding invalidates the result.
2. Enumerate current scope files afresh. Hash content and relative paths,
   including additions/deletions, metadata, declared resources and files that
   can change scope classification or Analysis Limitations. Handle unreadable
   files and symlinks conservatively; do not reuse earlier successful coverage.
   A parent-directory timestamp is insufficient. Use consistent snapshots and
   reject changes detected while taking or reading the snapshot.
3. Include the tool/analysis format version, bundled schema identity and all
   analysis options. Persist only a versioned, data-only representation; never
   deserialize executable Python objects. Preserve exact Report ownership,
   graph sets, item types and evidence on a hit.
4. Cache analyzer evidence, not review-policy or baseline decisions. Reapply the
   current policy and baseline for each `check`/`review`. Share the same snapshot
   across `usage`, `items`, `summary` and `check` projections.
5. Keep every mutation authorization fresh: plan creation, apply and deletion
   safety must not trust persisted analysis as their source of truth. Restrict
   initial persistent reuse to read-only queries. Write atomically, bound disk
   usage, and treat malformed, stale or incompatible entries as misses.

Before implementation, demonstrate invalidation for same-size/same-time edits,
new and deleted files/Reports, changed bindings, changing selection, changed
policy/baseline, moved roots, tool/schema updates, concurrent writes, corrupt
entries and native Windows paths. Compare cold/hit results with fresh analysis,
including graph ownership and Analysis Limitations. Measure the cost of fresh
content hashing: it may be acceptable, but should not be assumed negligible.
