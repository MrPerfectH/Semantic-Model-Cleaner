# Acceptance record — 0.1.2 (2026-10-14)

Sidebar scope selection. Same worktree and branch (`t3/vscode-app-plugin`,
base `e647e58`); no commits, pushes or PRs. All checks below ran on the **MSI
Windows laptop** (Windows, Python 3.13.2, Node 24.19), on a fresh clone of base
`e647e58` with this worktree's changes applied. Every changed file was hash-
compared with the Mac worktree (identical except Windows CRLF checkout).
**No 0.1.2 test ran on the Mac.** Linux/Omarchy was not used.

- Python suite: **1,239 passed, 8 skipped**; `ruff check .` clean.
- `npm test`: **27 passed** (scope state, model choice, deselection, stale
  responses, restart memory, folder reset, payload validation, authenticated
  scope requests, trust gating of the new commands). `npm audit`: 0.
- `npm run package` on Windows: `semantic-model-cleaner-0.1.2.vsix`, 15 files,
  SHA-256 `023af911e7f7e8965d7d9f177c0a91d85458599ebfed533e718bfc5a7b300492`.
  0.1.0 and 0.1.1 VSIX files are kept unchanged.
- Native desktop host, twice: source folder, then the **packaged VSIX installed
  into a disposable extensions directory** (VS Code 1.141.1 win32-x64,
  disposable profile, `result.json` `installedFromVsix: true`). Project: two
  models (TestModel with 2 connected reports, ProductQA with 2), one report with
  a broken binding. All 13 checks passed in both runs: welcome before launch;
  explicit choice with two models and no editor scope drawer; default all
  connected, unverified and other-model reports shown; exact 1-of-2 analysis
  with 0 Safe and the `report_scan:not_selected` limitation; stale banner and
  inert results after a sidebar change; full re-analysis; zero-report
  model-only analysis; model switch; change during analysis; restart keeps
  choices and closes the old port; folder switch resets and auto-selects the
  sole model; stop closes the port; projects byte-identical.
- Windows found a pre-existing engine bug: the parent-pipe watcher blocked the
  git build-stamp subprocess, so the editor stayed blank. Fixed in
  `vscode_host.serve`; covered by `test_real_host_exits_when_parent_pipe_closes`.

Mac: `code-insiders --install-extension semantic-model-cleaner-0.1.2.vsix`
into the existing VS Code Insiders profile; `--list-extensions` reports
`smc-local-preview.semantic-model-cleaner@0.1.2`. No window was reloaded and no
setting changed. Open windows keep running 0.1.1 until the user reloads.
Native use in the user's own Insiders window was not exercised.

# Acceptance record — 2026-10-12

## Checkout and ownership

Implemented in the existing isolated worktree on branch `t3/vscode-app-plugin`,
base HEAD `e647e58a0d1abaee20fdc84ccf7a10d2f681cacc`. The initial worktree was clean.
No commits, merges, publication, user-model edits or live VS Code settings changes
were made. New extension files and the necessary server/security/template/docs/CI
adaptations are the only source changes.

Execution was **macOS arm64** on `Przemeks-MacBook-Pro.local`, Darwin 27.0.0.
The live T3 catalog confirmed the delegated GPT-6-Astra route. This delegated
session remained on Mac; no remote execution/machine-selection tool was exposed.
Linux/Windows results are not inferred from this run. A new CI workflow defines
Linux/Windows checks but has not been run by this task.

## Observed checks

- Python full suite: **1,229 passed, 1 skipped** (platform-specific skip).
- Local boundary + VS Code security suite: **193 tests** included in that suite.
  It covers unchanged default framing, exact origin validation, Host/peer/token/
  JSON denial, instance identity, opt-in flag validation, and an actual Python
  server exiting on parent stdin EOF.
- `python -m ruff check .`: **All checks passed**.
- `npm test`: **16 passed, 0 failed**, including command-handler trust denial
  before settings/panel access, safe argv configuration, real child-process
  lifecycle/failures, wrong-instance rejection, timeout, unexpected exit,
  rapid start/start/stop and chunk-safe secret redaction.
- `npm audit`: **0 vulnerabilities** after moving packaging tooling to vsce 4.
- `git diff --check`: clean.
- `npm run package`: produces the pre-release
  `semantic-model-cleaner-0.1.0.vsix`; only runtime JavaScript, package metadata,
  license and documentation are included. No Python environment, node_modules,
  test profile, screenshots or tokens are packaged.

