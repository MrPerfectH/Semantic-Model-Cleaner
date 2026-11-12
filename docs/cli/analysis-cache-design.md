# Content-verified analysis reuse

## Cache contract

Commands with an explicit resolved Semantic Model and Report scope reuse analysis
under `SMC_USER_DIR/analysis-cache` (normally
`~/.semantic-model-cleaner/analysis-cache`). This includes `items`, `usage`,
`summary`, `check`, `review`, and the original-scope analysis used by planning.
Discovery and Report binding selection still run before query projections.

A cache key includes:

- Canonical model and selected Report paths, directory names, file modes and
  SHA-256 content hashes of every file in those artifacts, including resources.
- Current model/Report discovery and the `definition.pbir` contents of discovered
  Reports, including unselected and unverified Reports. Search roots must remain
  available. Adding a Report or changing a binding cannot silently reuse an old
  selection's evidence.
- Analysis options, model-only mode, excluded/unverified selection facts, the
  deletion-evidence option, and whether repair suggestions were requested.
- Cache format, Python/dependency versions, tool source and bundled schema
  contents. Frozen distributions also fingerprint their executable.

File size/mtime is never accepted as proof of unchanged content. The current
contents are hashed twice around a cache read or analysis calculation. File
mtime/ctime/inode observations additionally reject edits during those reads,
including a change restored to its original bytes. An invocation's parsed-input
cache is cleared when its content key changes, preventing a new snapshot from
being populated with an earlier snapshot's parsed items.

The cache contains checksummed, compressed JSON, with explicit data tags for
model items, Report References, tuple graph keys and sets. It never unpickles
Python or imports a class named by a cache file. Record types come from a fixed
local registry. Every hit returns independent objects; later query enrichment
cannot mutate persisted evidence. Entries have compressed/expanded size bounds,
atomic writes and a 32-entry retention bound. Missing, corrupt, incompatible or
unwritable entries fall back to fresh analysis. Symlink scopes are not cached.
Cache directories inside selected artifacts are refused, so caching cannot
write project metadata into a Semantic Model or Report.

These are local user-owned performance artifacts, containing model expressions,
names and location evidence. They can be deleted without affecting source files,
plans or recovery journals. Set `SMC_DISABLE_ANALYSIS_CACHE=1` to bypass persistent
reuse and its writes for comparison or troubleshooting.

## Mutation and policy boundaries

A cache hit is evidence for the exact current content snapshot, not an approval
token. Plan creation still checks deletion policy, binding/scope completeness,
TMDL writer eligibility and JSON/schema validity. The changed staged scope is
always analyzed afresh and compared for new unresolved references. Apply and
verify still hash source files against the reviewed plan; they never replace
those checks with cached analysis. The cache does not store review-policy or
baseline decisions: `check` and `review` reapply current inputs every time.

Compact queries and ordinary refactoring plans skip Report Extension Measure
deletion assessment. Full analysis/web output request it explicitly, and a Report
Extension Measure deletion plan assesses its original scope before deletion.
This distinction is part of the cache key.

PBIR schema validation separately retains process-local evidence keyed by
normalized document content, error limit and schema registry. Snapshots,
assessment and staged copies share those checks within one process. Strict
JSON/duplicate-key checks and original-byte plan fingerprints are unaffected.
Schema evidence is not currently persisted across CLI invocations.

## Validation

Regression coverage compares cold and cached evidence, item/usage projections,
plan validation and staged edits. It exercises same-size/same-time edits,
new/deleted metadata, newly discovered Reports, changed bindings and selection,
engine/schema changes, corrupt entries, caller mutations and edits during cache
reads. Domain tests bypass persistent reuse so safety tests still exercise fresh
analysis; dedicated cache tests enable isolated temporary state.

Wall-time measurements and PMRA cleanup results for this change are recorded in
`bulk-cleanup-benchmark.md`. They distinguish cold and repeated commands and
compare cached/uncached outputs, rather than treating a cache hit as a relaxation
of any cleanup guard.
