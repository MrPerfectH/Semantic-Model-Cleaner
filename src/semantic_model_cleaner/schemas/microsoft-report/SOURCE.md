# Microsoft report schema snapshot

Upstream: https://github.com/microsoft/json-schemas
Commit: `83ce11373faada0d01e76264a5cceb0ba70003e6`
Directory: `fabric/item/report`

All 97 upstream JSON files are preserved byte-for-byte, including transitive
embedded schema dependencies. `manifest.json` records retrieval URLs, declared
IDs and SHA-256 checksums. Microsoft's original MIT license is in `LICENSE`.

No files from users' models or reports belong in this directory. Runtime
validation uses this local snapshot only. See `docs/schema-validation.md` for
coverage and the explicit treatment of upstream identity conflicts.
