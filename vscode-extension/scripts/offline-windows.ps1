param([Parameter(Mandatory=$true)][string]$NodeExecutable,
      [Parameter(Mandatory=$true)][string]$ChildScript)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Offline firewall verification requires an elevated shell.'
}
$profiles = @(Get-NetFirewallProfile)
$disabled = @($profiles | Where-Object { -not $_.Enabled })
if ($disabled.Count -gt 0 -and $env:GITHUB_ACTIONS -ne 'true') {
    throw 'Firewall profiles are disabled. No settings were changed on this computer.'
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('smc-offline-' + [guid]::NewGuid().ToString('N'))
$group = 'SMC disposable offline test ' + [guid]::NewGuid().ToString('N')
$engine = Join-Path $env:SMC_ENGINE_EXTENSION 'engine\smc-engine.exe'
if (-not (Test-Path $engine)) { throw 'Set SMC_ENGINE_EXTENSION to the disposable installed extension.' }
New-Item -ItemType Directory -Path $temporary | Out-Null
$node = Join-Path $temporary 'node.exe'
Copy-Item $NodeExecutable $node
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class SmcOfflinePaths {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern uint GetLongPathName(string path, StringBuilder output, uint length);
}
'@
function Expand-ProgramPath([string]$Path) {
    $buffer = [Text.StringBuilder]::new(32768)
    $length = [SmcOfflinePaths]::GetLongPathName($Path, $buffer, $buffer.Capacity)
    if ($length -eq 0 -or $length -ge $buffer.Capacity) { throw "Cannot resolve program path: $Path" }
    return $buffer.ToString()
}
$node = Expand-ProgramPath $node
$engine = Expand-ProgramPath $engine
try {
    # Only ephemeral CI runners may temporarily enable disabled firewall profiles.
    foreach ($profile in $disabled) { Set-NetFirewallProfile -Profile $profile.Name -Enabled True }
    # Program-scoped rules avoid reserved-address prefix restrictions. The test
    # requires both a blocked external probe and working Win32 loopback traffic.
    foreach ($program in @($node, $engine)) {
        Write-Output ('Offline firewall program: ' + $program)
        New-NetFirewallRule -DisplayName ($group + ' ' + [IO.Path]::GetFileName($program)) -Group $group `
            -Direction Outbound -Action Block -Program $program -RemoteAddress Any `
            -Profile Any -Enabled True | Out-Null
    }
    & $node $ChildScript
    if ($LASTEXITCODE -ne 0) { throw 'Offline engine verification failed.' }
} finally {
    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    foreach ($profile in $disabled) { Set-NetFirewallProfile -Profile $profile.Name -Enabled False }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
