# Offline only: local function mocks every process lookup. Never accesses FM.
$ErrorActionPreference='Stop'
$directory=Join-Path ([IO.Path]::GetTempPath()) ('finite-rows-fixture-'+[Guid]::NewGuid().ToString('N'))
$root=Join-Path $directory 'windows-finite-rows-private'
[void][IO.Directory]::CreateDirectory($root)
$helper=Join-Path $PSScriptRoot 'Request-FiniteRows.ps1'
$counter=[pscustomobject]@{Count=0}
function Get-Process {
    [CmdletBinding()] param([int]$Id)
    if($Id -ne 12345){throw 'Unexpected fixture PID.'}
    $counter.Count++
    return [pscustomobject]@{ProcessName='fm';StartTime=[DateTime]::UtcNow.AddHours(-1)}
}
function Check([bool]$Condition,[string]$Reason){if(-not $Condition){throw "Finite helper fixture: $Reason"}}
function Save([string]$Name,$Value){[IO.File]::WriteAllText((Join-Path $root $Name),($Value|ConvertTo-Json),[Text.UTF8Encoding]::new($false))}
function Reset-Fixture {
    Remove-Item -LiteralPath (Join-Path $root 'finite-rows-request.json') -Force -ErrorAction SilentlyContinue
    $script:Session=[ordered]@{schema_version=4;mode='goalkeeper_rows0_3';finite_rows_enabled_by_default=$false
        raw_diagnostics_only=$true;allowed_scopes=@('goalkeeper_rows0_3');window_class='UnityWndClass'
        pid=12345;session_id='offline-fixture';bridge_sha256=('a'*64);game_sha256=('b'*64)}
    $script:Status=[ordered]@{state='ready';pid=12345;session_id='offline-fixture';bridge_sha256=('a'*64);game_sha256=('b'*64)}
    $script:State=[ordered]@{pid=12345;session_id='offline-fixture';bridge_sha256=('a'*64);terminal=$false;consumed=$false}
    Save 'session.json' $script:Session;Save 'module-status.json' $script:Status;Save 'finite-rows-state.json' $script:State
}
try {
    Reset-Fixture
    & $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteTwoChunksConfirmed | Out-Null
    $path=Join-Path $root 'finite-rows-request.json';$original=[IO.File]::ReadAllText($path);$request=$original|ConvertFrom-Json
    Check ($request.schema_version -eq 4 -and $request.mode -ceq 'goalkeeper_rows0_3' -and $request.stable_profile_asserted -eq $true) 'fixed manifest'
    Check ($request.pid -eq 12345 -and $request.session_id -ceq 'offline-fixture') 'session bound'
    foreach($name in @('batch_id','page_epoch','first_nonce','second_nonce')){
        $id=[Guid]::Empty
        Check ([Guid]::TryParseExact($request.$name,'D',[ref]$id) -and $id -ne [Guid]::Empty) 'canonical nonempty IDs'
    }
    Check ($request.first_nonce -cne $request.second_nonce) 'distinct child nonces'
    Check (($request.PSObject.Properties.Name -notcontains 'focus_path') -and ($request.PSObject.Properties.Name -notcontains 'rows')) 'no arbitrary selectors'
    Check (([DateTimeOffset]::Parse($request.expires_at)-[DateTimeOffset]::Parse($request.requested_at)).TotalSeconds -eq 120) 'finite expiry'
    $refused=$false
    try{& $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteTwoChunksConfirmed|Out-Null}catch{$refused=$true}
    Check ($refused -and [IO.File]::ReadAllText($path) -ceq $original) 'existing manifest cannot be replaced'
    foreach($scope in @('profile_rows0_3','profile_all_rows','tactics_current','next_match_card','schedule_rows0_9')){
        Reset-Fixture
        $refused=$false
        try{& $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteManifestConfirmed -Scope $scope|Out-Null}catch{$refused=$true}
        Check ($refused -and -not [IO.File]::Exists($path)) 'old session cannot admit new manifest'
        $script:Session.allowed_scopes=@('goalkeeper_rows0_3','profile_rows0_3','profile_all_rows','tactics_current','next_match_card','schedule_rows0_9');Save 'session.json' $script:Session
        $oldConsentRefused=$false
        try{& $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteTwoChunksConfirmed -Scope $scope|Out-Null}catch{$oldConsentRefused=$true}
        Check ($oldConsentRefused -and -not [IO.File]::Exists($path)) 'old two-chunk confirmation cannot authorize expanded manifest'
        & $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteManifestConfirmed -Scope $scope|Out-Null
        $expanded=[IO.File]::ReadAllText($path)|ConvertFrom-Json
        Check ($expanded.mode -ceq $scope -and $expanded.schema_version -eq 4 -and $expanded.PSObject.Properties.Name.Count -eq 14) 'exact14field selected manifest'
        Check (($expanded.PSObject.Properties.Name -notcontains 'focus_path') -and ($expanded.PSObject.Properties.Name -notcontains 'profiles')) 'no arbitrary subset/path'
    }
    Reset-Fixture
    $refused=$false
    try{& $helper -CandidateDirectory $directory -StableProfileAsserted -FiniteManifestConfirmed -Scope profile_arbitrary|Out-Null}catch{$refused=$true}
    Check ($refused -and -not [IO.File]::Exists($path)) 'unknown manifest rejected'
    foreach($case in @('terminal','consumed','scope','module','session','stable','approval')){
        Reset-Fixture
        switch($case){
            terminal{$script:State.terminal=$true;Save 'finite-rows-state.json' $script:State}
            consumed{$script:State.consumed=$true;Save 'finite-rows-state.json' $script:State}
            scope{$script:Session.allowed_scopes=@('profile_body');Save 'session.json' $script:Session}
            module{$script:Status.game_sha256=('c'*64);Save 'module-status.json' $script:Status}
            session{$script:State.session_id='stale';Save 'finite-rows-state.json' $script:State}
        }
        $refused=$false
        try{& $helper -CandidateDirectory $directory -StableProfileAsserted:($case -ne 'stable') -FiniteTwoChunksConfirmed:($case -ne 'approval')|Out-Null}catch{$refused=$true}
        Check ($refused -and -not [IO.File]::Exists($path)) 'invalid evidence cannot write manifest'
    }
    Check ($counter.Count -gt 0) 'actual helper exercised mocked process lookup'
    Write-Output 'Finite rows request helper offline fixture passed; no real process lookup or game call.'
}
finally{Remove-Item -LiteralPath $directory -Recurse -Force}
