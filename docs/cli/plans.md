# Reviewed changes from the CLI

The CLI and local web UI use the same change-plan engine. A plan stages operations on temporary copies, records exact file differences, and checks supported references before any selected input file is edited. Applying the plan writes its reviewed output bytes after checking that the inputs still match.

Use plans generated locally from files you trust. A plan contains absolute paths, original and replacement metadata, file fingerprints, and a digest. The digest detects accidental editing; it is not a signature or proof that a plan came from a trusted author. Do not apply downloaded or untrusted plans. Plans and journals can contain model expressions and other confidential metadata.

Legacy mutation HTTP routes and `smc clean-stale --apply` cannot bypass this workflow in the beta. Their direct-write requests are rejected with guidance to prepare and apply a saved plan.

## First change

Create `operations.json` outside discovered or selected model/report folders:

```json
{
  "operations": [
    {
      "kind": "actions",
      "actions": [
        {
          "action": "hide",
          "table": "Sales",
          "name": "Revenue",
          "item_type": "Measure"
        }
      ]
    }
  ]
}
```

Prepare and inspect the plan:

```bash
smc plan /path/to/project \
  --model /path/to/project/Models/Sales.SemanticModel \
  --report /path/to/project/Reports/Executive.Report \
  --operations operations.json \
  --output review/hide-revenue.plan.json

smc diff review/hide-revenue.plan.json
```

`plan` writes only the output plan, not the selected model/report files or a backup. Its stdout is a JSON summary containing the plan ID, output path, changed-file count, and validation result. Review the plan's scope, operations, coverage and validation as well as the diff.

Apply and verify the reviewed result:

```bash
smc apply review/hide-revenue.plan.json
smc verify review/hide-revenue.plan.json
smc history
```

Apply records a recovery journal automatically. There is no `--no-backup` option for this workflow. The saved original bytes in the plan provide the recovery source; this is not a full copy of every file in the project.

## Scope and storage

- `plan [project_path]` defaults to the current directory. Without `--model`, it must discover exactly one model beneath that path.
- For this command, `--model` and each repeated `--report` are exact folder paths, unlike the analyzer's name filters. Relative paths resolve from the current working directory.
- Without explicit `--report` arguments, planning selects discovered reports bound to the chosen model. At least one report is required. Refactoring additionally requires supported report bindings and complete supported scan coverage.
- The model must have a TMDL `definition` directory; reports must have PBIR `definition` directories. Artifact roots must be distinct and cannot contain one another. Symlinks within the selected scope are rejected.
- The snapshot covers `.tmdl`, `.json`, `.pbir` and `.pbism` metadata. Other project files are outside its fingerprint and recovery scope.
- Plan output must be outside discovered or selected model/report folders and must not overwrite the operations file.
- Journals default to `~/.semantic-model-cleaner/plans`. Setting `SMC_USER_DIR` changes the default to `<SMC_USER_DIR>/plans`. `apply`, `verify`, `restore`, `recover-lock` and `history` accept `--journal-dir`; verification itself reads the plan and files, not the journal.
- Use the same journal directory for operations on the same model. The per-model lock resides there; separate journal directories do not provide a shared lock. Keep journals outside selected artifacts and retain them until recovery is no longer needed.

## Operation format

The operations file accepts either an array or an object containing `operations`. The array must be nonempty. Operations run in order on staged copies, so later operations must use identities established by earlier ones.

| Kind | Fields | Effect |
| --- | --- | --- |
| `actions` | `actions` array | Display folder, hidden state, deletion, or table-group changes through the existing action engine |
| `rename` | One or more of `table_renames`, `measure_renames`, `column_renames` | Rename model metadata and rewrite supported selected-report references |
| `move` | `moves` array | Move measures to another home table and rewrite supported selected-report references |
| `promote` | `table`, `name`; optional `report_path`, `target_table`, `target_name`, `include_dependencies`, `allow_metadata_loss` | Promote a report extension measure, with explicit dependency/metadata-loss decisions |
| `dax` | `table`, `name`, `item_type`, `dax_expression`; optional `source_file` | Replace a supported measure or calculated-column expression |
| `clean_stale` | `entries` array | Remove supported stale PBIR metadata using exact analyzer locations |
| `report_issues` | `entries` array | Apply explicit report-reference replacements or removals |
| `report_repair` | Rename arrays as above | Rewrite report references only; do not rename the model |

