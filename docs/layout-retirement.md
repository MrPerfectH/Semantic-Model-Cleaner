# One workspace layout

The v2 workspace is the only served UI. The Classic layout link, template and
plan adapter assets have been removed. Compare is also absent.

Old bookmarks with ?ui=classic (or any other ui value) open v2. An existing
smc_ui cookie is ignored and expired; new visits do not persist a layout choice.
The workspace uses Items, Tables, Reports and Changes, with item details and
secondary scan/reference views.

The Windows packaging smoke checks the v2 assets, legacy selection handling,
cookie removal and 404 responses for retired assets. Historical audit captures
and release notes describe previous versions and remain unchanged.
