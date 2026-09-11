# Offline PBIR schema validation

`semantic_model_cleaner.metadata_validation` validates a JSON document only when it declares an exact `$schema` URI available in the bundled Microsoft report schemas. It does not infer a schema from a filename, a `version` property, or the application's interpretation of that file.

The bundle is copied from [Microsoft's JSON schema repository at commit `83ce11373faada0d01e76264a5cceb0ba70003e6`](https://github.com/microsoft/json-schemas/tree/83ce11373faada0d01e76264a5cceb0ba70003e6/fabric/item/report). It contains all 97 JSON schema files under `fabric/item/report` at that commit, including embedded schemas needed by transitive references, plus Microsoft's MIT license. Each original file is preserved byte-for-byte and has a SHA-256 entry in the local manifest. The module checks bundle integrity and reference closure before using it.

The validator's registry can resolve only bundled resources. It never downloads a schema at runtime, follows an untrusted `$schema` URL, or transmits model/report metadata. Unknown versions and missing declarations remain explicitly **not validated**.

## Status and coverage

| File status | Meaning |
| --- | --- |
| `valid` | The document passed its supported declared schema |
| `invalid` | The declared schema found errors, or JSON could not be parsed; `reason` distinguishes these |
| `not_validated` | No usable declaration, an unbundled schema/version, or an unavailable upstream schema/reference |

Schema errors include the instance JSON pointer, schema pointer, validation keyword and message. Messages are bounded to 800 characters, with a detail hash retained for comparison. A per-file error cap defaults to 100. If that cap is reached, `truncated` is true and the evidence is incomplete.

`validate_metadata` returns both `ok` and `complete`. `ok` means no invalid files were found; it does **not** mean every input was validated. `complete` additionally requires at least one JSON metadata file, no unvalidated files, no syntax failures and no truncated error lists. TMDL files are outside this JSON schema validator and are not counted.

The validator uses the draft declared by each official schema. JSON Schema `format` annotations are not asserted. This is metadata-shape validation, not semantic query resolution, DAX compilation, model refresh, report rendering, or a guarantee of equivalent Power BI runtime behavior.

## Python API

```python
from semantic_model_cleaner.metadata_validation import (
    bundle_info,
    compare_validation,
    validate_document,
    validate_metadata,
)

# Decoded document; no schema is inferred when $schema is absent.
file_result = validate_document(document, path="report-1/definition/page.json")

# Snapshot keys must be stable artifact-relative paths, preserving report identity.
# Values are bytes or JSON text. Only .json, .pbir and .pbism are considered.
before_validation = validate_metadata(before_snapshot)
after_validation = validate_metadata(after_snapshot)
comparison = compare_validation(before_validation, after_validation)
```

`bundle_info()` reports the pinned repository/commit, bundled schema count, registered URI count, unavailable schemas, and the lack of network access/format assertions. A missing, altered or incomplete installed bundle raises `SchemaBundleError` or an underlying installation error. Do not convert such an error into a passing result.

The comparison reports:

- `new_errors` and `resolved_errors`, identified by artifact path, schema, instance/schema pointers, keyword and message detail hash. Equal total error counts do not conceal a newly invalid field.
- `lost_validation`, when a previously validated/invalid document remains present but no longer has usable schema validation. Removing `$schema` cannot make a broken document appear repaired.
- `changed_not_validated`, covering new or changed documents that have no usable declared schema.
- `comparison_complete`, false when changed documents were not validated or either error list was truncated.
- `ok`, true only when there are no new errors, no lost validation and the comparison is complete. Unchanged pre-existing errors and unchanged unvalidated files are retained but are not new regressions. Deleted files are removed from the after snapshot; their errors are resolved in this structural comparison, not proof that deletion is semantically safe.

## Integration with change plans

Use the same before/after metadata snapshots already staged by the plan engine. Do not re-read live inputs independently while composing the reviewed diff.

1. Run `validate_metadata(before)` and `validate_metadata(after)` on stable keys such as `model/...`, `report-1/...`, `report-2/...`.
2. Add the summaries and `compare_validation` result to the plan's validation evidence.
3. Block newly introduced schema errors and lost validation before creating an applicable plan.
4. Expose unchanged existing violations separately. A team may fix them incrementally; they should not be silently relabeled as passing.
5. Treat changed unvalidated documents as a coverage decision. The schema layer has no evidence for them. A strict refactor policy can block them; a policy permitting them must explicitly preserve the “not validated” limitation instead of claiming full schema validation.
6. Keep the existing semantic-reference, deletion-policy, fingerprint, transaction and recovery checks. Schema validation supplements them.

Apply still needs the plan engine's freshness checks. Re-validating only after a write is too late to protect the user's input files.

## Integration with CI

Add structural errors as stable findings that preserve the report artifact path, JSON pointer, keyword and declared schema URI. Keep unvalidated metadata in the coverage report and allow policy to distinguish known structural errors from unknown coverage. Include the schema commit in exported evidence so a change in upstream schema rules can be separated from a change in user metadata.

A schema update can change validation results for unchanged models. Treat bundle updates as reviewed dependency changes; regenerate expected fixtures, compare before/after findings against synthetic inputs and representative local projects, and explain upstream changes in release notes.

## Upstream identity conflicts

The pristine pinned source has identity problems that cannot safely be resolved by silently guessing a different version:

- `visualConfiguration/1.8.0/schema-embedded.json` declares the ID of its sibling `schema.json`, with different contents.
- `visualConfiguration/2.0.0/schema.json` declares the 2.1.0 identity and 2.1.0 `$schema` constant.

These retrieval URIs are marked `upstream_schema_identity_conflict`. Dependent `visualContainer/1.8.0/schema.json` and `visualContainerMobileState/1.5.0/schema.json` are also marked not validated. The module computes the dependency closure, so an unusable dependency does not produce a false success for its caller.

Other embedded schema filenames use `schema-embedded.json` while their `$id` uses `schema.embedded.json`. Where those names are unambiguous, both authoritative upstream names are registered locally. No schema bytes are rewritten.

## Packaging requirements

Runtime requirements:

```text
jsonschema>=4.23,<5
referencing>=0.35,<1
```

`referencing` is a direct import even though jsonschema also depends on it. Its dependencies, including platform-specific `rpds-py` wheels, must match the installed Python interpreter.

Include `schemas/**/*` and `schemas/microsoft-report/LICENSE` in Python package data. The Windows build must copy `src/semantic_model_cleaner/schemas` to `semantic_model_cleaner/schemas`. Verify `bundle_info()` and at least one transitive visual-schema fixture from the built wheel/executable, not only from an editable checkout.

The synthetic tests cover positive validation, transitive references, exact error paths, no networking, unknown/missing declarations, upstream conflicts, corrupted bundles, before/after regression detection, schema removal and duplicate report display names represented by distinct paths.