## Real desktop development-host evidence

The disposable development-host smoke passed in installed **VS Code 1.141.0**
on Mac. It loaded this extension from source; it was **not an installed-VSIX
acceptance run**. It used a disposable VS Code profile and copy of the bundled
demo, with source hashes checked unchanged afterward.

Verified inside the real webview/browser:

- Existing full UI loaded and showed the selected Power BI Project.
- Same-origin authenticated discovery returned HTTP 200 and the demo model.
- Embedded confirmation accepted only explicit Confirm; Cancel and Escape denied.
- Clicking the actual Analyze button rendered demo results.
- Restart closed the old server port; stop/reopen worked; closing the editor
  closed the reopened process's port.

`integration-artifacts/cleaner-vscode.png` shows the rendered analysis inside
VS Code. `integration-artifacts/result.json` records the host and checks. These
local evidence artifacts are ignored by Git and excluded from the VSIX. Earlier
failed smoke runs identified a test-fixture naming error and the native-dialog
sandbox restriction; the latter resulted in the in-page dialog adaptation.

Workspace Trust is disabled only in this isolated development-host harness so
it can run unattended; real command-handler trust denial is covered by unit
tests. This is not evidence of the real Restricted Mode UI experience.

## Installed VSIX acceptance (parent verification)

The parent installed `semantic-model-cleaner-0.1.0.vsix` into a disposable
regular VS Code profile and extensions directory on Mac, with a separate copy
of the bundled demo and this checkout's prepared Python environment. Native UI
checks observed:

- Restricted Mode omitted Open Cleaner from the command palette; Show Logs and
  Stop Server remained available. Only the disposable demo folder was trusted.
- The installed Open Cleaner command loaded scope review for TestModel and its
  connected TestReport. Analyze rendered 9 items, and Revenue opened its full
  item detail page.
- JSON and Excel exports opened native save dialogs and were saved beneath the
  temporary verification directory. JSON parsed successfully (27,774 bytes),
  and openpyxl opened the workbook's Summary, Details and All References sheets.
- Restart replaced loopback port 52669 with 52797. A socket check confirmed the
  old port closed and the new port listened. Closing the Cleaner tab displayed
  `Cleaner: stopped`, and a socket check confirmed port 52797 closed.
- Byte comparison against the bundled demo found zero changed input files.

The ordinary VS Code Insiders TURBO workspace was not used for these checks.
This verifies the installed package's core local Mac flow; it does not establish
full apply/restore UX, all folder-selection paths, or native Windows/Linux support.

## Further acceptance checklist

Use a disposable profile and demo copy, not a real project. From the repository
root on Mac:

```sh
SMC_VERIFY_ROOT=$(mktemp -d /tmp/smc-vscode-manual.XXXXXX)
cp -R src/semantic_model_cleaner/demo_workspace "$SMC_VERIFY_ROOT/Project"
SMC_VSCODE_CLI='/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code'
"$SMC_VSCODE_CLI" --user-data-dir "$SMC_VERIFY_ROOT/profile" \
  --extensions-dir "$SMC_VERIFY_ROOT/extensions" \
  --install-extension "$PWD/vscode-extension/semantic-model-cleaner-0.1.0.vsix"
"$SMC_VSCODE_CLI" --new-window --user-data-dir "$SMC_VERIFY_ROOT/profile" \
  --extensions-dir "$SMC_VERIFY_ROOT/extensions" "$SMC_VERIFY_ROOT/Project"
```

If the launching shell inherited `ELECTRON_RUN_AS_NODE`, unset it for these CLI
invocations. Keep Workspace Trust enabled here. Check Restricted Mode first:
Open/Restart must not launch anything. Then trust only the disposable folder and
set Python Path in this disposable profile to this checkout's absolute
`.venv/bin/python` (or another explicitly prepared matching environment).

Check the installed VSIX's Explorer command, multi-root folder picker, empty
window folder selection, initial scope review, Analyze, detail navigation,
JSON/Excel download behavior, both layouts, confirmation focus/cancel,
restart/rapid close/reopen, logs and status bar. If validating apply/restore,
use only the disposable demo and compare its bytes afterward. No real model
mutation is authorized by this implementation task.

Remaining scope limits: full reviewed-plan interaction acceptance and additional
folder-selection/layout paths; native Windows/Linux extension-host execution; older
supported VS Code versions. Remote/browser hosts are explicitly unsupported,
not an outstanding claim. Marketplace publication and publisher registration
are outside this task.
