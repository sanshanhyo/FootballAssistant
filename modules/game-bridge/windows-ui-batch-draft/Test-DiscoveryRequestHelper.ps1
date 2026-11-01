# Offline fixture only. All process lookup is a local function; no FM or native API access.
$ErrorActionPreference = 'Stop'
$directory = Join-Path ([IO.Path]::GetTempPath()) ('discovery-helper-fixture-' + [Guid]::NewGuid().ToString('N'))
$root = Join-Path $directory 'windows-discovery-private'
[void][IO.Directory]::CreateDirectory($root)
$helper = Join-Path $PSScriptRoot 'Request-Discovery.ps1'
$processLookupCounter = [pscustomobject]@{ Count = 0 }
function Get-Process {
    [CmdletBinding()] param([int]$Id)
    if ($Id -ne 12345) { throw 'Fixture received unexpected process id.' }
    $processLookupCounter.Count++
    return [pscustomobject]@{ ProcessName = 'fm'; StartTime = [DateTime]::UtcNow.AddHours(-1) }
}
function Check([bool]$Condition, [string]$Message) { if (-not $Condition) { throw "Discovery helper fixture: $Message" } }
function Save([string]$Name, $Value) {
    [IO.File]::WriteAllText((Join-Path $root $Name), ($Value | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
function Reset-Fixture {
    Remove-Item -LiteralPath (Join-Path $root 'discovery-request.json') -Force -ErrorAction SilentlyContinue
    $script:Session = [ordered]@{ schema_version=3; mode='ui_discovery_once'; discovery_enabled_by_default=$false
        raw_diagnostics_only=$true; panel_index=0; focus_path='0/6'; window_class='UnityWndClass'
        pid=12345; session_id='offline-fixture'; bridge_sha256=('a'*64); game_sha256=('b'*64) }
    $script:Status = [ordered]@{ state='ready'; pid=12345; session_id='offline-fixture'; bridge_sha256=('a'*64); game_sha256=('b'*64) }
    $script:State = [ordered]@{ pid=12345; session_id='offline-fixture'; bridge_sha256=('a'*64); terminal=$false; consumed=$false }
    Save 'session.json' $script:Session; Save 'module-status.json' $script:Status; Save 'discovery-state.json' $script:State
}
function Reject-Invocation([bool]$Confirmed = $true) {
    $rejected = $false
    try { & $helper -CandidateDirectory $directory -UnverifiedProfileBodyDiagnosticsConfirmed:$Confirmed | Out-Null }
    catch { $rejected = $true }
    Check $rejected 'invalid fixture must reject'
    Check (-not [IO.File]::Exists((Join-Path $root 'discovery-request.json'))) 'failed validation must not create request'
}
try {
    Reset-Fixture
    & $helper -CandidateDirectory $directory -UnverifiedProfileBodyDiagnosticsConfirmed | Out-Null
    $path = Join-Path $root 'discovery-request.json'
    $original = [IO.File]::ReadAllText($path); $request = $original | ConvertFrom-Json
    Check ($request.schema_version -eq 3 -and $request.panel_index -eq 0 -and $request.focus_path -ceq '0/6' -and
        $request.checkpoint -ceq 'unverified_profile_body_diagnostics') 'fixed schema and scope'
    Check ($request.pid -eq 12345 -and $request.session_id -ceq 'offline-fixture') 'fake session binding'
    $nonce = [Guid]::Empty
    Check ([Guid]::TryParseExact($request.nonce, 'D', [ref]$nonce) -and $nonce -ne [Guid]::Empty) 'fresh canonical nonce'
    Check (([DateTimeOffset]::Parse($request.expires_at) - [DateTimeOffset]::Parse($request.requested_at)).TotalSeconds -eq 30) '30-second lifetime'
    $refused = $false
    try { & $helper -CandidateDirectory $directory -UnverifiedProfileBodyDiagnosticsConfirmed | Out-Null } catch { $refused = $true }
    Check ($refused -and [IO.File]::ReadAllText($path) -ceq $original) 'existing request cannot be replaced'
    foreach ($case in @('terminal','consumed','scope','panel','module','session','confirmation')) {
        Reset-Fixture
        switch ($case) {
            terminal { $script:State.terminal=$true; Save 'discovery-state.json' $script:State }
            consumed { $script:State.consumed=$true; Save 'discovery-state.json' $script:State }
            scope { $script:Session.focus_path='0/7'; Save 'session.json' $script:Session }
            panel { $script:Session.panel_index=1; Save 'session.json' $script:Session }
            module { $script:Status.game_sha256=('c'*64); Save 'module-status.json' $script:Status }
            session { $script:State.session_id='stale'; Save 'discovery-state.json' $script:State }
        }
        Reject-Invocation ($case -ne 'confirmation')
    }
    Check ($processLookupCounter.Count -gt 0) 'helper actually invoked mocked process lookup'
    Write-Output 'Discovery request helper offline fixture passed; no real process lookup or game call.'
}
finally { Remove-Item -LiteralPath $directory -Recurse -Force }
