# Semantic Model Cleaner for VS Code - Preview

Choose a semantic model and its reports in a native **Cleaner** sidebar, then
review the analysis in a desktop VS Code editor tab running the existing
Semantic Model Cleaner web UI. The Python engine discovers the Power BI Project
and its report bindings. Analysis and model changes remain explicit user
actions; the existing reviewed-plan safeguards are unchanged.

Version **0.1.8** is prepared as a Marketplace pre-release for
`MrPerfectH.semantic-model-cleaner`; this document does not confirm publication.
The **Preview** label remains. Native packages built from this source include the
Cleaner engine and Python runtime. Earlier VSIX packages required a separately
installed engine; this source change does not update those installed packages.
Native CI covers Windows x64, Linux x64, and macOS Intel/Apple Silicon.
Marketplace publication remains pending; see the build evidence for the tested
versions and platforms.

## Requirements and installation

- Desktop VS Code 1.95 or newer and a **trusted local workspace**.
- A native VSIX matching the supported operating system and architecture.
- Local disk Power BI Project files (TMDL Semantic Model and PBIR Reports).

Install the matching native VSIX with **Extensions: Install from VSIX...**, then
run **Semantic Model Cleaner: Open Cleaner**. No Python installation, virtual
environment, engine path, or first-run download is required. Once published,
Marketplace selects the matching platform package automatically.

For advanced development, **Python Path** can select an environment with a
compatible engine installed. Alternatively, **Executable** can select an external
`smc-web` executable. Python Path takes precedence. Clear both settings to use the
bundled engine; an explicitly configured override is never silently replaced.
Old explicit settings remain overrides after upgrading.

Settings are resource-scoped and restricted by Workspace Trust. The extension
also checks trust in command handlers before reading executable settings or
launching a process. Values are single executable paths or PATH command names,
never shell commands. Quotes, interpreter arguments, variable substitution and
`.cmd`/`.bat` wrappers are not supported. Paths containing spaces work without
adding quotes. Python mode uses `-I -m semantic_model_cleaner.web` to avoid importing
Python modules from the selected project directory.

## Use

Select the **Cleaner** icon in the Activity Bar. **Analysis Scope** is the
native picker; **Cleaner Actions** (collapsed) keeps **Open Cleaner**,
**Restart Server**, **Stop Server** and **Show Logs**. All use the same
trust-checked commands as the Command Palette.

- **Open Cleaner** (in Analysis Scope) uses the single workspace folder, offers a
  picker in multi-root workspaces, or a folder dialog in an empty window.
  Right-click a folder in Explorer to open it directly. Nothing starts until
  you choose it.
- **Cold commands**: Choose Semantic Model, Analyze and report selection commands
  open Cleaner and wait for model/report discovery when necessary. Open reveals
  the native Analysis Scope sidebar. Open and Choose never run analysis or Apply.
  Canceling a folder/model picker or stopping startup abandons the pending action.
- **Semantic model**: a sole model is selected automatically. With several,
  select one explicitly; nothing is guessed. Unsupported model folders are
  listed with a warning.
- **Reports**: every report in the folder connected to the chosen model is
  selected by default (`3 of 5 selected`). Clear checkboxes to analyze a subset,
  or use **Select All Reports** / **Clear Report Selection**. Choosing another
  model resets to all its connected reports. Reports whose binding cannot be
  verified are shown but not selectable; reports of other models are counted.
- **Analyze** analyzes exactly the chosen model and reports. With no reports it
  inspects the model only. A subset or zero reports leaves usage in the other
  reports unknown, so the result records an analysis limitation and no item is
  called Safe.
- The editor shows results only; it has no scope drawer. When the sidebar
  changes after an analysis, the editor marks the results **out of date** and
  blocks actions on them until you analyze again. A change during an analysis
  discards that run's result.
- **Restart Server** reloads settings and restarts the last selected project,
  keeping its model and report choices. Opening another folder resets them.
- **Stop Server** closes the panel and stops its process. Closing the panel or
  deactivating the extension also stops the process.
- **Show Logs** displays bounded, token-redacted launch and server output.
  The status bar shows starting/running/stopped/error and opens Cleaner.

One panel and one owned server run per VS Code window. Opening another folder
replaces the current one. Scope commands wait for the current startup and discovery. Opening another
folder replaces the previous launch; a stopped or closed panel cannot start a late server. No existing server
on a guessed port is reused.

## Boundaries

- **Local desktop only.** Remote SSH, WSL, Dev Containers, Codespaces, virtual
  workspaces and VS Code in a browser fail before starting a process. A workspace
  extension and loopback `portMapping` are used, but remote operation is not
  claimed. Public tunnels and `asExternalUri` URLs would need separate Host,
  Origin and ancestor verification; this preview deliberately does not create one.
