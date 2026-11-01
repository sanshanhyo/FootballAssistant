# One-shot raw UI discovery — separate opt-in candidate

This distinct schema-3 diagnostic does **not** relax the anchored batch protocol.
It does not produce player facts, validated anchors, an atomic snapshot, or a
continuation cursor. `PageIdentityVerified` is always false. There is no conversion
or merge API from its result into business facts. Only the separate
`FootballAssistant.WindowsDiscoveryCandidate` project can activate this mode.
The old candidate and anchored batch remain unchanged/disabled respectively.

## Explicit approval

An immutable, default-off approval binds the current allowlisted process/session,
bridge and game hashes, confirmed window class/thread, one nonce, exact panel and
canonical focus path, creation/expiry (at most120seconds). The request carries the
schema, nonce and exact approval digest internally; the strict file request first
binds the current session/build/module fields and fixed panel0/focus0/6. The host
constructs the immutable approval/token; neither request can replace that scope.
A matching request consumes the one attempt before identity admission. Every
consumed attempt terminates, including failure. No retry, fallback, traversal of
another panel, scheduling, or continuation is provided. The host retains
the same policy for the approved session and persists terminal state; reconstructing
a new policy per request would defeat single-use enforcement and is forbidden.

A proposed real request is panel0, relative focus `0/6`. This path comes from
historical macOS body captures; it is **not** validated on Windows. Screenshot
pixels do not establish native paths. Missing/hidden ancestors or an unavailable
index fail closed. Real activation and the expanded budget require specific user
approval; code/build availability is not permission to run or retry.
No real expected name or screenshot value is embedded in the implementation.

## Hard ceilings and cooperative stop

- 2048 reserved native units,1000ms soft wall time including guard/cleanup.
- Global panel-root depth32;96 node visits, including focus ancestors.
- Enumerate first8 children only; explicit focus edges0..511 (actual count checked).
- Up to8 complete texts,128UTF16 units each,1024total; reject truncated/invalid text.
-64 simultaneous strong roots,512 total allocations; no cross-request UI handle.

Work stops cooperatively at1792units or800ms at a safe managed boundary. This
leaves margin, not a guarantee. Native calls and mandatory root cleanup are not
preemptible; one second on the main thread can visibly freeze the game. Actual
1000ms/2048-unit failures discard observations; no time is subtracted or excluded.
Node/text limits, width/depth pruning and cooperative stops may return explicitly
bounded raw diagnostics. Even `approved_prefix_exhausted` means only the approved
first-eight-child prefix; it is not proof of complete UI coverage.

## Backend and output safety

Reuse `BatchNativeBackend`, unchanged: exact fresh window/thread/module grant
checks before every reserved native boundary, and its audited invoke→gcNew
critical section. One-pass child0-first DFS retains only its current rooted
ancestor stack and transient boxed returns; no sibling prefetch. Cycles are
bounded by global depth, nodes, operations and wall time.

Every root is cleaned on every exit, then a fresh final guard and full elapsed
accounting run before releasing any observation. Ownership/cancellation/expiry,
module mismatch, native errors, malformed text, hard-budget or cleanup failures
return no observations. Cleanup uncertainty is never treated as success.

Each observation carries its exact panel-relative numeric path; result carries
request binding, panel/focus, counts and bounded status. A label and value appearing
near each other are not automatically a field pair. The page may change while
reading; per-call fresh ownership is not page identity or snapshot consistency.
Discovery can nominate candidate anchor paths for a separate reviewed approval,
not silently install them or bypass pre/post-anchor validation.

## Cost assumptions and verification

The existing synthetic export layout predicts626units for a depth21 container
and four depth22 leaves;826units for a depth31 container and four depth32 leaves,
when reached by focus0/6. These are source-derived test expectations, not measured
Windows cost or claims that Windows shares the synthetic tree. Getter inheritance,
assembly placement and class layout can increase cost. A depth32 container's
children are depth33 and must be pruned, not read.

The96-node maximum plus8texts can exceed2048units on some trees; partial or empty
diagnostics are valid outcomes. No promise is made to collect every profile field.
Run `dotnet run --project modules/game-bridge/windows-ui-batch-draft/BatchDraftTests.csproj`
on Linux and Windows CI. Local .NET SDK is unavailable; do not report these new
tests as executed until CI actually completes.

## Host and operator sequence

The separate DLL exports `Doorstop.Entrypoint.Start`. With no valid
`footballassistant.windows-discovery.json`, it creates no timer or module lease.
No enabling JSON configuration, request or private evidence is shipped in the
artifact. Existing production/probe/UI candidate entrypoints are untouched.

1. With the authorized test instance closed, explicitly invoke
   `Prepare-DiscoveryCandidate.ps1` against the independently verified executable,
   GameAssembly and private candidate directory. It records pre-launch identity;
   it does not install, launch, modify game files or issue a read request.
2. Root/operator separately arranges the reviewed candidate loader and launch.
   The configured host writes a new session and performs existing file/module/PE
   validation off-thread. No IL2CPP export is invoked by startup or polling.
3. Once that exact session is visibly on the authorized profile page and its
   module status is ready, explicitly invoke `Request-Discovery.ps1` with its
   mandatory confirmation switch. It writes one30-second request for fixed
   panel0/focus0/6, refuses an existing request, and does not launch/poll/retry.
4. The host admits only a strict schema3 request matching its immutable current
   PID/session/candidate/module/class context. It permanently consumes its
   single session slot before native admission and keeps the same policy through
   failure. File replacement or another nonce cannot start a second attempt.
5. The timer callback calls the separate lease wrapper. Initial full-window
   admission scan, export binding, type/method resolution, traversal, cleanup,
   final guard and elapsed accounting belong to the one capture. There is no
   metadata/resolve warmup stage or unbudgeted UI pre-read. Existing fresh guards
   use the original entry thread, never a replacement current-thread installer.
6. Private `windows-discovery-private/discovery-evidence.jsonl` contains raw
   diagnostics; `discovery-state.json` becomes terminal. No automatic next request
   or game restart is provided. A failure, empty result or missing focus is final.

The isolated offline test executable now also exercises the strict host parser,
old/new parser rejection and one-use session gate. CI builds the separate DLL and
parses helper syntax, then executes the request helper only against temporary
owned status files with a mocked process lookup. It never executes the preparation
helper, queries a real game process or loads a game. The
artifact allowlist excludes all generated configuration/request/private files.
