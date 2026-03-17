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

## Runtime Behavior

- starts a local server on `127.0.0.1`
- prefers port `5001`, but falls back to another open local port if needed
- opens the default browser automatically unless `--no-open-browser` is passed
