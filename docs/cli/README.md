# CLI and automation contract

External agents: [versioned operations schema and reviewed workflow](agents.md).

`smc`, `semantic-model-cleaner`, and `python -m semantic_model_cleaner` use the
same command dispatcher. `--help` lists every command; `COMMAND --help` shows
its options. `--version` prints the package version. Help and version are always
plain text and exit 0, including when combined with `--format json`.

The existing analysis syntax stays supported: `smc PROJECT --format full`,
`unused`, `json`, or `xlsx`. There is no required `analyze` subcommand. Analysis
and automation select connected Reports by default; explicit filters narrow
that scope and do not prove all external consumers were checked.

## Commands and paths

Relative project/search paths start at the current working directory (CWD).

| Command family | `--model` | `--report` | Other path bases |
| --- | --- | --- | --- |
| Analysis, `clean-stale` | Case-insensitive name substring filter | Name substring filter on connected Reports | `--models-path`, `--reports-path`: CWD, including direct artifact search roots |
| `check` | Exact model path relative to PROJECT | Repeatable name substring filter | `--policy`: PROJECT; baseline input/output: CWD |
| `plan` | Exact model folder relative to CWD | Repeatable exact Report folder relative to CWD | Operations input and plan output: CWD |
| `diff`, `apply`, `verify`, `restore`, `recover-lock` | Not applicable | Not applicable | Positional plan/model paths and `--journal-dir`: CWD |
| `history` | Not applicable | Not applicable | `--journal-dir`: CWD |
| `policy`, `naming preview` | Exact model path relative to PROJECT | Repeatable exact Report path relative to PROJECT | Policy `--file`: PROJECT; naming plan `--output`: CWD |

Absolute paths work where a path is expected. They do not turn a name filter
into an exact-path option. For separate analysis roots use `--models-path` and
`--reports-path`; for automation use the command's documented exact-path flags.
Default journal storage is `<SMC_USER_DIR>/plans`, or
`~/.semantic-model-cleaner/plans` when the environment variable is unset.

## Streams, JSON, and exits

All command entry points emit UTF-8 bytes on stdout and stderr, including Windows
redirected pipes. Decode captured bytes as UTF-8. Each documented JSON response
is one complete JSON object; do not depend on one-line formatting. Stderr can
contain human diagnostics, exclusions, or interactive prompts; parse stdout.

| Mode | stdout | Exit codes |
| --- | --- | --- |
| Analysis `--format json` | Versioned analysis object; with `-o`, a JSON receipt pointing to the exported object; errors use the envelope below | 0 completed analysis (including findings); 2 argument, input, or execution failure |
| `check` (default or `--format json`) | Existing version 1.0 check envelope with scope, findings, summary, errors | 0 passed threshold; 1 findings meet threshold; 2 invalid input or execution failure |
| Plan family with `--format json` | Version 1.0 response with command and result fields; errors on stdout | 0 successful operation; 1 verification drift or unsuccessful apply/restore result; 2 invalid input, refused/stale plan, or execution failure |
| Plan family without `--format json` | Existing JSON results except a saved-plan `diff`, which is text; caught errors remain JSON on **stderr** | Existing 0/1/2 behavior |
| `clean-stale --format json` | Existing stale-candidate result | 0 no candidates; 1 candidates; 2 input/analysis failure or withheld direct apply |
| `policy`, `naming preview` | Existing JSON results/errors | 0 success; 1 unsuccessful naming preview; 2 caught input/execution failure |

The **plan family** is `plan`, `diff`, `apply`, `verify`, `history`, `restore`,
and `recover-lock`. Add `--format json` after the subcommand to opt into the
stdout contract. Diff of a saved plan returns `id`, combined `diff` text, and
per-file `changes`; diff of two model folders retains its comparison fields.
Apply/restore failures returned by the engine retain their receipt evidence;
verification retains `state` and `changed_since_plan`. Always inspect both exit code
and `ok` where provided.

Analysis and opt-in plan responses add `schema_version: "1.0"`, `command`, and
`ok`. Input/execution failures have this shape (with optional scope evidence):

```json
{
  "schema_version": "1.0",
  "command": "apply",
  "ok": false,
  "error": "Stale plan: inputs changed...",
  "errors": ["Stale plan: inputs changed..."]
}
```

Check retains its existing envelope: `schema_version`, `command`, `ok`, `scope`,
`findings`, `summary`, and `errors`. Consumers should use `errors` as an array
of messages; analysis/plan also expose `error` for convenience. Optional fields
may be added. This response version does **not** change the saved-plan schema,
digest, or check finding fingerprints.

Argument-parser failures are structured for analysis with `--format json`,
check's JSON mode, and the opt-in plan JSON mode. Other command modes retain
argparse's text usage/errors on stderr with exit 2. Policy/naming and stale
discovery retain their existing result shapes; they are not silently wrapped
in the new response envelope. Ordinary text/Excel analysis also retains its
existing diagnostics and input-error exits (1 or 2).

### Compatibility changes

Existing successful analysis JSON fields remain present; response metadata is
additive. Analysis `--format json` failures now produce JSON on stdout and exit
2, rather than only text on stderr with mixed exits. Analysis `--format json -o`
now prints a JSON output-file receipt instead of `Report saved to: ...`.
Check JSON argument errors now use its existing JSON envelope. Scripts using
these modes should parse stdout, inspect the exit code, and accept new fields.
Plan consumers need no migration unless they choose the new `--format json`
option; omitting it preserves legacy text diffs and stderr error placement.

## Disposable Windows workflow

From a source checkout with the CLI installed, copy the bundled example to a
temporary directory. This example only changes that copy. `check` may exit 1
because the example intentionally contains findings; review its JSON result.

```powershell
$demoCopy = Join-Path ([IO.Path]::GetTempPath()) ("smc-demo-" + [guid]::NewGuid())
Copy-Item -Recurse src/semantic_model_cleaner/demo_workspace $demoCopy
$operations = Join-Path $demoCopy 'operations.json'
$plan = Join-Path $demoCopy 'review/changes.plan.json'
$journal = Join-Path $demoCopy 'review/journal'
'[{"kind":"actions","actions":[{"action":"hide","table":"Sales","name":"Revenue","item_type":"Measure"}]}]' |
    Set-Content -Encoding utf8 $operations

smc check $demoCopy
smc plan $demoCopy --operations $operations -o $plan --format json
smc diff $plan --format json
# Inspect the diff and validation before applying the reviewed plan.
smc apply $plan --journal-dir $journal --format json
smc verify $plan --format json
smc history --journal-dir $journal --format json
smc restore $plan --journal-dir $journal --format json
```

Operations JSON accepts UTF-8 with an optional BOM. Plans and journals are UTF-8
without a BOM. Output guards reject artifact folders and aliases; they do not
create backups as a substitute for refusing unsafe export destinations.

See [reviewed plans](plans.md), [CI checks](check.md), and
[review policy and naming](review-policy.md) for operation-specific limits.
Machine-readable operations schemas and new AI integrations remain separate
follow-up work.
