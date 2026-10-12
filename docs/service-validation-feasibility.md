# Service validation feasibility probe (#116)

Developer tooling for #116 under #115. Run with
`python -m semantic_model_cleaner.service_probe`; this is deliberately separate
from the existing offline CLI and UI. It has no cleanup, publish, rebind,
permission-management or deployment operations. The only POST is Fabric's
read-only `getDefinition`. This does **not** mean read-only credentials suffice.

**Current decision: live feasibility remains unverified; no-go for accepting
#116 or treating dependent service workflows as proven.** Linux fixture and
installed-wheel results prove the executable plumbing, not tenant access.
No tenant name, live workspace/model ID, credentials or service snapshots belong
in this document or other public evidence.

## Reproduce without service credentials

From a development environment with this package installed:

```bash
python -m semantic_model_cleaner.service_probe run \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --workspace-id 00000000-0000-0000-0000-000000000002 \
  --model-id 00000000-0000-0000-0000-000000000003 \
  --fixture tests/fixtures/service_probe/supported.json \
  --evidence /tmp/smc-probe-fixture.json \
  --private-output /tmp/smc-probe-fixture-private
```

These IDs and responses are synthetic. The fixture transport makes no HTTP
requests and never loads credentials. It still runs the actual TMDL/PBIR
analyzer. Output explicitly says `fixture` and `live_acceptance: unverified`.
Use fresh output paths on every run; the probe refuses to overwrite evidence.
The same command works outside the checkout with an installed wheel and an
absolute fixture path. There is no new runtime dependency.

Exit 0 means candidate inspection or the bounded supported fixture/live path
completed. Exit 2 means incomplete capability, authentication failure, invalid
input or another failure. Exit 0 never accepts #116, establishes global
completeness or authorizes cleanup. `selected_scope_complete` concerns only
visible direct Reports in the supplied workspace list and supported metadata;
`global_completeness` is always false.

## Linux authentication and exact selection

The probe consumes only credentials already available to its Linux process:

- An existing Azure CLI session: it invokes `az account get-access-token` for
  `https://api.fabric.microsoft.com` and
  `https://analysis.windows.net/powerbi/api`, capturing output in memory.
- Alternatively, short-lived `SMC_FABRIC_TOKEN` and `SMC_POWERBI_TOKEN`
  environment values supplied by an already approved local authentication
  workflow. Never put token literals on the command line, in transcripts,
  fixtures, issue comments, or evidence. No Mac credential copying.

It never invokes login, registers applications, grants consent, changes tenant
settings, or refreshes through a password flow. Azure CLI may refresh its own
cached access token. Both tokens must have the same `tid` and `oid`, a supported
audience and a future expiry. Locally decoded JWT claims are selection checks,
not cryptographic authentication; the API validates the bearer tokens. Opaque
tokens or other audience encodings currently return a limitation. Token claims
alone do not verify workspace access or the friendly tenant name.

For a Linux machine without authentication, the required human step is to
install Azure CLI through an approved local setup and sign in **on Linux** as
the intended non-admin model owner:

```bash
az login --use-device-code --allow-no-subscriptions
```

