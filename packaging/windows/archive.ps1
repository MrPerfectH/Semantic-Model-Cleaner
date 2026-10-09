param([switch]$RequireSignature)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$appDirectory = Join-Path $repoRoot "dist\Semantic Model Cleaner"
$manifest = Get-Content -LiteralPath (Join-Path $appDirectory "release.json") -Raw | ConvertFrom-Json
if ($manifest.version -notmatch '^\d+\.\d+\.\d+b\d+$') { throw "Invalid beta package version" }
$exe = Join-Path $appDirectory "Semantic Model Cleaner.exe"
$signature = Get-AuthenticodeSignature -LiteralPath $exe
if ($RequireSignature) {
  if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or -not $signature.TimeStamperCertificate) {
    throw "A valid, timestamped public-trust signature is required before packaging: $($signature.Status)"
  }
}
$signatureEvidence = @{
  status = "$($signature.Status)"
  signature_required = [bool]$RequireSignature
  signer_subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
  signer_thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
  timestamped = [bool]$signature.TimeStamperCertificate
}
$signatureEvidence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appDirectory "signature.json") -Encoding utf8
$zipName = "semantic-model-cleaner-windows-x64-$($manifest.version).zip"
$zipPath = Join-Path $repoRoot "dist\$zipName"
Compress-Archive -Path "$appDirectory\*" -DestinationPath $zipPath -Force
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
# LF line ending so `sha256sum -c` accepts the sidecar on Linux and macOS; matches scripts/release_checksums.py
[System.IO.File]::WriteAllText("$zipPath.sha256", "$hash  $zipName`n", [System.Text.Encoding]::ASCII)
Write-Host "Created Windows artifact: $zipName (signature: $($signature.Status))"
