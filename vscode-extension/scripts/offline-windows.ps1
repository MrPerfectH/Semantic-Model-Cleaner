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
try {
    # Only ephemeral CI runners may temporarily enable disabled firewall profiles.
    foreach ($profile in $disabled) { Set-NetFirewallProfile -Profile $profile.Name -Enabled True }
    # CIDRs avoid Windows' rejection of ranges spanning reserved IPv6 addresses.
    # Cleaner binds IPv4 loopback only; block every other IPv4 address and all IPv6.
    $outsideLoopback = @('0.0.0.0/2', '64.0.0.0/3', '96.0.0.0/4', '112.0.0.0/5',
                        '120.0.0.0/6', '124.0.0.0/7', '126.0.0.0/8', '128.0.0.0/1', '::/0')
    foreach ($program in @($node, $engine)) {
        New-NetFirewallRule -DisplayName ($group + ' ' + [IO.Path]::GetFileName($program)) -Group $group `
            -Direction Outbound -Action Block -Program $program -RemoteAddress $outsideLoopback `
            -Profile Any -Enabled True | Out-Null
    }
    & $node $ChildScript
    if ($LASTEXITCODE -ne 0) { throw 'Offline engine verification failed.' }
} finally {
    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    foreach ($profile in $disabled) { Set-NetFirewallProfile -Profile $profile.Name -Enabled False }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
