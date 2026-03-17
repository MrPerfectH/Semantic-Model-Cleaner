# Landing Site

This directory powers the GitHub Pages landing site that points people to the Windows download, release channels, and developer setup.

## Build & deploy

1. Edit `index.html` and `styles.css` to update copy or visuals.
2. Push the changes to `codex/landing-site` (or merge it into `main` once ready).
3. GitHub Actions automatically publishes everything under `docs/` via [.github/workflows/pages.yml](../.github/workflows/pages.yml).

## Local preview

You can open `docs/index.html` in your browser or preview it with your preferred static-site tooling. No build step is required since the files are vanilla HTML/CSS.

## Notes

- The hero CTA links go directly to the stable Windows zip and the GitHub repo.
- Navigation anchors point to the `channels`, `workflow`, and `faq` sections.
- The `download` section has three cards for stable, beta, and source installs.
