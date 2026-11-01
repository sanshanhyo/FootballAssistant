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

Normal Steam startup need not inherit a shell's environment. Place only this fixed UTF-8 (without BOM) file
beside the self-owned `FootballAssistant.GameBridge.dll` in the approved private test directory:

`footballassistant.windows-probe.json`

```json
{"schema_version":1,"mode":"probe_only"}
```

The file is capped at 1024 bytes, has exactly these two distinct properties, and accepts no
path override or read mode. Logs are fixed beneath the DLL directory at
`windows-probe-private/logs/windows-scheduler-probe.log`. No file is searched in the current
working directory, original game folder, Steam configuration or registry. Missing/invalid
configuration fails closed before installing a timer. The DLL/runtime/config remain in the
test directory; only separately approved Doorstop proxy and ini belong in the original game.

For compatibility, an explicit `FOOTBALL_ASSISTANT_PRIVATE_ROOT` environment value takes
precedence and must still be an absolute private writable directory. Neither mode changes
system/user environment variables or Steam launch options. Existing path ancestors, adjacent
configuration and log destination are rejected if marked symbolic-link/reparse; diagnostics
recheck the log path before each append. These are best-effort checks in a trusted,
owner-controlled test directory, not protection against an attacker racing path replacements.
Maintain private directory permissions; the implementation does not claim to configure ACLs. No connection file, GameAssembly path, Mac profile,
native observer flag, UI control request or network credentials are needed for this probe.
The bounded background logger writes `logs/windows-scheduler-probe.log`; orderly disposal
requests completion but does not block process shutdown for disk flushing.

Optional `FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND` is a decimal handle explicitly selected for
the current process/session. Without it, `Process.MainWindowHandle` is logged as an
**unverified candidate**, `explicit_hwnd=False`, `owner_match=False`, even if PID/TID coincide.
Do not reuse another launch's handle. The environment is fixed at process creation; this
first candidate intentionally has no live control channel to select a newly created HWND.
Every tick enumerates at most 512 visited / 32 owned windows, even when MainWindowHandle
is nonzero. The JSON `windows` array records only this process's HWND, owner PID/TID,
owner stability across the observation, bounded class name (128-char buffer with explicit
completeness), WS_VISIBLE style, GetClientRect success/width/height and Win32 error codes.
No title or UI text is read. WS_VISIBLE is a style, **not evidence that pixels are unobscured**.
A failed rectangle has null dimensions, never a fabricated zero size. Enumeration status
must be `complete` before anyone treats the candidate set as complete. These diagnostics
never promote a candidate to an authorized game window.

### Proposed next gate (not implemented / not enabled by this diagnostic revision)

First confirm FM's actual class from these logs; `UnityWndClass` is a hypothesis until then.
Then use a fresh complete scan to require exactly one candidate with the confirmed class,
complete class text, stable current PID, owner TID equal to installer and callback TID,
visible style, successful positive client width/height. Zero/multiple candidates, partial
scans, destroyed/rebuilt windows or a changed owner all fail closed. Re-read the selected
window identity/class/style/rectangle immediately before each authorized read. Do not ask
the user for an HWND from a previous launch or use the first enumeration result.

A one-shot read should be authorized by a short-lived private request bound to this launch's
PID/session nonce/bridge hash and an operator-observed fresh main-menu checkpoint. Consume
the request once before the native call, including on failure; no automatic retry/read loop.
A diagnostic phase should first prove only the domain/export identity. A separately reviewed
small UI sample must retain its own method/shape/budget validation. This proposal does not
change the constructor-level Windows reader prohibition in the current candidate.


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
