# Demo Workspace

This directory contains a synthetic PBIR + TMDL workspace that is safe to share publicly.
It ships inside the package so the web app can offer a one-click "Try the demo workspace"
experience: the app copies it to `~/.semantic-model-cleaner/demo-workspace` and analyzes
the copy, so the bundled files are never modified. Loading the demo again resets the copy.

Use it to:

- see analysis and cleanup actions without preparing your own Power BI Project files
- validate local setup
- generate screenshots or demo recordings

Suggested commands when working from the repository:

```bash
semantic-model-cleaner src/semantic_model_cleaner/demo_workspace --format full
semantic-model-cleaner-web src/semantic_model_cleaner/demo_workspace
```
