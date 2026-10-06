# Windows release signing

Status: integration prepared; public signing has not been activated or verified. The published 0.4.0b4 ZIP remains unsigned. On 2026-10-05 the MSI machine had no code-signing certificate in either Windows personal certificate store. The cached Azure account could not authenticate a resource lookup (interactive authentication required), so no available cloud signing account was established.

The package workflow builds an unpackaged directory, optionally signs the application executable, verifies its Authenticode status and timestamp, then produces the ZIP and SHA-256 sidecar from those final bytes. `signature.json` records the verification result and certificate identity. A configured signing failure stops the release; it does not fall back to unsigned output. Pull-request builds remain unsigned and never log in to Azure. Third-party runtime files retain their upstream signatures; this integration signs the application's executable.

## Activate an existing signing identity

1. Obtain an Azure Artifact Signing account with completed public-trust identity validation and a certificate profile. Identity validation is an account-owner task. Do not use a self-signed or private-trust certificate for public distribution.
2. Configure an Entra application with GitHub OIDC federation for this repository's release tags (and main for manual validation), with **Artifact Signing Certificate Profile Signer** scoped to the certificate profile. Avoid broad subscription roles. Follow [Microsoft's OIDC setup](https://github.com/Azure/artifact-signing-action/blob/main/docs/OIDC.md) for the exact federation subject supported by the tenant.
3. Set these repository Actions variables: `SMC_SIGNING_CLIENT_ID`, `SMC_SIGNING_TENANT_ID`, `SMC_SIGNING_SUBSCRIPTION_ID`, `SMC_SIGNING_ENDPOINT`, `SMC_SIGNING_ACCOUNT`, `SMC_SIGNING_PROFILE`. Set `SMC_SIGNING_ENABLED=true` only after the identity/profile is ready. No certificate private key or client secret is stored in the repository.
4. Run **Public beta packages** manually on main. Verify the signing step and downloaded ZIP checks succeed; inspect the EXE's Digital Signatures tab and `signature.json` on a clean Windows machine.
5. Publish a new version/tag with release notes recording the signer and successful signed-artifact verification. Never replace the already-published unsigned 0.4.0b4 assets.

Local certificate users can run `build.ps1 -SkipArchive`, sign `dist/Semantic Model Cleaner/Semantic Model Cleaner.exe` using their approved signing tool, then run `archive.ps1 -RequireSignature`. Signature verification requires a trusted chain and an RFC 3161 timestamp. Signing identifies the publisher; it does not guarantee SmartScreen reputation or suppress every first-download warning.

References: [Artifact Signing prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart), [official GitHub action](https://github.com/Azure/artifact-signing-action). Public-trust eligibility depends on legal identity and region; an available Azure subscription alone is insufficient.