An optional operation-level `report_paths` restricts report work to a subset of the plan's selected reports. It cannot introduce an outside report. Explicit `report_path` and `source_file` values must be absolute paths within the selected artifacts. Report `artifact_path` values must be relative to their report and cannot traverse outside it.

### Model actions

Each action has `action`, `table`, `name` and `item_type`. Supported action names are `move_to_folder`, `move_to_table_group`, `hide`, `unhide` and `delete`. `move_to_folder` also uses `folder`; `move_to_table_group` uses `table_group`. Item types include `Measure`, `Column`, `Calculated Column` and `Table`, subject to the individual writer's supported combinations. Deletion is checked by the shared deletion policy; an unused-looking name is not authorization to bypass blockers.

### Rename a measure

```json
{
  "operations": [
    {
      "kind": "rename",
      "measure_renames": [
        {"table": "Sales", "name": "Revenue", "target_name": "Net Revenue"}
      ]
    }
  ]
}
```

For table renames, entries use `table` and `target_table`. Column rename entries use `table`, `name` and `target_name`. For report-only repair, column entries can additionally identify `target_table` where supported. Inspect the generated diff and remaining findings; the plan rejects newly detected unresolved references.

### Move a measure

```json
{
  "operations": [
    {
      "kind": "move",
      "moves": [
        {"table": "Sales", "name": "Revenue", "target_table": "Measures"}
      ]
    }
  ]
}
```

A home-table move is different from changing a display folder.

### Promote a report measure

```json
{
  "operations": [
    {
      "kind": "promote",
      "report_path": "/path/to/project/Reports/Executive.Report",
      "table": "Sales",
      "name": "Report Margin",
      "target_table": "Sales",
      "target_name": "Report Margin",
      "include_dependencies": true
    }
  ]
}
```

Promotion currently preserves the measure name and home table. A different `target_name` or `target_table` is rejected; plan a separate supported rename or move afterward.

If `report_path` is omitted, the first selected report is used; specify it explicitly when more than one report is selected. `include_dependencies` defaults to false. Unsupported metadata loss is not silently authorized: `allow_metadata_loss` defaults to false. Inspect the proposed dependency set and metadata differences before opting into either behavior.

### Report metadata entries

Prefer generating these from reviewed analyzer/UI evidence rather than guessing JSON paths. A stale cleanup entry identifies `report_path`, `artifact_path`, `source_path`, `selector_value` and `stale_kind`. A report-issue entry additionally identifies the intended `action` and reference; replacement entries specify `target_table` and `target_name`. Exact entry semantics remain those of the shared report writer. A missing or out-of-scope file is not silently added to the plan.

## Commands and exit codes

| Command | Output / meaning |
| --- | --- |
| `smc plan … --operations FILE -o PLAN` | Create a plan; stdout JSON summary |
| `smc diff PLAN` | Print unified text differences from a validated plan |
| `smc diff BASELINE_MODEL CANDIDATE_MODEL` | Print a model comparison as JSON; this is a separate comparison mode, not plan creation |
| `smc apply PLAN [--journal-dir DIR]` | Apply reviewed bytes after input checks; JSON result and receipt |
| `smc verify PLAN [--journal-dir DIR]` | Compare current metadata hashes to plan inputs/outputs; JSON state |
| `smc history [--journal-dir DIR]` | List saved operation receipts as JSON; does not list unapplied plan files elsewhere |
| `smc restore PLAN [--journal-dir DIR]` | Restore matching reviewed changes using the journal and original bytes |
| `smc recover-lock PLAN [--journal-dir DIR]` | On POSIX, remove an abandoned lock only after checking that its recorded process has exited |

Exit `0` means the command succeeded. For `verify`, that specifically means the selected metadata matches the planned outputs (`state: applied`). Exit `1` means an operation returned `ok: false`, including verification states `original` or `changed`, a rolled-back apply, or recovery requiring attention. Exit `2` covers handled input, plan-validation, I/O or parsing errors, reported as error JSON on stderr where handled by the command; argparse usage errors also use `2` and plain usage text. These codes are specific to the plan commands; `check` and `clean-stale` have their own contracts.

