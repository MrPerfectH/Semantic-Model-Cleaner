# CLI-Hub submission preparation

The cleaner entry in [semantic-model-cleaner.json](semantic-model-cleaner.json)
is a proposed addition to the `clis` array in CLI-Anything's `registry.json`,
not a local CLI registry or an announcement of a published listing.
It uses the supported Git installation route, so it does not assume a PyPI release.
`database` is an existing category and avoids adding a category just for this entry.

Before opening the registry-only PR:

1. Publish this repository's generated root `SKILL.md` on `main`, then check its
   raw URL returns the skill rather than a 404. Regenerate the skill and rerun
   `python scripts/generate_skill.py --check` if capabilities change.
2. Recheck the entry version against the source available from the installation
   URL. The draft records the current checkout's version, not a published release.
3. In a disposable virtual environment, install using the entry's exact command
   and run `smc capabilities` and `smc operations-schema` outside the checkout.
4. Add the entry to upstream `registry.json`, check uniqueness and required fields,
   and open a registry-only PR with the installed-command validation results.

Suggested title: `Add Semantic Model Cleaner standalone CLI`

Suggested body:

> Adds Semantic Model Cleaner to the database category. The standalone Python CLI
> analyzes local Power BI TMDL and PBIR files, traces item usage, and prepares
> sealed cleanup plans with diff/apply/verify and guarded recovery. It does not
> require Power BI Desktop for metadata analysis. The linked skill documents scope
> limits and explicit approval of the exact plan before apply or restore.
>
> Installation uses the standalone Git URL. Include the actual outside-checkout
> installation results and passing repository CI when submitting.

## Viewer readiness

Do not submit a speculative `npm install -g semantic-model-viewer-cli` entry.
The viewer CLI checkout on the `claude-marketplace` branch marks its package
`private: true`; its `docs/cli.md` explicitly says there is no published npm release.
The local `Semantic-Model-Viewer` application checkout is on a different branch
and does not contain the CLI distribution. Its root skill links to the existing
CLI skills on `claude-marketplace` rather than suggesting those files exist locally.

Upstream's standalone-harness contribution instructions require a pip-installable
package. Its newer installer also has npm and generic strategies, but that does
not establish eligibility in `registry.json`. A viewer listing needs a supported,
reproducible installation route and confirmation of the appropriate registry
(harness versus public/native tools). Publishing a package or changing distribution
is separate work; there is no valid second registry entry to submit yet.

Sources checked 2026-10-26:

- [Standalone contribution requirements and registry fields](https://github.com/HKUDS/CLI-Anything/blob/main/CONTRIBUTING.md)
- [Installer strategy selection](https://github.com/HKUDS/CLI-Anything/blob/main/cli-hub/cli_hub/installer.py)
- [Viewer CLI documentation](https://github.com/MrPerfectH/Semantic-Model-Viewer/blob/claude-marketplace/docs/cli.md)

The submission remains local until the linked cleaner skill is public and the
exact remote installation has been checked. No upstream PR has been opened.
