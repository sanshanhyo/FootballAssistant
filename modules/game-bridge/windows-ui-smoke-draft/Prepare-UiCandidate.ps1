# Records trusted pre-launch file evidence in the private candidate directory only.
# Does not install a proxy, change a game file, launch FM, or write a read request.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ExecutablePath,
    [Parameter(Mandatory=$true)][string]$GameAssemblyPath,
    [Parameter(Mandatory=$true)][string]$CandidateDirectory
)
$ErrorActionPreference = 'Stop'
if (Get-Process -Name fm -ErrorAction SilentlyContinue) { throw 'Close FM normally before recording pre-launch file identity.' }
function Assert-LocalPath([string]$Path) {
    if (-not ($Path -match '^[A-Za-z]:[\\/]')) { throw 'Absolute paths required.' }
    $item = [IO.Path]::GetFullPath($Path)
    while ($item) {
        if ([IO.File]::Exists($item) -or [IO.Directory]::Exists($item)) {
            if (([IO.File]::GetAttributes($item) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Reparse path refused: $item" }
        }
        $item = [IO.Path]::GetDirectoryName($item)
    }
}
foreach ($p in @($ExecutablePath, $GameAssemblyPath, $CandidateDirectory)) { Assert-LocalPath $p }
if (-not [IO.File]::Exists((Join-Path $CandidateDirectory 'FootballAssistant.WindowsUiCandidate.dll'))) { throw 'Candidate DLL is absent.' }
if ([IO.Path]::GetFileName($ExecutablePath) -ine 'fm.exe' -or [IO.Path]::GetFileName($GameAssemblyPath) -ine 'GameAssembly.dll') { throw 'Unexpected game filenames.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class FootballUiIdentity {
    [StructLayout(LayoutKind.Sequential)] public struct Info {
        public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh, WriteLow, WriteHigh;
        public uint VolumeSerial, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)] [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetFileInformationByHandle(SafeFileHandle file, out Info info);
}
'@
$exe = [IO.File]::Open($ExecutablePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
$game = $null
try {
    $game = [IO.File]::Open($GameAssemblyPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $exeHash = [BitConverter]::ToString($sha.ComputeHash($exe)).Replace('-','').ToLowerInvariant()
        $gameHash = [BitConverter]::ToString($sha.ComputeHash($game)).Replace('-','').ToLowerInvariant()
    } finally { $sha.Dispose() }
    if ($exeHash -ne '2a7318c6984bcb3a19ff3304432b63462581cee33ba203f9a0a118f11c69e27e') { throw 'fm.exe hash not approved.' }
    if ($gameHash -ne '820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a') { throw 'GameAssembly hash not approved.' }
    $info = New-Object FootballUiIdentity+Info
    if (-not [FootballUiIdentity]::GetFileInformationByHandle($game.SafeFileHandle, [ref]$info)) { throw 'File identity unavailable.' }
    [UInt64]$index = ([UInt64]$info.IndexHigh * 4294967296) + [UInt64]$info.IndexLow
    if ($index -eq 0) { throw 'Zero file identity rejected.' }
    if (Get-Process -Name fm -ErrorAction SilentlyContinue) { throw 'FM started during evidence capture; no configuration will be written.' }
    $configuration = [ordered]@{
        schema_version = 1; mode = 'ui_once'; exe_path = [IO.Path]::GetFullPath($ExecutablePath)
        game_path = [IO.Path]::GetFullPath($GameAssemblyPath); volume_serial = $info.VolumeSerial
        file_index = $index; window_class = 'UnityWndClass'; prelaunch_recorded_at = [DateTimeOffset]::UtcNow.ToString('O')
    }
    $path = Join-Path $CandidateDirectory 'footballassistant.windows-ui.json'
    Assert-LocalPath $path
    Assert-LocalPath ($path + '.tmp')
    [IO.File]::WriteAllText(($path + '.tmp'), ($configuration | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
    Write-Output "Recorded pre-launch identity; no launch/request/game file change performed: $path"
} finally { if ($game) { $game.Dispose() }; $exe.Dispose() }
