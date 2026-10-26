# Bundled VS Code engine

Build on the target OS and architecture with a prepared Python environment:

```sh
python -m pip install -e '.[dev]'
python packaging/vscode/build_engine.py
cd vscode-extension
npm ci
npm test
node scripts/smoke-engine.cjs
npm run package
node scripts/test-bundled.cjs
```

Linux CI runs the last command under `xvfb-run -a`. To use an existing local
VS Code installation instead of downloading a disposable test host:

```sh
SMC_TEST_BUNDLED=1 SMC_TEST_VSIX="$PWD/semantic-model-cleaner-0.1.8-linux-x64.vsix" \
SMC_VSCODE_EXECUTABLE=/usr/share/code/code npm run test:integration
```

The generated `vscode-extension/engine` directory is ignored by Git. It contains
the frozen `semantic_model_cleaner.web` entry point, Python, imported libraries,
templates, static assets, pinned schemas, demo files, license notices and a build
manifest. Each VSIX also gets a SHA-256 sidecar. Release verification rejects mixed versions,
wrong/missing targets, missing assets, checksum changes, lost executable bits,
and engines from a dirty or different source revision.

The engine stays with its supporting directory; do not copy only the
executable. Packaging checks native architecture and source engine version, and
the launcher verifies the running engine's version against the manifest.

Python Path takes precedence over an explicit Executable setting. With both
empty, the extension uses its own engine and never searches PATH for one.
Missing/incompatible bundles fail with reinstall instructions; they never trigger
pip, a download, or a silently selected external installation. Existing explicit
settings remain advanced overrides after upgrading.

CI builds four native targets: Windows x64 (`windows-2022`), Linux x64
(`ubuntu-22.04`, glibc 2.35), macOS arm64 (`macos-14`) and macOS Intel
(`macos-15-intel`). Linux release packages are built on the Ubuntu 22.04 baseline,
not on the developer's newer distribution. Other Linux distributions need
compatible system libraries. macOS 14 arm64 and macOS 15 Intel are the tested
baselines; earlier macOS releases are not claimed.

Each job installs its exact VSIX into a disposable profile. The installed engine
runs with an empty PATH and invalid PYTHONHOME/PYTHONPATH, without uninstalling or
changing the computer's Python installation. Offline verification blocks external
network access while allowing loopback:

- Linux: a private user/network namespace with only loopback enabled.
- macOS: a process sandbox denying outbound connections except localhost.
- Windows: temporary firewall rules for the disposable engine and a private copy
  of Node. The test requires elevation and enabled firewall profiles on personal
  computers. Only ephemeral CI runners may temporarily enable disabled profiles;
  every original profile setting and test rule is restored afterward.

The test first verifies that an external TCP connection fails, then exercises
analysis, JSON/XLSX export, plan preview/apply/verify, byte-exact restore, shutdown
and restart. Desktop integration also clicks the actual embedded change-review,
apply, verification and restore controls, proving both cancel paths leave files
unchanged. Evidence records the OS/architecture, network isolation, VSIX SHA-256,
engine selection and unchanged project inputs.

To run this acceptance on an available device, install the platform's exact VSIX
through the existing harness with `SMC_TEST_BUNDLED=1`, `SMC_TEST_OFFLINE=1`,
`SMC_TEST_VSIX` and `SMC_VSCODE_EXECUTABLE`. Use a normal desktop session; on
Windows use an elevated shell for the temporary program-scoped firewall rules.
No real Power BI Project or existing VS Code profile is used. To exercise only a
staged engine, set `SMC_ENGINE_EXTENSION` to this extension directory and run
`node scripts/offline-smoke.cjs`.

macOS builds use PyInstaller's ad-hoc signatures by default and verify the engine
signature. If an existing Apple Developer ID identity is installed, set
`SMC_CODESIGN_IDENTITY` when building; PyInstaller signs the collected native code
with hardened runtime, and the build rejects an identity that does not produce a
Developer ID Application signature. This does not perform Apple notarization.
No signing credentials or publisher secrets are currently configured in this
repository; public signing/notarization and Marketplace publication therefore
remain separate release work.

The manually dispatched publishing workflow requires all four verified artifacts
and publishes those exact packages. Pushes and PRs never publish. Evidence from a
CI runner is labeled as CI evidence; tests on a user's Mac or MSI require working
remote access and are not inferred from the CI results.
