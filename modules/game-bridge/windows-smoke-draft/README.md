# Windows one-shot smoke DRAFT — not production source, not enabled

This folder is deliberately outside ordinary `src/*.cs`. Its independent experimental
`FootballAssistant.WindowsMetadataCandidate.csproj` builds a DIFFERENT DLL/entrypoint.
The ordinary approved probe and NativeUiReader Windows prohibition are unchanged.
Only the separately selected experimental DLL can service explicit metadata requests.
No enabling config/request is included in CI artifacts; no automatic deployment occurs.

## Implemented here: policy plus UNEXECUTED metadata candidate

- A session context must contain the **actually verified** window class; empty class fails.
- Fresh complete bounded enumeration must yield exactly one qualifying window: stable
  current PID, exact known class, visible style, successful positive client rectangle,
  owner TID equal to the entry/callback TID. Unknown class/owner rows fail the full scan.
- A request binds nonce, PID, session, bridge hash, GameAssembly hash, class and stage.
  Its validity is at most 30 seconds; future/stale/expired requests fail.
- Metadata attempt first; only a recorded successful metadata operation permits a separate
  explicit UI request. Each stage is attempted at most once per policy/session, including
  failures. There is no retry loop. A second fresh scan is required immediately before a
  call; grants are consumed before that validation and cannot be reused.
- CandidateConfiguration additionally parses fixed-name, 4096-byte bounded JSON with exact
  fields/duplicate rejection. The independent host creates a fresh session before processing
  requests, never calls IL2CPP at startup and explicitly rejects UI-stage requests.

Run isolated fixture tests (no Windows/FM/native calls):
`dotnet run --project modules/game-bridge/windows-smoke-draft/DraftTests.csproj`

## Required before any runtime wiring

1. Obtain real class/unique visible client-area evidence on the actual authorized Steam
   process. Window-owner evidence is not a proof of a safe Unity frame phase. Confirm the current session
   stable page via existing operator evidence, not by calling new UI getters as a gate.
2. Start creates a cryptographically random session nonce; persist a small private session
   description with PID, bridge hash, module identity and observed class. No old process's
   HWND is supplied in environment variables. An authorized operator creates a short-lived
   fixed-name bounded request referencing that exact session/checkpoint. Strict schema,
   duplicate-key rejection, private-path/reparse checks and no reusable read-enable flag.
3. Resolve **only an already-loaded** GameAssembly from this current process, requiring
   unique module and exact approved canonical path. Acquire a module reference via
   GetModuleHandleEx (not LoadLibrary/NativeLibrary.Load), then verify module base/path,
   approved file hash and file identity against launch evidence. Hold the same file open
   without write/delete sharing during verification and calls. Disk hash alone must not be
   described as loaded-image identity proof; fail if identity/link/replacement cannot be
   reconciled. Resolve exports on that held module; bound addresses to executable regions
   of its actual PE mapping. Verify x64 ABI signatures from supported headers/build evidence.
4. First permitted native operation is tiny metadata: nonzero `il2cpp_domain_get`, bounded
   assembly count and expected assembly/image identities; no broad metadata dump. All calls
   occur on the freshly validated callback thread. Do not attach an arbitrary worker thread
   and label it the Unity main thread. A failure consumes the metadata request and bars UI.
5. Second separately authorized operation uses a dedicated `WindowsSmokeReader` factory
   that accepts only this session's verified module lease and single-use grant. Do not
   remove the ordinary NativeUiReader Windows guard. Validate method/type/getter shape
   before invoking; no hard-coded Mac field offsets. One visible text scalar only, bounded
   traversal (e.g. 64 nodes / depth 8), string length 128 code units, managed exception
   boundary and explicit elapsed-time budget. Time budgets checked between native calls
   cannot interrupt a stuck getter; acknowledge that limitation. No observer, packet,
   registry, network publisher or continuous capture in this stage.
6. Persist private evidence of the single returned field with PID/session/module/bridge
   identity, actual HWND/thread and time. Empty/exception/unknown is not fabricated content
   and not automatically retried. Use UI text only; do not call it a complete FM API.

Open conditions: UnityWndClass has been observed in the original Steam build, but each new
session still needs its own stable-window/checkpoint evidence. The native module lease
candidate is untested and no UI getter path has been implemented/approved. Consequently no game data
has been read by this draft and there is nothing here to activate through configuration.

## Current-process module lease / metadata candidate (not run)

`WindowsLoadedModuleLease.Acquire` only references an existing unique GameAssembly mapping
with GetModuleHandleEx(FROM_ADDRESS), balanced by FreeLibrary; it never loads another module.
It requires trusted **pre-launch** volume/file-index identity, canonical absolute path,
SHA256 plus the approved current fm.exe path/SHA256. Only the two actually invoked metadata exports are required. It holds a no-write/no-delete-share file
handle, compares loaded module path and PE image size, rejects non-x64 PE32+, and checks each
resolved export lies in a readable/executable/nonwritable PE section and committed executable-
read MEM_IMAGE memory allocated to that module. Forwarded/out-of-module exports fail.

