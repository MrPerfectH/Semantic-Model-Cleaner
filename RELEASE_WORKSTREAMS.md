# Release Workstreams

This repo uses local Git worktrees for public-release work instead of cloud development workspaces.

## Summary

- Keep the primary checkout on `main` for integration and review.
- Build and validate release artifacts in GitHub Actions.
- Limit active streams to two at a time when working solo.

## Worktree Layout

Run the setup script from the main checkout:

```bash
./scripts/setup_release_worktrees.sh
```

Expected worktrees:

- `../smc-foundation` on `codex/public-foundation`
- `../smc-windows` on `codex/windows-exe`
- `../smc-beta` on `codex/beta-gating`
- `../smc-site` on `codex/landing-site`

## Stream Ownership

### `codex/public-foundation`

- Scope: public-readiness only
- Files: `README.md`, `CONTRIBUTING.md`, `LICENSE`, `pyproject.toml`, `.gitignore`, issue/community scaffolding, public demo workspace
- Excludes: Windows packaging, beta gating, website deployment

### `codex/windows-exe`

- Scope: packaged Windows application and release artifact generation
- Files: packaged app launcher, browser auto-open flow, bundled assets/templates, Windows build workflow, release asset naming
- Excludes: broad public-doc rewrites

### `codex/beta-gating`

- Scope: stable vs beta separation
- Files: experiment registry, prerelease behavior, UI exposure, release labeling
- Excludes: unrelated product features

### `codex/landing-site`

- Scope: static website only
- Files: landing page, download links, screenshots/GIFs, docs navigation, GitHub Pages config
- Excludes: app feature work and release packaging logic

## Merge Order

1. `codex/public-foundation`
2. `codex/windows-exe`
3. `codex/beta-gating`
4. `codex/landing-site`

## PR Boundaries

- PR 1: public foundation only
- PR 2: Windows executable only
- PR 3: beta gating only
- PR 4: landing site only

## Validation

### Foundation

- `python -m pytest`
- `python -m ruff check .`
- `python -m build`
- Manual review for internal/private wording and generated artifacts

### Windows

- GitHub Actions build on `windows-latest`
- Packaged app starts, opens the browser, and loads bundled templates correctly
- Manual Windows smoke test for analyze, export, and basic cleanup

### Beta

- Stable mode hides beta UI and beta features
- Prerelease mode exposes beta UI and labels it clearly
- Release notes and prerelease labeling are consistent

### Site

- GitHub Pages build succeeds
- Stable and beta download links resolve correctly
- Screenshots and quickstart match the shipped app
