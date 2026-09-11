# Landing Site

This directory powers the GitHub Pages landing site for the `0.4.0b1` public
beta, repository quick start, support matrix, and developer setup.

## Build & deploy

1. Edit `index.html` and `styles.css` to update copy or visuals.
2. Push the changes to `codex/landing-site` (or merge it into `main` once ready).
3. GitHub Actions automatically publishes everything under `docs/` via [.github/workflows/pages.yml](../.github/workflows/pages.yml).

## Local preview

You can open `docs/index.html` in your browser or preview it with your preferred static-site tooling. No build step is required since the files are vanilla HTML/CSS.

## Notes

- The hero CTA links directly to the immutable `v0.4.0b1` Windows prerelease asset and the GitHub repo.
- Navigation anchors point to the `channels`, `workflow`, and `faq` sections.
- Prerelease downloads use the explicit tag and immutable asset URLs because
  GitHub's stable-release alias excludes prereleases.
