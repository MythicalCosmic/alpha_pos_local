param(
    [string]$RelayHost = '78.111.90.65',
    [string]$RootKey = "$env:USERPROFILE\OneDrive\Desktop\Keys\alpha_pos.pem",
    [int]$LocalDatabasePort = 25433,
    [int]$LocalApiPort = 28000
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $RootKey -PathType Leaf)) {
    throw "Root SSH key not found: $RootKey"
}

Write-Host "Opening authorized Alpha POS support access..." -ForegroundColor Cyan
Write-Host "PostgreSQL: 127.0.0.1:$LocalDatabasePort (user postgres)" -ForegroundColor Green
Write-Host "Local API:  http://127.0.0.1:$LocalApiPort" -ForegroundColor Green
Write-Host 'Keep this window open; press Ctrl+C to close both forwards.' -ForegroundColor Yellow

& "$env:WINDIR\System32\OpenSSH\ssh.exe" `
    -N -T -i $RootKey -o BatchMode=yes -o ExitOnForwardFailure=yes `
    -L "127.0.0.1:${LocalDatabasePort}:127.0.0.1:15433" `
    -L "127.0.0.1:${LocalApiPort}:127.0.0.1:18000" `
    "root@$RelayHost"
