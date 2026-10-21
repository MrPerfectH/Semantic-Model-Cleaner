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

## Repository versus published consumers (#120)

`smc service compare` takes the same target/scope options, plus
`--repository PROJECT --local-model EXACT_MODEL_PATH --mapping MAPPING.json`.
The same optional repository arguments work with `audit` and `validate`;
validation uses its explicit candidate as the local model unless overridden.

Mappings are environment-specific and must name the exact target:

```json
{
  "schema_version": 1,
  "target": {
    "tenant_id": "TENANT_GUID",
    "workspace_id": "TARGET_WORKSPACE_GUID",
    "model_id": "TARGET_MODEL_GUID"
  },
  "reports": [
    {"local_report": "Reports/Executive.Report", "workspace_id": "REPORT_WORKSPACE_GUID", "report_id": "REPORT_GUID"}
  ]
}
```

The private result separates matched, additional published, local-only,
unresolved and excluded local Reports, with identity evidence for each match.
Local connections must point to the selected exact local model path or exact
service model ID. Duplicate mappings, target mismatches and path escapes are
rejected. Missing mappings remain unresolved, even if names or `.platform`
logical IDs look identical. Unresolved local identities can correspond to
otherwise unmatched published Reports; “additional” means no confirmed
repository match in this inspected scope, not a universal identity claim.

Local-only means the explicitly mapped Report was not observed connected in a
fully enumerated selected workspace; it never means globally unpublished.
Denied or unsearched workspaces instead leave the mapping unresolved.

Identity confirmation is separate from definition comparison. Where both
snapshots are available, `enhanced-pbir-content-bytes/v1` hashes sorted relative
paths and exact bytes under `definition/` and `StaticResources/`. It excludes
`definition.pbir` (connection), `.platform` (logical identity), local caches,
diagram layout and unrelated files. Equal content bytes means only equality of
that documented subset, not equal binding, runtime behavior or all service
metadata. Other cases explicitly say `not_checked`.

## Application workflow (#121)

Open **Service validation · Experimental** from either application layout.
The offline **Open Power BI Project** flow remains available without sign-in.
The service page has its own jobs, scope revision and results; it never replaces
local analysis or feeds local cleanup/repair controls.

Check an existing local sign-in, or explicitly start device sign-in on this
computer. Device sign-in invokes an already installed Azure CLI for the exact
tenant using `az login --use-device-code --allow-no-subscriptions --output none`.
Only Microsoft's fixed sign-in link and short user challenge are displayed;
raw CLI output and access tokens are never returned. Cancel terminates the local
login process and removes the challenge. If CLI or the existing client scopes
are unavailable, the page explains that blocker. No registration, consent grant,
permission escalation, password collection or credential copying is performed.
Obtaining tokens does not yet establish workspace or definition access.

Enter the tenant and workspace GUIDs, load visible model candidates and select
an exact model. Enter each authorized Report workspace explicitly. Choose
published audit, local candidate validation, repository comparison or discovery.
Local candidate/project/mapping paths can be supplied directly; an open local
model is offered when available. Repository comparison is opt-in. Progress and
cancellation are shown; the current bounded service/authentication request may
finish before cancellation takes effect. Results cannot be exported until a job
completes. Changing selection cancels work and invalidates previous results and
exports; changing tenant/workspace also clears the old model/scope selection.

Results retain the selected IDs, discovered/analyzed states, direct service
Report links, affected reference locations, candidate changes and repository
coverage. Report Health and Analysis Limitations have separate sections.
**Export sanitized summary** is safe for sharing source-free counts, digests,
times and capability codes. **Export private result** preserves CLI-equivalent
full provenance and findings; keep it private. All endpoints use the existing
loopback/origin/token boundary and no-store responses.

For a synthetic browser check only, start the server with
`SMC_SERVICE_FIXTURE=/absolute/path/to/supported.json smc-web --port 8765`.
The page prominently labels fixture mode. A browser request cannot turn fixture
mode on or supply credentials. No fixture execution establishes live acceptance.

## Independent checks and acceptance boundary (#122)

Run the complete repository suite and lint, build the distribution, then execute
both installed-wheel checks outside the checkout:

```bash
python -m ruff check .
python -m pytest
python -m build
python scripts/smoke_wheel.py dist/*.whl
python scripts/smoke_service_wheel.py dist/*.whl
```

The service wheel smoke creates a fresh environment with resolved dependencies
and runs all four actual CLI commands plus the installed HTTP application. It
checks real analysis against synthetic definitions, exits 0/1/2, candidate
breakage, repository identity/definition comparison, partial access, source
hashes, sanitized/private exports, CLI/API agreement and expired results.
`--root NEW_DIRECTORY` retains that synthetic installation for a T3 browser
check. The existing wheel smoke checks offline CLI/baseline contracts and the
original application assets. CI runs the service wheel smoke on Linux; Windows
unit tests are automated platform checks, not native owner acceptance.

Unit fixtures additionally cover LROs/pagination, throttling, encrypted and
unsupported definitions, binding drift, cross-workspace identity, authentication
failures, parser gaps, candidate additions/removals, repeated runs, cancellation,
local HTTP isolation and target invalidation. None establish live permissions,
service completeness, visual rendering correctness or runtime DAX behavior.

All service workflows remain **experimental**. #116 remains open pending Linux
sign-in and authenticated inspection of the authorized workspace's actual model
candidates; the tenant and selected model must then be recorded privately by ID.
The remaining live gate includes non-admin owner access and permission/API
compatibility, same/cross-workspace Reports, good/broken/partial cases, candidate
and repository comparisons, cancellation/repeated runs and exported provenance.
Do not treat owner impact-analysis visibility as definition API permission.

#122 additionally requires CI on the final integrated revision, native Windows
package and supported macOS installation/launch evidence, disposable-project
cleanup regression evidence, and the owner's explicit go/no-go for that exact
build. Linux source, wheel and T3 browser fixtures do not replace those gates.
The integration PR stays draft with auto-merge disabled, and no service issue is
closed or main merge authorized by these independent checks.

### Response handling and diagnostics

The shared service transport treats HTTP 202 as header-driven LRO acceptance,
ignoring its body within the existing response size limit. Non-object or malformed
error bodies retain HTTP status classification. Successful responses still require
JSON objects; parse failures retain the HTTP status and a fixed body-kind label in
request evidence. Public summaries expose only those status/body-kind diagnostics,
without response bodies, headers, URLs or server messages.

After a validated operation succeeds, the client constructs its canonical
`/v1/operations/{id}/result` URL; it never follows the completion Location header.
Initial operation URL validation, redirect blocking and retry/poll/size limits
remain in force. Definition POST requests explicitly send
`Content-Type: application/json`; this is hardening, not a proven cause of the
previous failure.

Contract references: [Get Semantic Model Definition](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/get-semantic-model-definition)
and [Fabric long-running operations](https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation)
(checked 2026-10-21). These deterministic checks do not establish live acceptance
or identify the original failure's unknown raw response.
