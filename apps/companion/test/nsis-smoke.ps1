# CI-only disposable install. Never run an installer on a developer/user machine.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or -not $env:RUNNER_TEMP) {
  throw 'NSIS install smoke is restricted to disposable GitHub Windows runners'
}
$root = Join-Path $env:RUNNER_TEMP ('fa-nsis-' + [Guid]::NewGuid().ToString('N'))
$install = Join-Path $root 'application'
$profile = Join-Path $root 'user-data'
New-Item -ItemType Directory -Path $root | Out-Null
$installer = Get-ChildItem (Join-Path $PSScriptRoot '..\dist\FootballAssistant-*-Setup-x64.exe') | Select-Object -First 1
if (-not $installer) { throw 'NSIS Setup.exe artifact missing' }
$exe = Join-Path $install 'FootballAssistant.exe'
$uninstaller = Join-Path $install 'Uninstall FootballAssistant.exe'
function Invoke-Bounded([string]$file, [string]$arguments, [string]$stage, [int]$timeoutMs = 120000) {
  Write-Host "NSIS smoke: starting $stage (timeout ${timeoutMs}ms)"
  $process = Start-Process -FilePath $file -ArgumentList $arguments -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit($timeoutMs)) { $process.Kill(); throw "CI $stage timed out after ${timeoutMs}ms" }
  if ($process.ExitCode -ne 0) { throw "CI $stage failed with exit code $($process.ExitCode)" }
  Write-Host "NSIS smoke: completed $stage"
}
function Smoke-Installed([string]$name) {
  $env:FA_COMPANION_USER_DATA_DIR = $profile
  $env:FOOTBALL_ASSISTANT_SMOKE_REPORT = Join-Path $env:RUNNER_TEMP "companion-smoke-nsis-$name.json"
  $env:FOOTBALL_ASSISTANT_SMOKE_EXIT = '1'
  Remove-Item $env:FOOTBALL_ASSISTANT_SMOKE_REPORT -ErrorAction SilentlyContinue
  Invoke-Bounded $exe '--disable-background-networking' "application-$name"
  $report = Get-Content $env:FOOTBALL_ASSISTANT_SMOKE_REPORT -Raw | ConvertFrom-Json
  if ($report.platform -ne 'win32' -or $report.bootstrap.backend.state -ne 'ready' -or -not $report.bootstrap.backend.owned) { throw 'Installed app did not own a healthy bundled backend' }
  if (-not $report.renderer.bridge -or $report.renderer.nodeExposed) { throw 'Installed renderer isolation failed' }
  if ($report.renderer.ipcOk -ne $true) { throw 'Installed renderer IPC round trip failed' }
}
try {
  # /D must be the final argument; NSIS consumes the rest as an unquoted path.
  Invoke-Bounded $installer.FullName "/S /D=$install" 'initial-install' 300000
  if (-not (Test-Path $exe) -or -not (Test-Path $uninstaller)) { throw 'NSIS installation incomplete' }
  $channel = Get-Content (Join-Path $install 'installation.json') -Raw | ConvertFrom-Json
  if ($channel.distribution -ne 'nsis' -or $channel.schema -ne 1) { throw 'NSIS channel marker missing' }
  Smoke-Installed 'first-run'
  $settings = Join-Path $profile 'settings.json'
  $persona = Join-Path $profile 'backend\persona.md'
  if (-not (Test-Path $settings) -or -not (Test-Path $persona)) { throw 'First-run settings/persona not created' }
  Add-Content -Path $persona -Value "`nCI-only persona preservation marker."
  $settingsHash = (Get-FileHash $settings).Hash
  $personaHash = (Get-FileHash $persona).Hash
  # Synthetic only: assert account/history/memory files survive replacement and restart.
  $modelConfig = Join-Path $profile 'model-config.json'
  $credentialFile = Join-Path $profile 'credentials.enc.json'
  $conversationFile = Join-Path $profile 'companion-ui.json'
  '{"schema_version":1,"provider":"openai-compatible","baseUrl":"https://fixture.invalid/v1","model":"fixture-model"}' | Set-Content -LiteralPath $modelConfig -Encoding UTF8
  '{"schema_version":1,"ciphertext":"b3BhcXVlLXN5bnRoZXRpYy1jaXBoZXJ0ZXh0"}' | Set-Content -LiteralPath $credentialFile -Encoding UTF8
  '{"version":1,"historyEnabled":true,"fixtureExtension":"preserved","messages":[{"id":"fixture-history","role":"assistant","text":"synthetic history"}],"memories":[{"id":"fixture-memory","text":"synthetic memory"}]}' | Set-Content -LiteralPath $conversationFile -Encoding UTF8
  # Windows PowerShell UTF8 adds a BOM; the app JSON format is BOM-free.
  foreach ($dataFile in @($modelConfig, $credentialFile, $conversationFile)) {
    [IO.File]::WriteAllText($dataFile, [IO.File]::ReadAllText($dataFile), (New-Object Text.UTF8Encoding($false)))
  }
  $dataHashes = @{}
  foreach ($dataFile in @($modelConfig, $credentialFile)) { $dataHashes[$dataFile] = (Get-FileHash -LiteralPath $dataFile).Hash }
  # Same-version reinstall exercises the installer replacement path without a Release.
  Invoke-Bounded $installer.FullName "/S /D=$install" 'same-version-reinstall' 300000
  if ((Get-FileHash $settings).Hash -ne $settingsHash -or (Get-FileHash $persona).Hash -ne $personaHash) { throw 'Reinstall changed user settings/persona' }
  Smoke-Installed 'reinstall'
  foreach ($dataFile in $dataHashes.Keys) { if ((Get-FileHash -LiteralPath $dataFile).Hash -ne $dataHashes[$dataFile]) { throw 'Reinstall/restart changed synthetic account data' } }
  # Startup may normalize known defaults; preserve the content/schema, not its formatting.
  $conversation = Get-Content -LiteralPath $conversationFile -Raw | ConvertFrom-Json
  if ($conversation.version -ne 1 -or $conversation.historyEnabled -ne $true -or $conversation.fixtureExtension -ne 'preserved') { throw 'Restart lost conversation schema or extension data' }
  if (@($conversation.messages | Where-Object { $_.id -eq 'fixture-history' -and $_.role -eq 'assistant' -and $_.text -eq 'synthetic history' }).Count -ne 1) { throw 'Restart lost synthetic history' }
  if (@($conversation.memories | Where-Object { $_.id -eq 'fixture-memory' -and $_.text -eq 'synthetic memory' }).Count -ne 1) { throw 'Restart lost synthetic memory' }
  # The app has exited: uninstall must preserve these final persisted bytes exactly.
  $dataHashes[$conversationFile] = (Get-FileHash -LiteralPath $conversationFile).Hash
} finally {
  if (Test-Path $uninstaller) { Invoke-Bounded $uninstaller "/S _?=$install" 'uninstall' 300000 }
}
$deadline = (Get-Date).AddSeconds(15)
while ((Test-Path $exe) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
if (Test-Path $exe) { throw 'Uninstall left installed application executable' }
if ((Get-FileHash $settings).Hash -ne $settingsHash -or (Get-FileHash $persona).Hash -ne $personaHash) { throw 'Uninstall changed user settings/persona' }
foreach ($dataFile in $dataHashes.Keys) { if ((Get-FileHash -LiteralPath $dataFile).Hash -ne $dataHashes[$dataFile]) { throw 'Uninstall changed synthetic account or conversation data' } }
@{ installed = $true; backendReady = $true; reinstalled = $true; uninstalled = $true; settingsPreserved = $true; personaPreserved = $true; accountPreserved = $true; historyMemoryPreserved = $true; modelCalls = 0 } | ConvertTo-Json | Set-Content (Join-Path $env:RUNNER_TEMP 'companion-smoke-nsis-result.json')
