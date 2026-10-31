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
function Invoke-Bounded([string]$file, [string]$arguments) {
  $process = Start-Process -FilePath $file -ArgumentList $arguments -PassThru
  if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'CI installer/application process timed out' }
  if ($process.ExitCode -ne 0) { throw "CI process failed with exit code $($process.ExitCode)" }
}
function Smoke-Installed([string]$name) {
  $env:FA_COMPANION_USER_DATA_DIR = $profile
  $env:FOOTBALL_ASSISTANT_SMOKE_REPORT = Join-Path $env:RUNNER_TEMP "companion-smoke-nsis-$name.json"
  $env:FOOTBALL_ASSISTANT_SMOKE_EXIT = '1'
  Remove-Item $env:FOOTBALL_ASSISTANT_SMOKE_REPORT -ErrorAction SilentlyContinue
  Invoke-Bounded $exe '--disable-background-networking'
  $report = Get-Content $env:FOOTBALL_ASSISTANT_SMOKE_REPORT -Raw | ConvertFrom-Json
  if ($report.platform -ne 'win32' -or $report.bootstrap.backend.state -ne 'ready' -or -not $report.bootstrap.backend.owned) { throw 'Installed app did not own a healthy bundled backend' }
  if (-not $report.renderer.bridge -or $report.renderer.nodeExposed) { throw 'Installed renderer isolation failed' }
}
try {
  # /D must be the final argument; NSIS consumes the rest as an unquoted path.
  Invoke-Bounded $installer.FullName "/S /D=$install"
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
  # Same-version reinstall exercises the installer replacement path without a Release.
  Invoke-Bounded $installer.FullName "/S /D=$install"
  if ((Get-FileHash $settings).Hash -ne $settingsHash -or (Get-FileHash $persona).Hash -ne $personaHash) { throw 'Reinstall changed user settings/persona' }
  Smoke-Installed 'reinstall'
} finally {
  if (Test-Path $uninstaller) { Invoke-Bounded $uninstaller "/S _?=$install" }
}
$deadline = (Get-Date).AddSeconds(15)
while ((Test-Path $exe) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
if (Test-Path $exe) { throw 'Uninstall left installed application executable' }
if ((Get-FileHash $settings).Hash -ne $settingsHash -or (Get-FileHash $persona).Hash -ne $personaHash) { throw 'Uninstall changed user settings/persona' }
@{ installed = $true; backendReady = $true; reinstalled = $true; uninstalled = $true; settingsPreserved = $true; personaPreserved = $true; modelCalls = 0 } | ConvertTo-Json | Set-Content (Join-Path $env:RUNNER_TEMP 'companion-smoke-nsis-result.json')
