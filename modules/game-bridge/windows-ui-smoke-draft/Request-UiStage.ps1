# Invoke ONLY after root/user confirms this new session is at the a stable page in this new session (main menu or the authorized temporary test career).
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('metadata','ui_resolve','ui_text')][string]$Stage,
    [Parameter(Mandatory=$true)][switch]$StableCurrentSessionPageConfirmed,
    [ValidatePattern('\A(0|[1-9]|[12][0-9]|3[01])\z')][string]$PanelIndex = '0'
)
$ErrorActionPreference = 'Stop'
if ($PSBoundParameters.ContainsKey('PanelIndex') -and $Stage -ne 'ui_text') { throw 'Explicit -PanelIndex is supported only for ui_text.' }
if (-not $StableCurrentSessionPageConfirmed) { throw 'Current-session stable-page confirmation required.' }
if (-not ($CandidateDirectory -match '^[A-Za-z]:[\\/]')) { throw 'Absolute private candidate directory required.' }
$root = Join-Path $CandidateDirectory 'windows-ui-private'
foreach ($p in @($CandidateDirectory, $root)) {
    $cursor = [IO.Path]::GetFullPath($p)
    while ($cursor) {
        if (([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) -and
            (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'Reparse path refused.' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
$sessionPath = Join-Path $root 'session.json'
if (([IO.File]::GetAttributes($sessionPath) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse session refused.' }
$sessionFile = Get-Item -LiteralPath $sessionPath
if ($sessionFile.Length -gt 4096) { throw 'Session file too large.' }
$session = [IO.File]::ReadAllText($sessionPath) | ConvertFrom-Json
if ($session.mode -ne 'ui_once_metadata_first' -or $session.ui_enabled_by_default -ne $false) { throw 'Unexpected session mode.' }
$statusPath = Join-Path $root 'module-status.json'
if (([IO.File]::GetAttributes($statusPath) -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    (Get-Item -LiteralPath $statusPath).Length -gt 4096) { throw 'Invalid module status file.' }
$status = [IO.File]::ReadAllText($statusPath) | ConvertFrom-Json
if ($status.state -ne 'ready' -or $status.pid -ne $session.pid -or $status.session_id -ne $session.session_id -or
    $status.bridge_sha256 -ne $session.bridge_sha256 -or $status.game_sha256 -ne $session.game_sha256) { throw 'Current-session module verification is not ready.' }
$process = Get-Process -Id $session.pid -ErrorAction Stop
if ($process.ProcessName -ne 'fm' -or $sessionFile.LastWriteTimeUtc -lt $process.StartTime.ToUniversalTime()) { throw 'Session does not match live FM lifetime.' }
$statePath = Join-Path $root 'stage-state.json'
if (([IO.File]::GetAttributes($statePath) -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    (Get-Item -LiteralPath $statePath).Length -gt 4096) { throw 'Invalid stage state file.' }
$state = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
if ($state.pid -ne $session.pid -or $state.session_id -ne $session.session_id -or
    $state.bridge_sha256 -ne $session.bridge_sha256 -or $state.terminal -ne $false) { throw 'Session stage unavailable/terminal.' }
if ($Stage -eq 'metadata' -and $state.metadata_succeeded) { throw 'Metadata already consumed.' }
if ($Stage -eq 'ui_resolve' -and (-not $state.metadata_succeeded -or $state.resolve_succeeded)) { throw 'Resolve requires successful metadata and unused resolve stage.' }
if ($Stage -eq 'ui_text' -and (-not $state.resolve_succeeded -or $state.ui_completed)) { throw 'Capture requires successful resolve and unused capture stage.' }
$now = [DateTimeOffset]::UtcNow
$request = [ordered]@{
    schema_version = 1; stage = $Stage; nonce = [Guid]::NewGuid().ToString('D'); pid = $session.pid
    session_id = $session.session_id; bridge_sha256 = $session.bridge_sha256; game_sha256 = $session.game_sha256
    window_class = $session.window_class; checkpoint = 'stable_current_session_page'
    requested_at = $now.ToString('O'); expires_at = $now.AddSeconds(30).ToString('O')
}
if ($PSBoundParameters.ContainsKey('PanelIndex')) { $request['panel_index'] = [int]$PanelIndex }
$path = Join-Path $root 'ui-stage-request.json'
foreach ($p in @($path, ($path + '.tmp'))) {
    if ([IO.File]::Exists($p) -and (([IO.File]::GetAttributes($p) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'Reparse request refused.' }
}
[IO.File]::WriteAllText(($path + '.tmp'), ($request | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
Write-Output "Wrote one 30-second $Stage request for PID $($session.pid), session $($session.session_id). No subsequent stage is automatic."
if ($Stage -eq 'ui_text') {
    Write-Output "Requested panel index: $PanelIndex. One panel only; unavailable index is terminal, with no fallback."
    Write-Output 'Capture limits: 250ms soft elapsed, 384 reserved boundary units, one panel, 32 nodes, depth 8, 8 children/node, one text up to128 UTF-16 units; no retry. Text is a UI component value, not proof of screen visibility or business meaning.'
}
