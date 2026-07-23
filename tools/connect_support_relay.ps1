[CmdletBinding()]
param(
    [string]$RelayHost = '78.111.90.65',
    [string]$InspectorKey = (
        Join-Path $env:USERPROFILE `
            'OneDrive\Desktop\Keys\AlphaPOS Inspector\id_ed25519'
    ),
    [string]$KnownHostsFile = '',
    [ValidateRange(1024, 65535)]
    [int]$LocalDatabasePort = 25433,
    [ValidateRange(1024, 65535)]
    [int]$LocalApiPort = 28000,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRelay = '78.111.90.65'
$ExpectedRelayFingerprint = 'SHA256:1lLEF3N1MYR66gJGCGchrd5spzN6m9r/eWopf38uArQ'
$ExpectedInspectorFingerprint = 'SHA256:oruim7+5BsUAaL9D9SANGYOfiqMph6S4S9+p2TPZ+c8'

if ($RelayHost -cne $ExpectedRelay) {
    throw "This connector is pinned to relay $ExpectedRelay."
}
if ($LocalDatabasePort -eq $LocalApiPort) {
    throw 'The local database and API ports must be different.'
}

if (-not $KnownHostsFile) {
    $artifactPin = Join-Path $PSScriptRoot 'AlphaPOS-Support-Relay-Known-Hosts'
    $sourcePin = Join-Path $PSScriptRoot 'support_relay_known_hosts'
    $KnownHostsFile = if (Test-Path -LiteralPath $artifactPin -PathType Leaf) {
        $artifactPin
    } else {
        $sourcePin
    }
}

$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$keygen = Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe'
foreach ($required in @($ssh, $keygen, $InspectorKey, $KnownHostsFile)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required support connector file not found: $required"
    }
}

$pinLines = @(
    Get-Content -LiteralPath $KnownHostsFile |
        Where-Object { $_.Trim().Length -gt 0 }
)
if ($pinLines.Count -ne 1) {
    throw 'The relay pin file must contain exactly one non-empty host-key line.'
}
$pinFields = @($pinLines[0] -split '\s+')
if (
    $pinFields.Count -ne 3 -or
    $pinFields[0] -cne $ExpectedRelay -or
    $pinFields[1] -cne 'ssh-ed25519'
) {
    throw 'The relay pin file does not contain the expected exact Ed25519 host.'
}

$pinResult = @(& $keygen -lf $KnownHostsFile -E sha256 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "OpenSSH rejected the relay pin file: $($pinResult -join ' ')"
}
$pinText = $pinResult -join ' '
if ($pinText -notmatch 'SHA256:[^\s]+') {
    throw 'OpenSSH did not return a relay host-key fingerprint.'
}
$actualRelayFingerprint = $Matches[0]
if ($actualRelayFingerprint -cne $ExpectedRelayFingerprint) {
    throw (
        "Relay host-key fingerprint mismatch. Expected " +
        "$ExpectedRelayFingerprint; received $actualRelayFingerprint."
    )
}

# Loading the public half makes Windows OpenSSH enforce the private-key DACL.
& $keygen -y -f $InspectorKey 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'OpenSSH rejected the inspector private key or its Windows ACL.'
}
$keyResult = @(& $keygen -lf $InspectorKey -E sha256 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "OpenSSH could not fingerprint the inspector key: $($keyResult -join ' ')"
}
$keyText = $keyResult -join ' '
if ($keyText -notmatch 'SHA256:[^\s]+') {
    throw 'OpenSSH did not return an inspector-key fingerprint.'
}
$actualInspectorFingerprint = $Matches[0]
if ($actualInspectorFingerprint -cne $ExpectedInspectorFingerprint) {
    throw (
        "Inspector key mismatch. Expected $ExpectedInspectorFingerprint; " +
        "received $actualInspectorFingerprint."
    )
}

$connection = [ordered]@{
    relay = $ExpectedRelay
    account = 'alphapos-inspector'
    relay_fingerprint = $actualRelayFingerprint
    inspector_fingerprint = $actualInspectorFingerprint
    database = "127.0.0.1:$LocalDatabasePort"
    backend = "http://127.0.0.1:$LocalApiPort"
}

Write-Host 'Alpha POS support connector validated.' -ForegroundColor Green
Write-Host "Relay:       $($connection.relay)" -ForegroundColor DarkCyan
Write-Host "Host pin:    $($connection.relay_fingerprint)" -ForegroundColor DarkCyan
Write-Host "PostgreSQL:  $($connection.database)" -ForegroundColor Green
Write-Host "Backend API: $($connection.backend)" -ForegroundColor Green
Write-Host (
    'Safety gate: connect only while the restaurant desktop panel reports ' +
    '"DB Ready" and "Backend Ready".'
) -ForegroundColor Yellow
Write-Host (
    'Full-access warning: this connector grants full database and backend ' +
    'access. Protect the inspector key and close this window when finished.'
) -ForegroundColor Red

if ($ValidateOnly) {
    [pscustomobject]$connection
    return
}

Write-Host 'Keep this window open; press Ctrl+C to close both forwards.' `
    -ForegroundColor Yellow

$arguments = @(
    '-F', 'NUL',
    '-N', '-T',
    '-p', '22',
    '-i', $InspectorKey,
    '-o', 'BatchMode=yes',
    '-o', 'IdentitiesOnly=yes',
    '-o', 'IdentityAgent=none',
    '-o', 'PreferredAuthentications=publickey',
    '-o', 'PasswordAuthentication=no',
    '-o', 'KbdInteractiveAuthentication=no',
    '-o', 'GSSAPIAuthentication=no',
    '-o', 'HostbasedAuthentication=no',
    '-o', 'NumberOfPasswordPrompts=0',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=$KnownHostsFile",
    '-o', 'GlobalKnownHostsFile=NUL',
    '-o', 'HostKeyAlgorithms=ssh-ed25519',
    '-o', 'UpdateHostKeys=no',
    '-o', 'VerifyHostKeyDNS=no',
    '-o', 'CanonicalizeHostname=no',
    '-o', 'ProxyCommand=none',
    '-o', 'ProxyJump=none',
    '-o', 'PermitLocalCommand=no',
    '-o', 'ControlMaster=no',
    '-o', 'ControlPath=none',
    '-o', 'ForwardAgent=no',
    '-o', 'ForwardX11=no',
    '-o', 'RequestTTY=no',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'TCPKeepAlive=no',
    '-o', 'ConnectionAttempts=1',
    '-o', 'ConnectTimeout=10',
    '-o', 'LogLevel=ERROR',
    '-o', 'EscapeChar=none',
    '-L', "127.0.0.1:${LocalDatabasePort}:127.0.0.1:15433",
    '-L', "127.0.0.1:${LocalApiPort}:127.0.0.1:18000",
    "alphapos-inspector@$ExpectedRelay"
)

& $ssh @arguments
if ($LASTEXITCODE -ne 0) {
    throw "The support connector exited with code $LASTEXITCODE."
}