This is not an in-memory code hash or anti-tamper scanner. Correct trust chronology of the
pre-launch file identity remains necessary: do not fill the approval from the current file
and claim it proves which file the process loaded earlier. Missing/uncertain chronology is
a stop condition. Alternate path aliases, reparse points, writable code pages or unexpected
exports conservatively fail rather than being normalized away. Hash/file/PE validation may
be expensive and must be prepared outside the timing-sensitive callback before an explicit
short-lived request, while preserving the held lease. No IL2CPP call occurs during acquire.

Only `RunMetadata` can bind/invoke the two native functions; its policy checks consume a
metadata grant and revalidate a fresh window identity before `il2cpp_domain_get`. Before
`il2cpp_domain_get_assemblies` it checks identity and expiry again. Result is only nonzero
domain and assembly count 1..1024; the returned array is never dereferenced. Failure consumes
the attempt and bars UI. The lease lifetime lock prevents concurrent release during calls.
The signatures match the existing reader's Cdecl/nuint declarations but still require the
approved Windows build/header ABI evidence before real invocation. No exception handler can
make an invalid native ABI safe; this candidate is not yet runtime-approved.

The wider reader source's 34/35-export discrepancy is NOT a blocker to this minimal stage:
only `il2cpp_domain_get` and `il2cpp_domain_get_assemblies` are checked/bound/invoked. This says
nothing about verification of all other exports. The native factory additionally pins the
operator-provided original Windows GameAssembly SHA256 `820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a`
and fm.exe SHA256 `2a7318c6984bcb3a19ff3304432b63462581cee33ba203f9a0a118f11c69e27e`;
another build fails closed. `UnityWndClass` has now been observed by the operator, but the
new session still needs complete unique-window and stable-page evidence before request authorization.
No default class is silently inserted by this implementation.

Tests currently exercise fake metadata delegates, single-use behavior, bad counts/hash and
identity loss between queries. They do not execute the lease or call real IL2CPP. A real
Windows own-module fixture for lease ABI/PE validation remains required. The ordinary production build excludes this folder; a separate experimental workflow compiles/tests it and publishes only a disabled candidate artifact.

Primary references:
- https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw
- https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulefilenamew
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle
- https://learn.microsoft.com/en-us/windows/win32/debug/pe-format


## Independent metadata candidate: controlled runbook

**No actual native metadata run has yet been validated. Review CI and code before deployment.**
The current known Windows build and UnityWndClass are pinned from operator evidence; do not
reuse the prior process PID/TID/HWND or treat the previous main-menu confirmation as a new
session's confirmation.

1. Obtain the Windows-only `WindowsMetadata-EXPERIMENTAL-NOT-INSTALLED` artifact after its
   exact commit passes both OS fixture tests and build. It contains the separate DLL, source,
   hashes and scripts, but NO enabling JSON. Original production/probe payload is unchanged.
2. After the user normally exits FM, run `Prepare-MetadataCandidate.ps1` with explicit
   `-ExecutablePath`, `-GameAssemblyPath`, `-CandidateDirectory` in the approved private test
   location. This refuses any running fm process, validates approved binary hashes, records
   volume/file-index plus timestamp, and writes only the candidate-adjacent fixed opt-in JSON.
   No executable/proxy/ini/system environment/Steam option is altered by this helper.
3. Root separately coordinates the approved Doorstop target change to the independent
   `FootballAssistant.WindowsMetadataCandidate.dll` and a normal Steam launch. The host
   rejects records dated after process start and refuses absent/invalid config. It writes
   `windows-metadata-private/session.json`, prepares/holds the existing module lease off-thread,
   then writes `module-status.json` ready; there have still been ZERO IL2CPP calls.
4. Observe `metadata-evidence.jsonl`: complete unique-window scans in this new session.
   Get a new root/user confirmation of a stable page in this session (main menu or the authorized temporary test career).
   Only then run `Request-MetadataOnce.ps1 -CandidateDirectory ... -StableCurrentSessionPageConfirmed`.
   The helper verifies live session and ready module status, writes a 30-second nonce/PID/
   session/bridge/game/class-bound metadata-only request, and does nothing else.
5. The next eligible callback consumes the request, rechecks the window, calls domain_get,
   rechecks again, calls domain_get_assemblies and emits one metadata_success with domain_present
   and assembly_count, or metadata_failed_no_retry. It never dereferences assemblies or
   enters UI traversal. `ui_enabled=false` is invariant. A stale/wrong-session request is
   ignored; failed native attempt is not retried. Read the evidence file to establish result.
6. No UI phase is wired. The pure policy contains a future UiText stage, but the host parser
   rejects it and the host project contains no UI reader. Do not claim business/player data
   was read from a successful domain/assembly-count diagnostic. A separate reviewed UI step
   remains necessary for a first visible text field.

Private JSON/path checks are best-effort for an owner-controlled test directory and do not
claim to defeat hostile concurrent path replacement. Keep that directory private. The
prelaunch helper holds files against write/delete while recording, but does not retain the
lock until launch; the approved hashes/FileID are rechecked by the host. Maintain the trusted
launch provenance chain. Session is single-instance; never reconstruct policy on each tick.
Stop gates callbacks immediately. For process-shutdown safety, held module/file leases may
remain until exit rather than race a callback. No hot unloading is supported.