Verification does not re-run DAX or a new semantic analysis. It verifies fingerprints and returns the validation recorded during planning. A no-op plan has identical input/output fingerprints and can therefore verify as `applied` without any file writes.

## Validation and freshness

Planning analyzes the baseline and staged result, rejects newly detected unresolved references, and records remaining pre-existing problems. It checks exact error identities/locations rather than relying only on a total count.

Rename, move, promotion, report repair, DAX edits and deletion require stricter coverage checks. Invalid selected JSON metadata, unsupported scan coverage, or unsuitable report bindings can block a plan before edits occur. Non-reference metadata changes can tolerate unchanged pre-existing invalid JSON; changed JSON still must pass validation.

Validation is static and limited to supported selected metadata. It does not perform full Microsoft schema validation, evaluate the DAX engine, refresh a model, render reports, or establish equal Power BI runtime results. A plan may retain existing problems; inspect both existing and remaining problem counts.

The engine fingerprints selected metadata before and after staging and checks again before apply. If someone changes a selected file, generate a new plan. Do not edit the plan JSON or its digest to work around freshness checks. Apply writes the already reviewed bytes; it does not reinterpret changed operations at apply time.

## Receipts and recovery

A plan is saved to the journal directory before applying. Its receipt begins as `applying`, records completed paths as writes proceed, and finishes as `applied`. A caught failure attempts to restore completed writes in reverse order. It records `rolled_back` when that succeeds or `recovery_required` when restoration cannot finish safely. Do not retry the same apply after a receipt already exists; inspect it and either restore or create a new plan.

Restore an applied or interrupted operation:

```bash
smc history
smc restore review/hide-revenue.plan.json
```

Restore accepts receipts in `applied`, `applying`, `recovery_required` or `restoring` states. It leaves already-original files alone and restores a changed file only when it still matches the reviewed replacement bytes. It refuses to overwrite subsequent edits. A successful restore records `restored`; failures requiring attention record `recovery_required` or return an error. The journal and retained plan are the recovery record; keep both.

If a process was terminated while holding a lock, inspect the receipt and confirm that the operation is no longer running. On POSIX:

```bash
smc recover-lock review/hide-revenue.plan.json
smc restore review/hide-revenue.plan.json
```

Lock recovery requires a matching receipt and a recorded process that can be established to have exited. It removes only the abandoned lock; it does not restore files. A live or unverifiable owner keeps its lock. On Windows, automatic lock recovery is unsupported: inspect the recorded process and lock path, confirm the process has exited, remove the abandoned lock manually, then use `restore`. Never clear a lock belonging to an active operation.

## Local web API

The UI uses the same engine through these local endpoints:

| Endpoint | Contract |
| --- | --- |
| `POST /api/plans` | Body: `{operations: [...], model_path: "…", report_paths: ["…"]}`. Returns `{ok: true, plan: {...}}`; omitted scope fields use the current app selection |
| `GET /api/plans` | Returns `{plans: [...], receipts: [...]}`. Plan summaries omit input/output fingerprints and original/replacement bytes; they retain file diffs |
| `GET /api/plans/<id>` | Returns the full validated stored plan |
| `POST /api/plans/<id>/apply` | Apply a stored plan; returns result/receipt |
| `POST /api/plans/<id>/verify` | Check stored-plan output fingerprints |
| `POST /api/plans/<id>/restore` | Guarded restoration |
| `POST /api/plans/<id>/recover-lock` | Guarded abandoned-lock recovery where supported |

Plan IDs are 32 lowercase hexadecimal characters. Creation/lookup errors generally return HTTP `400`; unsuccessful apply/verify/restore/recovery results return `409`. Unknown operation names return `404`. The API is a local app interface, not a service for accepting arbitrary remote plans. Successful apply/restore invalidates the app's cached analysis; request a fresh analysis before interpreting current usage.

See [CI checks](check.md) for read-only policy gates and [supported workflows](../support.md) for broader product limits.
