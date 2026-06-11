# Semantic Model Cleaner

Semantic Model Cleaner analyzes Power BI PBIR + TMDL projects, shows which semantic model items appear to be unused across selected reports, and lets you apply cleanup actions locally.

It is designed for local use against files on your machine. The current release target is early-stage open source for Power BI practitioners who already work with PBIR and TMDL.

## Current Status

- Project maturity: early-stage `0.x`
- Runtime shape: Python package with a CLI, a local web UI, and Windows desktop packaging
- Stable entry points: `semantic-model-cleaner`, `semantic-model-cleaner-web`, `smc`, and `smc-web`
- Windows entry points: packaged `Semantic Model Cleaner.exe`, `semantic-model-cleaner-desktop`, and `smc-desktop`
- Roadmap: beta feature isolation, release hardening, and a public landing site

## What It Does

- Scans exactly one `.SemanticModel` and one or more `.Report` folders
- Detects direct report usage plus supported indirect or model-backed usage
- Surfaces warnings for unresolved or ambiguous dynamic references
- Lets you review analysis results in a local web UI
- Supports local cleanup actions such as move to folder, hide/unhide, and delete
- Previews queued cleanup actions before writing TMDL files

## What It Does Not Do

- It does not host or publish reports for you
- It does not yet ship a signed installer or auto-update flow
- It does not yet cover every Power BI metadata edge case

## Requirements

- Python `3.11+`

## Install

Runtime install:

```bash
python -m pip install .
```

Development install:

```bash
python -m pip install -e .[dev]
```

### Windows Packaged App

For terminal-free Windows use, a packaged launcher is also available.

Local launcher command:

```bash
semantic-model-cleaner-desktop .
```

Short alias:

```bash
smc-desktop .
```

Packaged runtime behavior:

- starts the local app on `127.0.0.1`
- prefers port `5001` and falls back to another free local port if needed
- opens the default browser automatically
- can skip browser launch with `--no-open-browser`

## Quick Start

### CLI

Run the analyzer from a workspace root:

```bash
semantic-model-cleaner . --format full
```

Export JSON or Excel:

```bash
semantic-model-cleaner . --format json -o analysis.json
semantic-model-cleaner . --format xlsx -o analysis.xlsx
```

Short alias:

```bash
smc . --format full
```

Use explicit paths when your model and report roots are separate:

```bash
semantic-model-cleaner \
  --models-path /path/to/Model.SemanticModel \
  --reports-path /path/to/Report.Report \
  --format unused
```

Module entrypoint:

```bash
python3 -m semantic_model_cleaner . --format full
```

### Local Web UI

Start the web app:

```bash
semantic-model-cleaner-web .
```

Short alias:

```bash
smc-web .
```

Then open `http://127.0.0.1:5001`.

Optional flags:

```bash
semantic-model-cleaner-web . --port 8080
semantic-model-cleaner-web . --host 0.0.0.0
semantic-model-cleaner-web . --debug
```

Module entrypoint:

```bash
python3 -m semantic_model_cleaner.web .
```

## Demo Workspace

The app bundles a small synthetic demo workspace. In the web UI, click **Try the demo workspace** to copy it to `~/.semantic-model-cleaner/demo-workspace` and analyze it — no Power BI Project files of your own are needed, and the bundled copy is never modified. The source lives under [`src/semantic_model_cleaner/demo_workspace`](src/semantic_model_cleaner/demo_workspace) and also supports screenshots, quick validation, and safe public examples.

A richer synthetic QA workspace is available under [`examples/product-qa-workspace`](examples/product-qa-workspace). It exercises trust-critical flows such as Report Health, stale report metadata, broken references, Unsupported Metadata review downgrades, RLS-backed dependencies, and Report Extension Measures.

## Supported Exports

- CLI: `json`, `xlsx`
- Web UI: `Export JSON`, `Export Excel`

Both web exports download the latest completed analysis without re-running it.

## Safety Notes

- The workflow is intentionally `1 semantic model -> 1 or more reports`
- Queued model cleanup actions are dry-run planned before `/api/action` writes files
- The app can create a backup before destructive edits when requested
- Field parameters backed by `NAMEOF(...)` are supported
- Remaining caveats include calculation groups, broader metadata indirection, and malformed or skipped JSON

## Development

Run tests:

```bash
python3 -m pytest
```

Run lint:

```bash
python3 -m ruff check .
```

Build distributions:

```bash
python3 -m build
```

Build the Windows package locally:

```powershell
pwsh -File packaging/windows/build.ps1
```

## Stable vs Beta

- The default `SMC_RELEASE_CHANNEL` is `stable`. Set `SMC_RELEASE_CHANNEL=beta` or `SMC_RELEASE_CHANNEL=prerelease` to exercise the beta UI that surfaces experimental flows and prerelease messaging.
- Enable one or more experiments with `SMC_EXPERIMENTS=compare-models` (comma-separated for multiple keys). The web UI also accepts `--experimental compare-models` when you launch `semantic-model-cleaner-web`.
- Stable releases hide beta banners and extra UI; beta/prerelease builds show a `Beta` banner and list the active experiments so users know they are on a fast-moving channel.

See `tests/test_experiments.py` for the supported experiment keys and release-channel logic.

## Repository Layout

- `src/semantic_model_cleaner/analyzer.py`: CLI analyzer and export logic
- `src/semantic_model_cleaner/webapp.py`: Flask app and API
- `src/semantic_model_cleaner/tmdl_writer.py`: TMDL edit engine
- `src/semantic_model_cleaner/templates/index.html`: single-page web UI template
- `src/semantic_model_cleaner/demo_workspace/`: bundled synthetic demo workspace
- `examples/product-qa-workspace/`: richer synthetic QA workspace
- `scripts/analyze_model_usage.py`: compatibility wrapper for the packaged CLI
- `scripts/app.py`: compatibility wrapper for the packaged web app
- `tests/`: automated tests and fixtures

## Contributing

Contribution guidance is documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

Planned follow-up work is tracked in [BACKLOG.md](BACKLOG.md).

## More Detail

Analyzer-specific usage and caveats are documented in [scripts/analyze_model_usage.README.md](scripts/analyze_model_usage.README.md).

## Community & Support

- License: [MIT](LICENSE)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security reporting: [SECURITY.md](SECURITY.md)
- Issues and discussions are monitored on the public [GitHub repository](https://github.com/MrPerfectH/Semantic-Model-Cleaner).
