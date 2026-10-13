# Semantic Model Cleaner for VS Code — local preview

Open the existing Semantic Model Cleaner web UI in a desktop VS Code editor tab.
The Python engine discovers the selected Power BI Project, and the UI opens its
scope review. Analysis and model changes remain explicit user actions; the
existing reviewed-plan safeguards are unchanged.

This is an unpublished **0.1.1 pre-release VSIX**. `smc-local-preview` is a local
package identifier, not a claim of a registered Marketplace publisher. The VSIX
contains the extension, not Python or the engine. No software is auto-installed.

## Requirements and installation

- Desktop VS Code 1.95 or newer and a **trusted local workspace**.
- Python 3.11+ with a Semantic Model Cleaner build supporting `smc-web --vscode`.
  This capability is introduced by this checkout; an older package, even one
  reporting the same Python beta version, is not sufficient.
- Local disk Power BI Project files (TMDL Semantic Model and PBIR Reports).

Prepare a Python environment explicitly from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

On Windows, use `py -3 -m venv .venv` and
`.venv\Scripts\python.exe -m pip install -e .`.

In VS Code, choose **Extensions: Install from VSIX…** and select
`semantic-model-cleaner-0.1.1.vsix`. Set **Semantic Model Cleaner: Python Path**
to the absolute `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`).
Alternatively leave Python Path empty and set **Executable** to the absolute
path of this environment's `smc-web` / `smc-web.exe`.

Settings are resource-scoped and restricted by Workspace Trust. The extension
also checks trust in command handlers before reading executable settings or
launching a process. Values are single executable paths or PATH command names,
never shell commands. Quotes, interpreter arguments, variable substitution and
`.cmd`/`.bat` wrappers are not supported. Paths containing spaces work without
adding quotes. Python mode uses `-I -m semantic_model_cleaner.web` to avoid importing
Python modules from the selected project directory.

## Use

- **Semantic Model Cleaner: Open Cleaner** uses the single workspace folder,
  offers a picker in multi-root workspaces, or a folder dialog in an empty window.
  Right-click a folder in Explorer to open it directly.
- Repository models are discovered automatically, including models outside `Models/`. A sole model is selected automatically. Choose from the populated model selector to see its connected Reports without browsing.
- Use **Refresh repository** after adding or changing repository files.
- Review the selected model and connected reports, then choose **Analyze**.
- **Restart Server** reloads settings and restarts the last selected project.
- **Stop Server** closes the panel and stops its process. Closing the panel or
  deactivating the extension also stops the process.
- **Show Logs** displays bounded, token-redacted launch and server output.
  The status bar shows starting/running/stopped/error and opens Cleaner.

One panel and one owned server run per VS Code window. Opening another folder
replaces the current one. Requests arriving during startup cancel the previous
launch; a stopped or closed panel cannot start a late server. No existing server
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
npm run package
```

The package command creates `semantic-model-cleaner-0.1.1.vsix` with the VSIX
pre-release flag. It does not publish. Open this directory in VS Code and use
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

`SMC_TEST_PYTHON` can select the prepared interpreter. Without
`SMC_VSCODE_EXECUTABLE`, the VS Code test runner downloads its default test host.
Linux needs a desktop or `xvfb-run -a npm run test:integration`. Windows can set
these environment variables in PowerShell. The script copies the bundled demo,
uses disposable VS Code/SMC profiles and a local debugging port, and deletes the
copy afterward. It disables Workspace Trust **only in that disposable test
host**; trust denial is covered separately by command-handler tests. It exercises
authenticated discovery, confirmation/cancel/Escape, the real Analyze button,
restart and stop, and hashes demo inputs to detect changes. Evidence goes to
`integration-artifacts/`. No user project is used.

See [ACCEPTANCE.md](ACCEPTANCE.md) for observed results, evidence boundaries and
installed-VSIX verification steps.

API references: [Workspace Trust](https://code.visualstudio.com/api/extension-guides/workspace-trust),
[webview security](https://code.visualstudio.com/api/extension-guides/webview),
and [desktop port mapping](https://code.visualstudio.com/api/advanced-topics/remote-extensions#option-2---use-a-port-mapping).
