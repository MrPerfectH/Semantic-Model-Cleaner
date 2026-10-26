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

CI builds Windows x64 and Linux x64 separately, installs each VSIX into a
disposable profile, and exercises that installed engine with an empty PATH.
The engine smoke covers analysis, JSON/XLSX export, plan preview/apply/verify,
byte-exact restore, shutdown and restart on demo copies. Desktop integration
then verifies scope selection and lifecycle without engine settings. Evidence
records the tested VSIX SHA-256 and whether the bundled engine was selected. The manually dispatched publishing workflow
consumes these verified artifacts; pushes do not publish. macOS builds, platform
signing/notarization, minimum OS/glibc support, clean-machine/offline acceptance and native review of the cleanup/restore UI
remain release work. Native Windows
success must be established by its CI/native run, not inferred from Linux.
