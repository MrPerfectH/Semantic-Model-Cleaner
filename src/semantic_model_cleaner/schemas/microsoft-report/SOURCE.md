# Microsoft report schema snapshot

Upstream: https://github.com/microsoft/json-schemas
Commit: `5e1199a15b80e3d51198fe017b1a6fb9bb0871a6`
Directory: `fabric/item/report`

All 113 upstream JSON files are preserved byte-for-byte, including transitive
embedded schema dependencies. `manifest.json` records retrieval URLs, declared
IDs and SHA-256 checksums. Microsoft's original MIT license is in `LICENSE`.

No files from users' models or reports belong in this directory. Runtime
validation uses this local snapshot only. See `docs/schema-validation.md` for
coverage and the explicit treatment of upstream identity conflicts.
