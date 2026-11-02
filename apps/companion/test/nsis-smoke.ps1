# CI-only rejection check. Never run an installer on a developer/user machine.
# Full reader installation needs a real, authorized FM directory, absent on hosted runners.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or -not $env:RUNNER_TEMP) {
  throw 'NSIS check is restricted to disposable GitHub Windows runners'
}
$root = Join-Path $env:RUNNER_TEMP ('fa-nsis-' + [Guid]::NewGuid().ToString('N'))
$install = Join-Path $root 'application'
$profile = Join-Path $root 'user-data'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$installer = Get-ChildItem (Join-Path $PSScriptRoot '..\dist\FootballAssistant-*-Setup-x64.exe') | Select-Object -First 1
if (-not $installer) { throw 'NSIS Setup.exe artifact missing' }
# Synthetic profile sentinels: rejection must not modify user settings or persona.
$settings = Join-Path $profile 'settings.json'
$persona = Join-Path $profile 'persona.md'
[IO.File]::WriteAllText($settings, '{"fixture":"preserve-on-rejected-install"}', (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($persona, 'CI-only persona preservation marker.', (New-Object Text.UTF8Encoding($false)))
$settingsHash = (Get-FileHash $settings).Hash
$personaHash = (Get-FileHash $persona).Hash
$env:FA_COMPANION_USER_DATA_DIR = $profile
# No /FM_DIR, no game assets, no production bypass flag. /D must remain last.
$process = Start-Process -FilePath $installer.FullName -ArgumentList "/S /D=$install" -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(120000)) {
  $process.Kill()
  throw 'Silent installer failed to reject missing game path without interaction'
}
if ($process.ExitCode -ne 3) { throw "Expected missing-game-path exit 3, got $($process.ExitCode)" }
if ((Test-Path (Join-Path $install 'FootballAssistant.exe')) -or (Test-Path (Join-Path $install 'installation.json'))) {
  throw 'Rejected installation left an installed application/channel marker'
}
if ((Get-FileHash $settings).Hash -ne $settingsHash -or (Get-FileHash $persona).Hash -ne $personaHash) {
  throw 'Rejected installation changed user settings/persona'
}
@{
  schema = 2
  silentMissingGamePathRejected = $true
  rejectionExitCode = $process.ExitCode
  noApplicationInstalled = $true
  settingsPreservedOnRejection = $true
  personaPreservedOnRejection = $true
  fullInstallation = 'not_run'
  reinstallUninstallLifecycle = 'not_run'
  actualGameDeployment = 'not_run'
  reason = 'Hosted runner has no authorized FM game directory; fail-closed rejection is not a completed installation.'
  modelCalls = 0
} | ConvertTo-Json | Set-Content (Join-Path $env:RUNNER_TEMP 'companion-smoke-nsis-result.json')
Write-Host 'Verified actual Setup.exe rejects silent fresh installation without FM path; full lifecycle NOT RUN.'
