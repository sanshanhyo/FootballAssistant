# One explicitly approved fixed two-chunk manifest. No launch, retries or path overrides.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateDirectory,
    [Parameter(Mandatory=$true)][switch]$StableProfileAsserted,
    [Parameter(Mandatory=$true)][switch]$FiniteTwoChunksConfirmed
)
$ErrorActionPreference = 'Stop'
if (-not $StableProfileAsserted -or -not $FiniteTwoChunksConfirmed) { throw 'Explicit stable-profile assertion and fixed two-chunk approval required.' }
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
$root = Join-Path $CandidateDirectory 'windows-finite-rows-private'
Assert-NonReparse $root
$sessionPath = Join-Path $root 'session.json'
$session = Read-Bounded $sessionPath
if ($session.schema_version -ne 4 -or $session.mode -cne 'goalkeeper_rows0_3' -or
    $session.finite_rows_enabled_by_default -ne $false -or $session.raw_diagnostics_only -ne $true -or
    @($session.allowed_scopes) -cnotcontains 'goalkeeper_rows0_3' -or $session.window_class -cne 'UnityWndClass') { throw 'Unexpected finite rows session scope.' }
if ([string]$session.bridge_sha256 -cnotmatch '\A[0-9a-f]{64}\z' -or [string]$session.game_sha256 -cnotmatch '\A[0-9a-f]{64}\z' -or
    [string]::IsNullOrWhiteSpace([string]$session.session_id) -or ([string]$session.session_id).Length -gt 128 -or
    [string]$session.pid -cnotmatch '\A[1-9][0-9]*\z') { throw 'Invalid session binding.' }
$status = Read-Bounded (Join-Path $root 'module-status.json')
if ($status.state -cne 'ready' -or $status.pid -ne $session.pid -or $status.session_id -cne $session.session_id -or
    $status.bridge_sha256 -cne $session.bridge_sha256 -or $status.game_sha256 -cne $session.game_sha256) { throw 'Current-session module verification is not ready.' }
$process = Get-Process -Id $session.pid -ErrorAction Stop
if ($process.ProcessName -cne 'fm' -or (Get-Item -LiteralPath $sessionPath).LastWriteTimeUtc -lt $process.StartTime.ToUniversalTime()) { throw 'Session does not match live FM lifetime.' }
$state = Read-Bounded (Join-Path $root 'finite-rows-state.json')
if ($state.pid -ne $session.pid -or $state.session_id -cne $session.session_id -or $state.bridge_sha256 -cne $session.bridge_sha256 -or
    $state.terminal -ne $false -or $state.consumed -ne $false) { throw 'Discovery unavailable or already consumed.' }
$now = [DateTimeOffset]::UtcNow
$request = [ordered]@{
    schema_version = 4; mode = 'goalkeeper_rows0_3'; batch_id = [Guid]::NewGuid().ToString('D')
    page_epoch = [Guid]::NewGuid().ToString('D'); first_nonce = [Guid]::NewGuid().ToString('D'); second_nonce = [Guid]::NewGuid().ToString('D')
    pid = [int]$session.pid; session_id = $session.session_id; bridge_sha256 = $session.bridge_sha256; game_sha256 = $session.game_sha256
    window_class = $session.window_class; stable_profile_asserted = $true
    requested_at = $now.ToString('O'); expires_at = $now.AddSeconds(120).ToString('O')
}
$path = Join-Path $root 'finite-rows-request.json'
Assert-NonReparse $path
Assert-NonReparse ($path + '.tmp')
if ([IO.File]::Exists($path) -or [IO.File]::Exists($path + '.tmp')) { throw 'Existing request refused; no overwrite or retry.' }
$bytes = (New-Object Text.UTF8Encoding($false)).GetBytes(($request | ConvertTo-Json))
if ($bytes.Length -gt 4096) { throw 'Request exceeds bound.' }
$stream = [IO.File]::Open(($path + '.tmp'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Move-Item -LiteralPath ($path + '.tmp') -Destination $path
Write-Output 'Wrote one finite manifest: goalkeeper rows0..1 then2..3 only; at least2s cooldown; no retries or further chunks.'
Write-Output 'Each chunk: 2048 units /1000ms soft; total:4096 units /2000ms soft. Manifest expires120s. Stop on any failure.'
Write-Output 'Stable-profile and page-epoch are operator assertions, NOT verified page/player identity. Keep the same profile open; no navigation during this finite capture.'
