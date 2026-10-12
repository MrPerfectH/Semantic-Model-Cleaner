# Experimental service validation

These optional commands are provisional under #115. Live non-admin owner access,
permission/API compatibility and native release acceptance remain unverified.
Existing offline commands do not require authentication and retain their output
and exit contracts. Nothing here publishes, rebinds, repairs or deletes a service
artifact or grants permissions.

## Scoped discovery (#117)

```bash
smc service discover --tenant-id TENANT_GUID \
  --workspace-id MODEL_WORKSPACE_GUID --model-id MODEL_GUID \
  --report-workspace-id REPORT_WORKSPACE_GUID \
  --report-workspace-id ANOTHER_ACCESSIBLE_WORKSPACE_GUID --format text
```

All identities are exact GUIDs. Report search scope is mandatory and explicit;
include the model workspace if it should be searched. No workspace is added by
name or automatically searched tenant-wide. The target appears before results
in readable output and in the `target` object in JSON. Names never establish
DEV/PROD equivalence. Repeated scope entries and repeated Report identities
within a workspace are deduplicated; conflicting identities limit coverage.

Authentication uses only existing local Azure CLI sign-in or the two token
environment variables described in [the feasibility guide](service-validation-feasibility.md).
Token tenant/subject/audience/expiry checks precede network access; there is no
fallback to another tenant. Interrupted CLI execution exits 2. Authentication
failures include a fixed actionable message, never credential or service error
text. The app sign-in workflow does not create registrations or grant consent.

Default JSON uses `schema_version: service-validation/1`. Results include exact
source IDs, selected scope, per-workspace enumeration states/times, known direct
Reports, their states/connections, request receipts and Analysis Limitations.
These are **private local results**: do not post them to an issue or PR.
`--public` emits a strict summary with counts and limitation codes, without
identities, names, paths, definitions or credentials. `-o NEW_FILE` writes an
owner-only file and refuses overwrites. Without `-o`, output goes to stdout.

An empty enumerated workspace differs from denied, partial and failed discovery.
`unknown_downstream_report_count` stays null, never zero. The selected-scope flag
only describes visible direct Reports in the listed workspaces; global
completeness is always false. Unsupported/unknown Report types and missing
connection metadata are limitations. Impact-analysis UI visibility is not API
access. Known additional consumers outside this boundary cannot be inferred.

Service-only exit codes: 0 means the requested supported operation completed
within the explicit scope without findings; 1 means findings; 2 means incomplete
coverage, cancellation, invalid input or execution failure. No exit code accepts
live feasibility or authorizes cleanup. Experimental/live-acceptance fields are
always present. Incomplete validation cannot produce exit 0. These semantics do
not alter the existing offline CLI.

For deterministic testing, pass `--fixture tests/fixtures/service_probe/supported.json`
with its synthetic IDs (tenant ending 001, workspace 002, model 003, report scope
002). Fixture mode never loads credentials or uses HTTP, and is labeled as such.
Transport, pagination, retrieval/path safety and identity handling are shared
with the #116 probe, not separate implementations. API permissions and current
Microsoft source links are in the feasibility guide. No live demonstration has
yet been completed.

## Published model audit (#118)

Use the same required identity/scope options with `smc service audit`. Definitions
are retrieved fresh into an owner-only temporary snapshot and deleted even on
failure/cancellation; no project files or persistent service cache are used.
Model and Report receipts record format, retrieval time, hash and `cached:false`.
LROs, inaccessible/encrypted/unsupported definitions and malformed Report parts
remain visible, rather than becoming empty successful scans.

The existing analyzer supplies Live/Stale Report Reference interpretation,
Report Extension Measures, dependency evidence and exact Report/page/visual or
metadata locations. `report_health.findings` is separate from
`analysis_limitations`. Durable `snapshot://` locations replace temporary paths;
Report findings carry exact workspace/report IDs and service links in private
results. Missing definitions reduce selected coverage; normal Report Health
findings cause exit 1 only when the rest of the selected supported scan completed.
Incomplete coverage takes precedence and exits 2. A clean fixture scan exits 0,
explicitly labeled synthetic and experimental.

`coverage.complete` stays false for cleanup because service consumer discovery
is bounded. `selected_scope_complete` describes supported validation of the
selected visible scope; it never implies tenant completeness. No-use items are
at least Review, with shared limitation IDs. Parser-only coverage is separately
named `parser_coverage`, and existing offline contracts remain unchanged.
The sanitized export retains definition digests/times and counts, not service
names, source IDs or reference text. Full private JSON remains available locally.

## Local candidate validation (#119)

```bash
smc service validate --candidate /path/to/Candidate.SemanticModel \
  --tenant-id TENANT_GUID --workspace-id TARGET_WORKSPACE_GUID \
  --model-id TARGET_MODEL_GUID --report-workspace-id REPORT_WORKSPACE_GUID
```

The candidate must be an exact TMDL model directory containing
`definition/model.tmdl`. It is copied into the private snapshot without following
symlinks. Its source path, capture time and byte hash are separate from published
target identity and hash. Source bytes are checked again after validation;
concurrent candidate changes make the result incomplete. No local file is edited.

Baseline and candidate are analyzed against the **same retrieved Report files**.
`comparison` separates pre-existing, introduced and resolved Report Health
findings by stable Report identity and reference location, with the exact Report
hashes used. Both analyses remain available in private JSON. A removed/renamed
measure, column or table produces affected Report locations when supported
references break; additions and unchanged references do not manufacture errors.
Expression-only and relationship changes are not proven compatible merely
because references resolve. Static metadata validation never proves runtime
behavior or universal consumer coverage. Inaccessible/unsupported Reports and
parser limitations propagate through both analyses and take exit-code priority.
