# Bulk cleanup benchmark and acceptance

## Method

Measured on the read-only PMRA fixture copied to a writable directory under
`~/.cache/smc-bulk-cleanup`, with staging there instead of the small `/tmp` tmpfs.
Linux, Python 3.14.7; one Semantic Model and eight connected Reports. The fixture
itself was never modified. The starting branch was `perf/cli-agent-speed` at
`c7b8b69`. Each timed command ran in a separate process.

The before plan combines the 823 approved deletion actions from the benchmark's
three-round cleanup. The new command constructs its own guarded closure and
whole-table actions, so those two plan timings are not identical workloads.
Cached/uncached comparisons below use identical current commands and inputs.

| Command | Before (`c7b8b69`) | Current repeated command | Current cache disabled |
| --- | ---: | ---: | ---: |
| `items --unused --all` | 10.102 s | 5.344 s | 5.526 s |
| `usage` (one column) | 9.182 s | 5.384 s | 5.222 s |
| cleanup plan | 62.679 s | 46.479 s | 41.918 s |
| `verify` after apply | 2.284 s | 1.324 s | 1.305 s |

The current cold `items` invocation took 9.183 s. Apply took
3.020 s. Verify always computes fresh source hashes; it does not use analysis
reuse. These are single wall-time observations, not CI performance thresholds.
The cache prevents re-analysis, but its content hashing and serialization are
not free: on this fixture it adds plan overhead versus the current cache-disabled
command. Schema checks and staged validation remain uncached across processes.
The main workflow improvement is one supported plan instead of repeated retries
and successive apply/analyze rounds.

## Output equivalence and safety

- Cold, cached and cache-disabled item JSON are identical. Cached and uncached
  usage JSON are identical.
- Current cached/uncached plans have identical operations, input/output hashes,
  exact changes, coverage, validation and cleanup evidence. Only plan identity,
  creation time and seal naturally differ.
- The first plan for **all 751 current Safe items** succeeded with no retries.
- The cascade emitted one plan with 809 actions, removing
  **810 model items and 11 tables**, including all three
  unused Scorecard calculated tables. Their inferred columns were removed with
  their partitions rather than individually.
- Apply and verify passed. The post-apply listing contains no Safe model items.
  It retains 4 hidden-only Review items by default. `Report View[value]`
  remains used, with 8 live locations despite Report references spelling `Value`.
- The benchmark's independent oracle passes every safety check: no required item
  deleted, no dangling dependency in a retained item, retained item blocks and
  non-item metadata unchanged, and no Report/collateral changes. It counts
  810 removed unused items out of 843 oracle-unused items
  (96.1%); the rest require Review or remain conservatively protected.

## Difference from the older 823-item cleanup

The new guards retain unresolved visual-property bindings and their dependency
chains, plus a table anchor for the unresolved webUrl entity. They do not force
an old deletion count. Relative to the old 823-action set, 18 prior actions are
kept and five previously kept columns are now removed: four inferred columns
from the three whole calculated tables, and a different removable column in
`page_URL`. The net result is 810 removals. `page_URL` itself and the model URL
measure remain, so the existing unresolved binding is not turned into a missing
table or a deleted potential measure target.

The saved plan's unused-kept report contains 68 items with concrete rule and
location evidence. It distinguishes hidden-only Review, inferred columns,
Tool Entities, calendar/detail-rows declarations, retained Review consumers,
and unresolved visual-property bindings. The latter need explicit binding
review; no model change or Report repair is inferred from similar names.

## Agent command

```text
smc plan PROJECT --model-path PMRA_Semantic_Models/PMRA_POC.SemanticModel --cleanup unused --cascade -o cleanup-plan.json --format json
```

Review `smc diff cleanup-plan.json`, then use the existing apply/verify workflow.
Add `--include-review` only to approve hidden-only Review; every other guard
remains. No operations-generation script or retry loop is required.
