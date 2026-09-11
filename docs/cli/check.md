# Read-only CI checks

`smc check` runs the same local TMDL/PBIR analyzer used by the app. It makes no model/report edits and requires no Power BI Desktop, cloud service, or paid dependency. It validates supported static references, not report rendering or model query results.

```sh
smc check ./project --format json
smc check ./project --model Models/Sales.SemanticModel --fail-on warning
smc check ./project --report Executive --report Operations
smc check ./project --write-baseline smc-baseline.json
smc check ./project --baseline smc-baseline.json
```

`--model` is an artifact path relative to the project directory (an absolute path also works). Without it, exactly one discovered semantic model is required. Report discovery is under the project directory. Repeatable `--report` arguments are case-insensitive name substring filters, applied to reports bound to the selected model. Unmatched selection is an input error. `--format` defaults to `json`; `text` is intended for interactive use.

Exit codes:

| Exit | Meaning |
|---|---|
| 0 | No unsuppressed findings meet the configured failure threshold. |
| 1 | Findings meet the failure threshold. |
| 2 | Invalid arguments, invalid baseline, unusable input scope, or analysis failure. |

Argparse syntax errors and `--help` follow normal CLI behavior (stderr usage with exit 2, help with exit 0). Runtime failures in JSON mode return a JSON envelope with `ok: false` and `errors`.

By default only error findings fail the check. `--fail-on warning` also fails on warnings, including items with no found usage. A pass does not mean the model has no unused items or that every possible consumer was inspected.

## JSON contract, version 1.0

The envelope has `schema_version`, `command`, `ok`, `scope`, `findings`, `summary`, and `errors`. Findings contain `rule_id`, `severity`, `message`, `path`, `table`, `name`, `location`, `fingerprint`, and `suppressed`. Consumers should use rule IDs and structured fields rather than parse message wording. New fields may be added; incompatible changes require a version change.

Paths in successful result scope and findings are relative to the project directory using forward slashes; artifacts outside that directory can contain `..`. Finding order and fingerprints are deterministic across moved copies of the same project. The fingerprint hashes the rule, relative path, item identity, and reference location; it does not include absolute paths, timestamps, or prose.

`scope` reports the selected model/reports, all discovered report binding states, selected and known-bound counts, whether all known bound reports were selected, unverified report count, and `scan_complete`. `external_consumers_verified` is always false. A connection matched by published model name is identified as `connected_by_name`; it is not equivalent to verified remote identity. Deliberately excluded reports remain visible in scope. An unverified discovered binding produces SMC008 because the excluded report might use the selected model.

`scan_complete` means no detected unreadable report file or unresolved unsupported model metadata in the selected scan. It does not claim exhaustive format conformance. Unsupported metadata with resolved target names still produces a warning.

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

## Baselines

A baseline is `{ "schema_version": "1.0", "fingerprints": ["..."] }`. `--write-baseline` writes the current eligible fingerprints; it does not change the current check's exit code. Commit the file after reviewing the findings, then use `--baseline` in CI. Suppressed findings remain in output and counts. SMC002, SMC003, and SMC008 cannot be baselined, so accepted debt cannot hide missing coverage. A baseline is not a deletion authorization. Baseline output must be outside Semantic Model and Report artifact folders; symlink destinations are checked too.

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

This assumes the model/report project is under `bi/`. Replace that path. The
example pins the public beta tag so tool behavior cannot change between runs.

```yaml
jobs:
  semantic-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: MrPerfectH/Semantic-Model-Cleaner
          ref: 'v0.4.0b1'
          path: .tools/smc
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: python -m pip install ./.tools/smc
      - run: smc check ./bi --format json > smc-findings.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: semantic-check
          path: smc-findings.json
```

## Azure Pipelines example

This example checks out the public beta tag from GitHub, then scans only `bi/`
in the calling repository. Replace the project path. The final step publishes
findings even when the policy gate fails.

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
      git -C .tools/smc checkout 'v0.4.0b1'
      python -m pip install ./.tools/smc
    displayName: Install reviewed Semantic Model Cleaner
  - bash: smc check ./bi --format json > smc-findings.json
    displayName: Check model and report references
  - task: PublishPipelineArtifact@1
    condition: always()
    inputs:
      targetPath: smc-findings.json
      artifact: semantic-check
```

Add `--baseline smc-baseline.json` only after reviewing and committing the baseline. These examples perform read-only checks; automated apply should consume a separately reviewed plan.
