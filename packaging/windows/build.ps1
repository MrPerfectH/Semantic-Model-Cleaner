$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$version = python -c "from semantic_model_cleaner import __version__; print(__version__)"
$version = "$version".Trim()

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --console `
  --name "Semantic Model Cleaner" `
  --add-data "src/semantic_model_cleaner/templates;semantic_model_cleaner/templates" `
  --add-data "src/semantic_model_cleaner/demo_workspace;semantic_model_cleaner/demo_workspace" `
  src/semantic_model_cleaner/windows_launcher.py

$zipName = "semantic-model-cleaner-windows-x64-$version.zip"
$zipPath = Join-Path $repoRoot "dist\$zipName"
if (Test-Path $zipPath) {
  Remove-Item $zipPath
}

Compress-Archive `
  -Path "dist\Semantic Model Cleaner\*" `
  -DestinationPath $zipPath

Write-Host "Created Windows artifact: $zipName"
