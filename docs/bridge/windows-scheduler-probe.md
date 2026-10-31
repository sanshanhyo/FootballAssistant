# Windows scheduler probe candidate — NOT a production UI reader

This code only records thread/window identities. No switch enables Windows native reads.
The Doorstop Windows branch does not construct `BridgeRuntime`, `NativeUiReader`, publishers,
registry probes or native observers. Both BridgeRuntime and optional BepInEx Plugin reject
Windows as defense in depth. Mac scheduling and cached pthread-main-thread behavior are unchanged.

## Why this mechanism

Official Doorstop v4.6.0 redirects Windows `il2cpp_init`, calls the original synchronously,
then initializes CoreCLR and directly invokes `Doorstop.Entrypoint.Start` on that caller.
This establishes caller continuity, **not** that FM's caller is its Unity PlayerLoop thread.

- https://github.com/NeighTools/UnityDoorstop/blob/v4.6.0/src/windows/entrypoint.c#L142
- https://github.com/NeighTools/UnityDoorstop/blob/v4.6.0/src/bootstrap.c#L277-L301
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-settimer
- https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-timer
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-killtimer

A NULL-HWND timer belongs to its installing thread and requires its existing message pump.
We neither start a new message pump nor patch window procedures. Timers can starve or never
fire. Callback identity is observed on every tick; no callback/thread affinity is assumed.
A window-owner match is necessary but not a claim of Unity-safe timing; nested message
pumping can occur outside the intended frame phase. Official BepInEx's current
IL2CPPChainloader has no MainThreadTick event; this path does not rely on that extension.

## Minimal configuration after separate loader-install authorization

Use the audited official x64 Doorstop release and matching official x64 .NET 10 runtime
(the direct project targets net10.0). Select the proxy name only after checking executable /
UnityPlayer imports. Check existing files before writing anything; preserve hashes and a
rollback manifest. This document does not authorize an installation or a game launch.

```ini
[General]
enabled=true
target_assembly=C:\approved-private-location\FootballAssistant.GameBridge.dll
redirect_output_log=false
ignore_disable_switch=false
[Il2Cpp]
coreclr_path=C:\approved-private-location\runtime\coreclr.dll
corlib_dir=C:\approved-private-location\runtime
```

Set `FOOTBALL_ASSISTANT_PRIVATE_ROOT` to an absolute, private writable diagnostics directory
in the launched game's environment. No connection file, GameAssembly path, Mac profile,
native observer flag, UI control request or network credentials are needed for this probe.
The bounded background logger writes `logs/windows-scheduler-probe.log`; orderly disposal
requests completion but does not block process shutdown for disk flushing.

Optional `FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND` is a decimal handle explicitly selected for
the current process/session. Without it, `Process.MainWindowHandle` is logged as an
**unverified candidate**, `explicit_hwnd=False`, `owner_match=False`, even if PID/TID coincide.
Do not reuse another launch's handle. The environment is fixed at process creation; this
first candidate intentionally has no live control channel to select a newly created HWND.
When the candidate is zero, an EnumWindows diagnostic bounded to 512 visited / 32 owned windows records only this process's
window count, first owned HWND/TID, completion status and Win32 error. It reads no window
titles/text and never promotes an enumerated candidate into an authorized window.
Candidate logs are enough to assess whether a future controlled selection mechanism is useful.

## Evidence required from an authorized FM probe launch

Record executable/GameAssembly/bridge/loader/runtime hashes and actual process ID separately.
Collect the entry native TID, timer ticks, callback native TID, candidate HWND and owner PID/TID
from a fresh main menu. Establish independently that the HWND belongs to the actual game,
not a console/splash/helper. No callback means scheduler unproven, not success. A mismatch,
missing HWND, ambiguous game window or interrupted launch means no UI-read authorization.
All ticks always report `native_reads=disabled`, including owner-match ticks.

A subsequent one-small-UI-read stage requires another reviewed code change and evidence-based
main-menu checkpoint, verified Windows exports/types/getters, budgets and error handling.
There is no Mac field-offset fallback or automatic promotion in this candidate.

## Tests and lifecycle

Run `dotnet run --project modules/game-bridge/tests/WindowsProbeTests.csproj`.
Pure logic tests exercise identity rejection, changing windows, unknown timer IDs, reentry,
identity/log exceptions, same-thread stop, worker-thread stop, and queued late callbacks.
On Windows it additionally creates an owned built-in STATIC test window, pumps only the
harness's own message queue, checks real timer affinity/worker rejection, destroys the window
and verifies the guard rechecks it, then stops from a worker. No FM or loader is involved.

`dotnet build modules/game-bridge/FootballAssistant.DirectBridge.csproj --configuration Release`
checks the standalone CoreCLR entry. Independent GitHub workflow runs both on Linux/Windows.
Tests are evidence only when their actual run succeeds, not merely because this source exists.

Stop gates future work immediately. An off-thread stop leaves timer destruction to the next
owner callback; if the owner never pumps again the harmless timer lives until process exit.
All reverse P/Invoke delegates are rooted for process lifetime because KillTimer does not
remove queued messages. No hot unloading is supported. Diagnostic callback exceptions never
cross the unmanaged boundary. This does not protect a process from arbitrary native access
violations; the probe deliberately never calls game APIs in the first place.