Complete that device login with the intended account. If the correct tenant is
already known, add `--tenant <verified-tenant-guid>`. Do not guess a tenant from
an organization name. The next inspection confirms the token tenant and access
to the exact workspace. Azure CLI supports browser/device login, tenant
selection and resource token acquisition; successful Azure login alone does
not prove Fabric scopes or item permissions. See Microsoft's
[interactive Azure CLI login](https://learn.microsoft.com/cli/azure/authenticate-azure-cli-interactively),
[`az login` options](https://learn.microsoft.com/en-us/cli/azure/reference-index#az-login),
and [`get-access-token`](https://learn.microsoft.com/en-us/cli/azure/account#az-account-get-access-token).

If the pre-existing client lacks consent for the required API scopes, stop and
record that blocker. An organization-approved existing public client using
MSAL interactive/device login can supply the two tokens instead. This probe
does not provide a new application registration or acquire new permissions.
Microsoft's [Fabric authentication quickstart](https://learn.microsoft.com/en-us/rest/api/fabric/articles/get-started/fabric-api-quickstart)
describes public-client MSAL login. Its registration tutorial is a setup
prerequisite, not something the probe performs or an assumption that the normal
owner is a tenant administrator.

First inspect the exact authorized workspace, with no model-name matching:

```bash
python -m semantic_model_cleaner.service_probe inspect \
  --workspace-id <authorized-workspace-guid> \
  --evidence /tmp/smc-inspect.json \
  --private-output /tmp/smc-inspect-private
```

Privately review `identities.json` for the authenticated credential tenant and
candidate model IDs/display names. Check that this tenant is the intended
organization using the owner's authenticated account context. The workspace
URL's UI language, experience and subfolder parameters do not establish a
tenant or select a model. Inspection lists the entire selected workspace,
including nested folders via the API's recursive default. Choose a suitable
existing TMDL-capable model and direct PBIR consumer; do not modify an item to
make the probe pass. Never infer DEV/TEST/PROD identity from matching names.

Then run with explicit identities and only authorized discovery workspaces:

```bash
python -m semantic_model_cleaner.service_probe run \
  --tenant-id <verified-tenant-guid> \
  --workspace-id <authorized-workspace-guid> \
  --model-id <inspected-model-guid> \
  --report-workspace-id <another-authorized-accessible-workspace-guid> \
  --evidence /tmp/smc-live.json \
  --private-output /tmp/smc-live-private
```

Omit the additional workspace option until such a workspace is authorized;
repeat it for further selected workspaces. The model workspace is always
included. The probe rechecks that the exact model ID is visible there. No
all-tenant enumeration or admin API is used. Normal owner access must not
silently become an admin workflow.

## Verified Microsoft API requirements (2026-10-12)

- [List Semantic Models](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/list-semantic-models):
  viewer workspace access and delegated `Workspace.Read.All` or
  `Workspace.ReadWrite.All`; paginated, with recursive workspace listing by
  default. Item-only access may therefore be insufficient for this probe.
- [Get Semantic Model Definition](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/get-semantic-model-definition):
  **read and write item permissions**, with `SemanticModel.ReadWrite.All` or
  `Item.ReadWrite.All`. The probe explicitly requests `TMDL`, not TMSL. Encrypted
  sensitivity labels block this endpoint; labels are not returned in the
  definition. Success is an observed capability, not proof of ownership.
- [Get Reports In Group](https://learn.microsoft.com/en-us/rest/api/power-bi/reports/get-reports-in-group):
  Power BI `Report.Read.All` or `Report.ReadWrite.All`. The returned `datasetId`
  identifies the direct Semantic Model. Available properties depend on the
  API and caller; absent type/binding metadata remains unknown. The API is
  workspace-scoped, not a guarantee that every tenant consumer is discoverable.
- [Get Report Definition](https://learn.microsoft.com/en-us/rest/api/fabric/report/items/get-report-definition):
  **read and write Report permissions**, with Fabric `Report.ReadWrite.All` or
  `Item.ReadWrite.All`. Encrypted sensitivity labels block retrieval. Having
  write permission on the model does not grant write permission on its Reports.
- [Report definition formats](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/report-definition):
  PBIR and PBIR-Legacy are distinct; retrieval reflects service storage. The
  probe does not request conversion or upgrade a legacy Report. Only enhanced
  PBIR parts are fed to the analyzer. A root `report.json` is a legacy-format
  limitation, not an empty successful scan. Retrieved `definition.pbir` must
  confirm the same exact model ID (`semanticmodelid` or `pbiModelDatabaseName`);
  names, local paths, ambiguous bindings and intervening rebinds are rejected.
- [Fabric LROs](https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation)
  and [pagination](https://learn.microsoft.com/en-us/rest/api/fabric/articles/pagination):
  follow operation state and result after 202; respect Retry-After, handle 429,
  and follow continuation URI/token. The probe also handles OData next links
  defensively, although the Power BI endpoint currently documents a collection
  response rather than a pagination contract. Continuations cannot change
  origin or workspace path. Redirects are disabled.
- [Impact-analysis privacy](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-dataset-impact-analysis):
  a writer can see aggregate impact for limited-access workspaces without
  seeing item names. This is not API definition access. Unknown consumers stay
  unknown; the probe cannot even give their exact count.

Unattended CI should use an already provisioned workload identity, such as a
service principal with federation/certificate or an eligible managed identity,
through an approved token provider or existing Azure CLI session. Do not use
user passwords or copy a user's token cache into CI. Each invoked API and item
must support the identity, and it needs appropriate workspace/item access.
Fabric's [identity support](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support)
requires the service-principal tenant setting for service principals/managed
identities; enabling it needs a Fabric administrator. Power BI has additional
[service-principal prerequisites](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-service-principal).
Those are explicit CI setup gates, not requirements silently added to the
interactive owner workflow. CI and its tenant configuration remain untested.

## Evidence and interpretation

Public JSON records per-request operation, alias, HTTP status and UTC time;
model/report definition format, part/byte count and content digest; workspace
enumeration result; Report states; actual parser counts; and capability gaps.
It omits tokens, raw URLs, tenant/source IDs, names, expressions, definition
payloads, response text and raw error messages. Source identities are mapped
to per-run aliases in the separate `identities.json` (directory 0700, file 0600
on Linux). Treat that file as private; inspect results include candidate names.
Definitions live in a private temporary directory and are removed when the
run ends. Evidence files are created exclusively and never overwritten.

Report states distinguish discovered, retrieved, analyzed, excluded,
inaccessible, unknown and not-analyzed stages. `retrieved_at` and definition
metadata preserve retrieval evidence after a Report reaches analyzed status.
A parsing gap can coexist with `analyzed`: that means the supported scanner ran,
not that every reference was covered. Report Health contains only parser Report
issue counts. Denied discovery/retrieval and unsupported input are Analysis
Limitations, never invented Report defects. Parser limitations are summarized
separately. All items with No Use Found In Scope remain Review in this service
projection; there are no cleanup actions or global non-use claims. Existing
offline analyzer results/contracts are not changed.

Read budgets are bounded: 30 seconds per HTTP call, 300 seconds of overall
request scheduling, 100 collection pages, 60 operation-state polls, at most
three 429 retries, and 64 MiB per response/decoded definition. A Retry-After
over 60 seconds produces an explicit retry-budget limitation instead of
retrying too early. The last in-flight request can extend the scheduling
budget by its timeout. No permission retry, admin escalation, decryption or
alternate export fallback is attempted. A generic unsupported-item response
is only *possible* encryption, never proof of a label's presence.

## Remaining live acceptance record

The proposed first-release boundary is **direct Power BI Reports visible in
explicitly selected accessible workspaces**, with enhanced PBIR retrieval and
TMDL model analysis. The probe implements that boundary; owner agreement and
live demonstration are still required before accepting it for #117–122.

Keep a private source-ID mapping and publish only aliases plus these facts:

1. Exact commit/wheel digest, OS/Python, UTC run times and evidence kind.
2. Intended tenant verified through authenticated workspace access; inspected
   candidates and reason for selecting the exact model ID.
3. Actual non-admin owner identity class, workspace roles, item permissions,
   delegated scopes, licensing/tenant settings relevant to successful calls.
   API success does not prove all of these; annotate independent owner/admin
   attestations rather than inventing them. Record the source/time of each.
4. Successful model and connected Report retrieval/analysis in the selected
   workspace and another authorized accessible workspace. Record inaccessible
   scope independently of what impact analysis shows.
5. Definition denial, encrypted labels, unsupported formats and missing binding
   metadata: distinguish live observations, synthetic tests and cases not tested.
6. Agreed boundary, unresolved limitations and owner go/no-go decision.

`permission_observations` and `live_acceptance` deliberately stay unverified in
automatic output. Supplement them with reviewed acceptance evidence; don't
edit fixture evidence to resemble live evidence. Leave #116 open without the
live record. All integration stays under `feature/service-validation`; any PR
must be draft against that branch, and nothing from this slice merges to main.
