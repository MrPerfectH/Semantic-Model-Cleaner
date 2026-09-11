# Windows Packaging

This branch packages the local web UI as a Windows executable instead of introducing a separate desktop codebase.

## Local Build

Install development dependencies, then run:

```powershell
pwsh -File packaging/windows/build.ps1
```

Output:

- unpacked app folder: `dist/Semantic Model Cleaner/`
- release zip: `dist/semantic-model-cleaner-windows-x64-<version>.zip`
- SHA-256 sidecar files: `<zip-name>.sha256`

The public beta is available from the [v0.4.0b1 prerelease](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b1). Download the versioned ZIP and its checksum, verify it, then extract the entire ZIP before opening the executable. The package includes its beta identity, templates, static JavaScript/CSS, pinned schemas, and synthetic demo files.

## Runtime Behavior

- starts a local server on `127.0.0.1`
- prefers port `5001`, but falls back to another open local port if needed
- opens the default browser automatically unless `--no-open-browser` is passed

The beta ZIP is unsigned. Windows verification runs the downloaded ZIP outside
the checkout with a Python-free child `PATH`, a real Chromium browser, an
occupied preferred port, and disposable paths containing spaces and non-ASCII
characters. The gate analyzes the demo and applies, verifies, and restores a
reviewed synthetic change before the tag workflow publishes the prerelease.