- The engine binds `127.0.0.1` on an OS-assigned port. A fresh 256-bit launch token
  travels only in the child's environment and request headers. Readiness checks
  the matching instance fingerprint. There are no token URLs or token files.
- An opt-in `--vscode --host 127.0.0.1 --port 0` protocol permits only the exact
  desktop webview and shell ancestor origins measured from the panel. Only the
  root HTML iframe navigation is exempt from the normal Fetch Metadata framing
  rejection. Host, peer, API token, JSON and Origin checks remain enforced;
  there is no CORS permission. Ordinary web launches still deny embedding.
- The panel has no local resource roots and can frame only its own loopback
  server. The existing UI uses local assets; this extension adds no CDN requests.
- VS Code's sandbox blocks native alert/confirm dialogs. Embedded mode uses
  in-page alerts and awaited confirmations; Cancel has initial focus and Escape
  cancels. Ordinary browser mode retains native dialogs. Existing app-local
  browsing and explicitly confirmed plan actions still operate on the local
  filesystem; the selected folder is a starting scope, not a filesystem jail.
- Logs are limited to 64 KiB. Secret redaction is applied to complete bounded
  lines, so a token split across stdout chunks cannot leak. Overlong or trailing
  incomplete lines are omitted. An extension-host crash closes the child's stdin
  lifetime pipe; ordinary stop also signals and, if needed, force-kills the child.

## Develop, test and package

From this directory, with Node 22+:

```sh
npm ci
npm test
# Use the prepared Python environment on this native build host:
python ../packaging/vscode/build_engine.py
node scripts/smoke-engine.cjs
npm run package
```

The package command creates `semantic-model-cleaner-0.1.8-<platform>-<arch>.vsix`
with the VSIX pre-release flag and matching platform target. It requires a staged
native engine; a universal package without an engine is not produced. It does not publish. Open this directory in VS Code and use
**Run Cleaner extension** (F5) for a development host.

Run the Python suite from the repository root:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

A real extension-host/browser smoke is available:

```sh
SMC_VSCODE_EXECUTABLE='/Applications/Visual Studio Code.app/Contents/MacOS/Code' npm run test:integration
```

`SMC_TEST_BUNDLED=1` with `SMC_TEST_VSIX` tests the installed native package
without configuring a Python interpreter. Add `SMC_TEST_OFFLINE=1` to verify the
engine with OS-level external-network isolation (Windows needs elevation). Otherwise, `SMC_TEST_PYTHON` can select
the prepared development interpreter. Without
`SMC_VSCODE_EXECUTABLE`, the VS Code test runner downloads its default test host.
Linux needs a desktop or `xvfb-run -a npm run test:integration`. Windows can set
these environment variables in PowerShell. The script builds a disposable
two-model project (bundled demo plus the Product QA example, extra connected
reports and one broken binding), uses disposable VS Code/SMC profiles and a
local debugging port, and deletes the copy afterward. Set `SMC_TEST_VSIX` to
install and test a packaged VSIX in the disposable extensions directory instead
of this source folder (if CLI discovery fails, set `SMC_VSCODE_CLI_JS` to the product's
`resources/app/out/cli.js`). It disables Workspace Trust **only in that disposable test
host**; trust denial is covered separately by command-handler tests. It drives the
native sidebar: cold Choose and Analyze, explicit model choice, default and deselected reports, exact
subset and model-only analysis, stale results, model and folder switches, a
change during analysis, restart and stop, and hashes inputs to detect changes. Evidence goes to
`integration-artifacts/`. No user project is used.

See [ACCEPTANCE.md](https://github.com/MrPerfectH/Semantic-Model-Cleaner/blob/main/vscode-extension/ACCEPTANCE.md) for observed results, evidence boundaries and
installed-VSIX verification steps.

API references: [Workspace Trust](https://code.visualstudio.com/api/extension-guides/workspace-trust),
[webview security](https://code.visualstudio.com/api/extension-guides/webview),
and [desktop port mapping](https://code.visualstudio.com/api/advanced-topics/remote-extensions#option-2---use-a-port-mapping).

## Marketplace release preparation

The package declares the public publisher `MrPerfectH`, repository URL and MIT
license, and includes `LICENSE`. The `media/cleaner-broom.svg` is the Activity Bar
icon; `media/cleaner.png` is the Marketplace package icon.

The manually dispatched **Publish Cleaner Marketplace pre-release** workflow
runs extension and focused Python checks, packages this version and publishes
that exact VSIX with `--pre-release`. A repository maintainer must configure
`VSCE_PAT` with permission for the `MrPerfectH` publisher and explicitly dispatch
the workflow from the reviewed release commit. Pushes do not publish. Packaging
or passing tests alone does not establish Marketplace availability.
