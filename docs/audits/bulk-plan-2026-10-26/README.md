# Bulk-plan verification for issue #169

The performance implementation is already integrated: commit
`39507ca40f31f68416d78c604269405ea7fe4046`, merged through
[PR #172](https://github.com/MrPerfectH/Semantic-Model-Cleaner/pull/172).
The older issue comment describing an unpublished MSI commit is superseded.
This follow-up supplies a shareable successful fixture and reproducible evidence;
it does not introduce another cache or remove validation.

## Workload and reproduction

Run from the repository with its development dependencies installed:

```bash
PYTHONPATH=src python scripts/benchmark_bulk_plan.py /path/to/new/bulk-run
PYTHONPATH=src python scripts/benchmark_bulk_plan.py /path/to/new/bulk-profile --profile
```

Both paths must be new. The script generates synthetic files only: one Semantic
Model, 40 tables, 1,960 items, eight connected Reports, 160 pages and 5,067 card
visuals. One `actions` operation contains 787 delete actions (275 unused measures
and 512 unused columns), spread over all tables. Retained visuals reference a
retained measure. This is a successful representative batch, not a reconstruction
of private PMRA expressions or the previously failed described-table case.

Fixture generation, apply, verification and restore are outside the planning
timer. The script checks that planning never edits inputs, actually applies and
verifies all 787 deletions, then restores every source byte. `benchmark.json`
contains phase wall/process-CPU times, read counts, validation and equivalence
hashes. `--profile` also saves `planning.pstats` and its top cumulative functions;
profiler times have overhead and are not comparable with unprofiled samples.
Phase timings are inclusive: analysis within policy evaluation can overlap other
rows, so do not add them together.

To run the same harness against the pre-optimization source without changing the
working checkout:

```bash
mkdir /path/to/new/before-source
git archive 4b44ed7cafcfd2b556d4942c135bd7286a6cef17 src/semantic_model_cleaner |
  tar -xf - -C /path/to/new/before-source
PYTHONPATH=/path/to/new/before-source/src python scripts/benchmark_bulk_plan.py /path/to/new/before-run
```

Use the same interpreter and dependencies for both runs. The harness adapts only
optional discovery arguments introduced after the historical revision; it does
not bypass any engine safety checks. Compare `equivalence` in the two JSON files,
not plan IDs, absolute scope paths or timestamps.

## Measured evidence

Recorded 2026-10-26 on Linux x86_64, Python 3.14.7, Intel Core i5-8365U,
eight logical CPUs. Generated projects were on `/dev/shm` (tmpfs); staging used
the local home cache. Before source: `4b44ed7cafcfd2b556d4942c135bd7286a6cef17`.
Current source: main `83fb425` plus this follow-up's discovery guard. This compares
the historical source with current behavior, including intervening safety/scope
changes, rather than isolating the cache commit alone.

| Unprofiled planning metric | Before | Current |
| --- | ---: | ---: |
| Wall seconds | 53.420 | 15.535 |
| Process CPU seconds | 53.027 | 15.451 |
| `Path.read_text` calls | 125,855 | 13,368 |
| `Path.read_bytes` calls | 16,793 | 16,879 |
| Plan-analysis CPU seconds, two calls | 15.729 | 1.200 |
| Deletion-policy CPU seconds, one call | 3.131 | 1.149 |
| Staged-writer CPU seconds, one call | 11.423 | 0.502 |
| Schema-validation CPU seconds, two calls | 18.559 | 8.470 |
| Changed files | 40 | 40 |

These are single local samples. The before run overlapped focused tests; other
machine activity was not controlled. They establish reproducibility and reduced
repeated work on this fixture, not a guaranteed production speedup or a revised
timing for MSI/PMRA. The previous PMRA CPU/read-count evidence in PR #172 remains
separate; its wall timings also overlapped other work.

The separate cProfile runs identify the repeated work. Before optimization,
19 `analyze` calls consumed 67.714 cumulative seconds, schema validation 53.078
and staged `apply_actions` 31.023 (inclusive, profiled wall seconds). Current
planning calls `analyze` three times; model parses fall from 38 to four and
`validate_document` calls from 10,486 to 5,243. Current schema validation remains
the largest measured phase at 23.624 profiled seconds, rather than repeated
writer reads. The raw [before](before.json), [current](after.json),
[profiled before](profile-before.json) and [profiled current](profile-after.json)
records include the full measurements and top cumulative functions. These
profiles verify the integrated change retrospectively; the original pre-fix
profiling is described in commit `39507ca` and PR #172.

All four equivalence hashes match between revisions and the separate profiled
runs: inputs, outputs, complete file changes (including reviewed bytes/diffs) and
the complete validation object. Both revisions report zero existing or remaining
reference problems, 5,227 schema-valid documents before and after, zero invalid
documents and 16 unchanged documents without supported declared schemas. These
16 are the generated `definition.pbir` and minimal `report.json` files; they are
explicitly recorded as not validated. No DAX execution, refresh or report-rendering
equivalence is claimed.

The immutable per-plan AnalysisCache in PR #172 shares baseline work with the
deletion policy, uses a separate staged cache, reuses writer file reads and memoizes
unchanged schema documents. Existing work-count/byte-equivalence tests in
`tests/test_bulk_plan_performance.py` guard these mechanisms. The new harness and
its small regression case in `tests/test_bulk_benchmark_script.py` add a portable
successful end-to-end workload and timing evidence.

Developer saved DAX queries and editor state remain outside cleanup scope, as
required by [PR #175](https://github.com/MrPerfectH/Semantic-Model-Cleaner/pull/175).
This benchmark does not reintroduce them. It validates supported static metadata;
it does not assess whether a calculation gives the intended business result.
