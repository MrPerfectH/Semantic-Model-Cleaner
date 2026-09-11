$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$identityJson = python -c "import json; from semantic_model_cleaner import __release_channel__, __version__; print(json.dumps({'version': __version__, 'channel': __release_channel__}))"
if ($LASTEXITCODE -ne 0) { throw "Could not read package version" }
$identity = $identityJson | ConvertFrom-Json
$version = "$($identity.version)".Trim()
$channel = "$($identity.channel)".Trim()
if ($channel -ne "beta") { throw "Windows public-beta package must use the beta release channel" }

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --console `
  --name "Semantic Model Cleaner" `
  --paths "src" `
  --add-data "src/semantic_model_cleaner/templates;semantic_model_cleaner/templates" `
  --add-data "src/semantic_model_cleaner/static;semantic_model_cleaner/static" `
  --add-data "src/semantic_model_cleaner/schemas;semantic_model_cleaner/schemas" `
  --add-data "src/semantic_model_cleaner/demo_workspace;semantic_model_cleaner/demo_workspace" `
  packaging/windows/entrypoint.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$appDirectory = Join-Path $repoRoot "dist\Semantic Model Cleaner"
@{
  name = "Semantic Model Cleaner"
  version = $version
  release_channel = $channel
  packaging = "windows-x64-zip"
} | ConvertTo-Json | Set-Content -Path (Join-Path $appDirectory "release.json") -Encoding utf8
Copy-Item -Path (Join-Path $repoRoot "LICENSE") -Destination $appDirectory -Force
Copy-Item -Path (Join-Path $repoRoot "packaging\windows\README.txt") -Destination $appDirectory -Force

$zipName = "semantic-model-cleaner-windows-x64-$version.zip"
$zipPath = Join-Path $repoRoot "dist\$zipName"
if (Test-Path $zipPath) {
  Remove-Item $zipPath
}

Compress-Archive `
  -Path "$appDirectory\*" `
  -DestinationPath $zipPath

Write-Host "Created Windows artifact: $zipName"

$hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $zipName" | Set-Content -Path "$zipPath.sha256" -Encoding ascii
