# One explicitly authorized current-session diagnostic request. No launch, fallback or retry.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateDirectory,
    [Parameter(Mandatory=$true)][switch]$UnverifiedProfileBodyDiagnosticsConfirmed,
    [ValidateSet('profile_body','goalkeeper_row0')][string]$Scope = 'profile_body'
)
$ErrorActionPreference = 'Stop'
if (-not $UnverifiedProfileBodyDiagnosticsConfirmed) { throw 'Explicit raw profile-body diagnostic confirmation required.' }
if ($CandidateDirectory -notmatch '^[A-Za-z]:[\\/]') { throw 'Absolute private candidate directory required.' }
function Assert-NonReparse([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) -and
            (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'Reparse path refused.' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
function Read-Bounded([string]$Path) {
    Assert-NonReparse $Path
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt 1 -or $file.Length -gt 4096) { throw 'Private status size outside bounds.' }
    $value = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
    Assert-NonReparse $Path
    return $value
}
$root = Join-Path $CandidateDirectory 'windows-discovery-private'
Assert-NonReparse $root
$sessionPath = Join-Path $root 'session.json'
$session = Read-Bounded $sessionPath
if ($session.schema_version -ne 3 -or $session.mode -cne 'ui_discovery_once' -or
    $session.discovery_enabled_by_default -ne $false -or $session.raw_diagnostics_only -ne $true -or
    $session.panel_index -ne 0 -or $session.focus_path -cne '0/6' -or $session.window_class -cne 'UnityWndClass') { throw 'Unexpected discovery session scope.' }
$focusPath = '0/6'
if ($Scope -eq 'goalkeeper_row0') {
    if (@($session.allowed_scopes) -cnotcontains 'goalkeeper_row0') { throw 'This session does not advertise the explicit goalkeeper row0 scope.' }
    $focusPath = '0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0'
}
if ([string]$session.bridge_sha256 -cnotmatch '\A[0-9a-f]{64}\z' -or [string]$session.game_sha256 -cnotmatch '\A[0-9a-f]{64}\z' -or
    [string]::IsNullOrWhiteSpace([string]$session.session_id) -or ([string]$session.session_id).Length -gt 128 -or
    [string]$session.pid -cnotmatch '\A[1-9][0-9]*\z') { throw 'Invalid session binding.' }
$status = Read-Bounded (Join-Path $root 'module-status.json')
if ($status.state -cne 'ready' -or $status.pid -ne $session.pid -or $status.session_id -cne $session.session_id -or
    $status.bridge_sha256 -cne $session.bridge_sha256 -or $status.game_sha256 -cne $session.game_sha256) { throw 'Current-session module verification is not ready.' }
$process = Get-Process -Id $session.pid -ErrorAction Stop
if ($process.ProcessName -cne 'fm' -or (Get-Item -LiteralPath $sessionPath).LastWriteTimeUtc -lt $process.StartTime.ToUniversalTime()) { throw 'Session does not match live FM lifetime.' }
$state = Read-Bounded (Join-Path $root 'discovery-state.json')
if ($state.pid -ne $session.pid -or $state.session_id -cne $session.session_id -or $state.bridge_sha256 -cne $session.bridge_sha256 -or
    $state.terminal -ne $false -or $state.consumed -ne $false) { throw 'Discovery unavailable or already consumed.' }
$now = [DateTimeOffset]::UtcNow
$request = [ordered]@{
    schema_version = 3; nonce = [Guid]::NewGuid().ToString('D'); pid = [int]$session.pid
    session_id = $session.session_id; bridge_sha256 = $session.bridge_sha256; game_sha256 = $session.game_sha256
    window_class = $session.window_class; checkpoint = 'unverified_profile_body_diagnostics'
    panel_index = 0; focus_path = $focusPath
    requested_at = $now.ToString('O'); expires_at = $now.AddSeconds(30).ToString('O')
}
$path = Join-Path $root 'discovery-request.json'
Assert-NonReparse $path
Assert-NonReparse ($path + '.tmp')
if ([IO.File]::Exists($path) -or [IO.File]::Exists($path + '.tmp')) { throw 'Existing request refused; no overwrite or retry.' }
$bytes = (New-Object Text.UTF8Encoding($false)).GetBytes(($request | ConvertTo-Json))
if ($bytes.Length -gt 4096) { throw 'Request exceeds bound.' }
$stream = [IO.File]::Open(($path + '.tmp'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Move-Item -LiteralPath ($path + '.tmp') -Destination $path
Write-Output "Wrote one 30-second request: scope $Scope, panel 0, focus $focusPath, 1000ms soft / 2048 reserved units. No retry or next chunk."
Write-Output 'Raw unverified profile-body diagnostics only; no page identity, complete profile, business-field or speed guarantee.'
if ($Scope -eq 'goalkeeper_row0') {
    Write-Output 'Fixed category title + row0 label/value only; global depth48, at most3 complete texts, same96nodes/64live/512total roots. No other row, fallback or retry.'
} else {
    Write-Output 'Original profile-body DFS remains global depth32, first8children, at most8texts; no scope fallback.'
}
