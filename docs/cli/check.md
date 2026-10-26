# Read-only CI checks

`smc check` runs the same local TMDL/PBIR analyzer used by the app. It makes no model/report edits and requires no Power BI Desktop, cloud service, or paid dependency. It validates supported static references, not report rendering or model query results.

```sh
smc check ./project --format json
smc check ./project --model-path Models/Sales.SemanticModel --report-path Reports/Executive.Report
smc check ./project --model Models/Sales.SemanticModel --fail-on warning
smc check ./project --report Executive --report Operations
smc check ./project --write-baseline smc-baseline.json
smc check ./project --baseline smc-baseline.json
```

`--model` is an artifact path relative to the project directory (an absolute path also works). Without it, exactly one discovered semantic model is required. Report discovery is under the project directory. Repeatable `--report` arguments are case-insensitive name substring filters, applied to reports bound to the selected model. Unmatched selection is an input error. `--format` defaults to `json`; `text` is intended for interactive use.

For new scripts, `--model-path` and repeatable `--report-path` select exact folders
relative to PROJECT (absolute paths also work). These options work consistently
across project commands. The `--model`/`--report` behavior above is retained for
compatibility; do not mix selectors for the same artifact type. See the
[selection and migration guide](README.md#recommended-exact-selection).

Exit codes:

| Exit | Meaning |
|---|---|
| 0 | No unsuppressed findings meet the configured failure threshold. |
| 1 | Findings meet the failure threshold. |
| 2 | Invalid arguments, invalid baseline, unusable input scope, or analysis failure. |

In JSON mode (the default), argument syntax and runtime failures return the existing JSON envelope on stdout with `ok: false`, `errors`, and exit 2. `--format text` keeps argparse usage errors on stderr. `--help` always prints text and exits 0. See the [CLI contract](README.md) for stream and compatibility details.

`--write-baseline` requires an existing external output directory. Selected,
discovered, and named Semantic Model/Report folders are protected, including
resolved aliases and excluded artifacts. Existing output files with multiple
hard links are refused because they may alias project metadata; choose a new
external filename. Ordinary external baseline files can still be overwritten.

By default only error findings fail the check. `--fail-on warning` also fails on warnings, including items with no found usage. A pass does not mean the model has no unused items or that every possible consumer was inspected.

## JSON contract, version 1.0

The envelope has `schema_version`, `command`, `ok`, `scope`, `findings`, `summary`, and `errors`. Findings contain `rule_id`, `severity`, `message`, `path`, `table`, `name`, `location`, `fingerprint`, and `suppressed`. Consumers should use rule IDs and structured fields rather than parse message wording. New fields may be added; incompatible changes require a version change.

Paths in successful result scope and findings are relative to the project directory using forward slashes; artifacts outside that directory can contain `..`. Finding order and fingerprints are deterministic across moved copies of the same project. The fingerprint hashes the rule, relative path, item identity, and reference location; it does not include absolute paths, timestamps, or prose.

`scope` reports the selected model/reports, all discovered report binding states, selected and known-bound counts, whether all known bound reports were selected, unverified report count, and `scan_complete`. `external_consumers_verified` is always false. A connection matched by published model name is identified as `connected_by_name`; it is not equivalent to verified remote identity. Deliberately excluded reports remain visible in scope. An unverified discovered binding produces SMC008 because the excluded report might use the selected model.

`scan_complete` means no detected unreadable report file or unresolved unsupported model metadata in the selected scan. It does not claim exhaustive format conformance. Unsupported metadata with resolved target names still produces a warning.

Each `scope.bindings` row includes its classification `message`. Binding evidence
is retained when discovery succeeds but the selected Report set is empty or
unusable, so invalid-scope responses can still explain the exclusions. A
definition containing both populated `byPath` and `byConnection` is
`ambiguous_definition` and excluded consistently with the app and ordinary
analysis. Null alternatives are ignored; empty or malformed alternatives still
follow the existing binding validation.

| Rule | Default severity | Meaning |
|---|---|---|
| SMC001 | error | Broken DAX reference in a model or report extension item. |
| SMC002 | error | Report JSON could not be parsed or read; scan incomplete. |
| SMC003 | error/warning | Unsupported model metadata; error when target coverage is unresolved, warning when detected targets can be identified. |
| SMC004 | warning | No item usage found in selected scope; includes cleanup recommendation. |
| SMC005 | warning | Stale report metadata reference. |
| SMC006 | source severity | Other Report Health issue, including missing references. |
| SMC007 | warning | Analyzer warning, such as unresolved field parameter targets. |
| SMC008 | error | A discovered report has an unverified binding and was excluded. |
| SMC009 | warning | Naming policy proposes a change. |
| SMC010 | error | Naming policy has conflicting targets. |
| SMC011 | error | Declared Report schema validation failed or its errors were truncated. |
| SMC012 | warning | JSON metadata has no supported declared schema validation. |

## Repository gates and Markdown summaries

An optional `ci_gate` in `.smc-policy.json` can make naming findings block CI
while unused-item findings stay advisory, or fail specifically on unused items
with a selected Cleanup Recommendation. It can independently require complete
dependency analysis, complete JSON schema validation, and all known connected
Reports. See [gate settings and precedence](review-policy.md#ci-gates). Findings
retain their severity, identity and scope; `gate.blocking` and `gate.reason`
explain the effective decision. The check and focused review use the same gate:
`smc review` accepts the same `--policy` (relative to PROJECT) and `--baseline`
(relative to CWD) with the same validation, so both commands reach the same verdict.

```sh
smc check ./bi --format json --summary-output smc-summary.md > smc-findings.json
```

`--summary-output` writes a UTF-8 Markdown companion, leaving JSON stdout and the
check exit code unchanged. A findings/requirement failure is distinct from an
input/execution failure. Selected/excluded Reports, coverage, gate outcomes,
suppressed/reviewed findings and available source locations remain visible.
Report Health and Analysis Limitations have separate sections.

Metadata is escaped; at most 200 findings, 100 entries per scope collection and
20 execution errors are shown. Each metadata field is capped at 800 characters
after escaping; `@` and `$` are written as HTML entities so a pasted summary cannot
mention people or render math.
Truncation/omission is explicit; use JSON for full details. The summary does not
include entire model expressions, but can contain confidential names and paths.
It is written for handled input/execution errors after argument parsing succeeds;
argument syntax errors do not create a summary.

Use an existing external output directory. Artifact folders and resolved aliases
are protected. A summary cannot overwrite policy, baseline input, or baseline
output; existing multiply-linked outputs are refused. Unsafe destinations or
summary write failures return exit 2. The CLI does not post comments or upload data.

## Baselines

A baseline is `{ "schema_version": "1.0", "fingerprints": ["..."] }`. `--write-baseline` writes the current eligible fingerprints; it does not change the current check's exit code. Commit the file after reviewing the findings, then use `--baseline` in CI. Suppressed findings remain in output and counts. SMC002, SMC003, SMC008, SMC010, SMC011 and SMC012 cannot be baselined, so accepted debt cannot hide missing coverage or protected validation failures. A baseline is not a deletion authorization. Baseline output must be outside Semantic Model and Report artifact folders; symlink destinations are checked too.

## Shared deletion policy

`cleanup_policy.evaluate_deletion_policy(model_path, report_paths, actions)` returns:

```json
{"ok": false, "errors": ["..."], "violations": [{"rule_id": "SMC-D004", "table": "Sales", "name": "Revenue", "message": "..."}], "scope": {"model": "...", "reports": [], "complete": false}}
```

The function only reads files. Non-delete batches bypass it. Delete batches require a fresh analysis of an existing model and selected bound PBIR reports. Reasons are SMC-D001 invalid/unverified scope, D002 incomplete scan, D003 absent target, D004 used/broken/inferred item, D005 Review recommendation, and D006 retained dependency. An unused DAX dependency chain can pass when every dependent is also deleted; retained sort-by/hierarchy/bare-table dependencies remain protected.

Call it for both preview and apply. The owning transaction layer must also validate source hashes, show the complete diff, and validate/rollback mutations. Policy success is neither a persistent authorization token nor proof that remote consumers are unaffected.

## Observed performance sample

On 2026-09-07, a disposable generated project was measured on this development machine (macOS arm64, Python 3.13.13). It contained 2,000 model items across 20 tables: 1,000 measures, 1,000 columns including 100 calculated columns, short measure dependency chains, 19 relationships, and one RLS role. Five bound reports contained 50 pages, 500 visuals, and 1,000 live references; 582 metadata files were scanned.

Three in-process repetitions took 0.200/0.185/0.192 seconds for `analyze` (median 0.192 s) and 0.271/0.264/0.261 seconds for `run_check` including discovery and finding generation (median 0.264 s). The default check exited 0 with 838 warning findings and complete detected scan coverage. No original user project was read or modified by this benchmark; the generated project was automatically deleted.

These are observations for one synthetic fixture, not a performance guarantee. They exclude process startup, browser rendering, JSON printing, plan generation, filesystem latency on network drives, and Power BI runtime validation. Real projects with larger DAX expressions or additional metadata should be measured separately.

## GitHub Actions example

This assumes the model/report project is under `bi/` with a reviewed
`.smc-policy.json`. Replace that path and the tool ref placeholder with a reviewed
commit containing the new gate/summary features. Older beta tags do not provide
these options. Keep that ref pinned so behavior cannot change between runs.

```yaml
jobs:
  semantic-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: MrPerfectH/Semantic-Model-Cleaner
          ref: '<reviewed-commit-containing-this-feature>'
          path: .tools/smc
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: python -m pip install ./.tools/smc
      - run: smc check ./bi --format json --summary-output smc-summary.md > smc-findings.json
      - name: Show check summary
        if: always()
        run: |
          if [ -f smc-summary.md ]; then
            cat smc-summary.md >> "$GITHUB_STEP_SUMMARY"
          fi
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: semantic-check
          path: |
            smc-findings.json
            smc-summary.md
```

## Azure Pipelines example

This example checks out the reviewed tool commit from GitHub, then scans only
`bi/` in the calling repository. Replace the project path and ref placeholder.
It publishes findings and displays the summary even when the policy gate fails.

```yaml
pool:
  vmImage: ubuntu-latest
steps:
  - checkout: self
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.13'
  - bash: |
      set -euo pipefail
      git clone https://github.com/MrPerfectH/Semantic-Model-Cleaner.git .tools/smc
      git -C .tools/smc checkout '<reviewed-commit-containing-this-feature>'
      python -m pip install ./.tools/smc
    displayName: Install reviewed Semantic Model Cleaner
  - bash: |
      mkdir -p smc-results
      smc check ./bi --format json --summary-output smc-results/summary.md > smc-results/findings.json
    displayName: Check model and report references
  - bash: |
      if [ -f smc-results/summary.md ]; then
        echo "##vso[task.uploadsummary]$PWD/smc-results/summary.md"
      fi
    condition: always()
    displayName: Show check summary
  - task: PublishPipelineArtifact@1
    condition: always()
    inputs:
      targetPath: smc-results
      artifact: semantic-check
```

Add `--baseline smc-baseline.json` only after reviewing and committing the baseline. These examples perform read-only checks; automated apply should consume a separately reviewed plan.
