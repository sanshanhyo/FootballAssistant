# Offline finite page-collector draft — NOT registered or approved for game use

This schema-2 prototype is separate from the one-shot candidate. Existing candidate
projects, request parsers, terminal semantics and safety checks are unchanged. No host
or timer calls this code. No screenshot value, player name, real anchor or runtime path
is hardcoded. Enabling an approval object in an offline fixture is not operator approval.

## Proposed ceilings, subject to cost review and explicit real-test approval

- 4 explicit requests per approved batch; 2-second minimum cooldown; lifetime 120 seconds.
- Per request: 2048 reserved units / 1000ms cooperative elapsed; aggregate8192 /4000ms.
- Global panel-root depth48;128 charged node visits INCLUDING repeated ancestors and anchors.
- First8 children per enumerated node; direct approved paths use canonical indices0..511.
-64 simultaneously live strong roots AND512 total allocations per request.
-8 text items,128 UTF-16 code units each,1024 total; numeric paths only.
- Numeric continuation cursor only,<=337 pending paths/16384characters. No native object,
  handle, stale grant or cached ownership identity survives a request.

These are draft ceilings, not predicted latency or production defaults. One second on
the main thread is noticeable. Native work/mandatory cleanup can overrun a soft deadline.
All cleanup elapsed is included in accounting; no overhead is subtracted. Remaining
batch allowance can shorten a request. The fake native deep21–32 cost report must pass
before any real-test proposal; a larger ceiling is not evidence of successful capture.

## Approval and page evidence

Approval is immutable and default-off: exact process/session/module hashes/window class,
panel/subtree, batch ID, page epoch and two distinct approved anchor paths+exact text hashes.
Each new request has its own nonce/sequence, short expiry, approval fingerprint and expected
cursor digest. Replays/replacements cannot redirect it. Every native read retains the fresh
full ownership/grant guard. Reentrancy is rejected; safety failures terminate the batch.

Two anchors are read through the same rooted, visible, typed/bounds-checked backend before
AND after each chunk. There are no current approved real anchor paths. Without them no
runtime collector can be enabled. Missing/hidden/mismatched anchors or incomplete final
validation discard all output and terminate. Facts are not released before final policy
accounting accepts the result. Matching UI anchors are evidence of a consistent anchor set,
NOT proof of stable player identity, active pixel visibility, or an atomic game snapshot.
No business IDs or label/value joins are inferred; no cross-chunk facts are silently merged.

## Work, continuation and stopping

The cursor stores pending relative DFS paths within the one approved subtree. Reacquire the
panel and path each request, validate all ancestor visibility/counts, and retain no runtime
pointers afterwards. Each node is re-resolved from the selected subtree root; this deliberately
simple prototype may repeat ancestor work, which is charged to the same budget. It is not a
general whole-game scanner. Depth/node/operation limits bound cyclic graphs too.

Stop collecting BEFORE exhausting the request cap, reserving768units/350ms and34node visits
for final anchor validation. This reserve is only an early-stop heuristic, never permission
to exceed actual caps: if final checks cannot finish, discard and terminate.8 texts or work
reserve produces a resumable numeric cursor only when final anchor validation succeeds.
No automatic next request is issued. Completed/exhausted/cancelled/security-failed batches
cannot restart themselves. The next explicit request must match the previous accepted cursor.

Root scopes free boxed values/strings after copying and release unneeded parents only after
the child is rooted. Keep invoke→gcNew free of allocation/guard/instrumentation. Cleanup runs
even after cancellation/deadline/ownership loss. Live64 and cumulative512 are distinct bounds;
this deliberately differs from the old cumulative64-root one-shot contract.

## Offline acceptance

Policy tests cover default-off, exact allowlist, mutation/replay, cooldown, expiry, cumulative
accounting, fresh ownership failure, concurrent requests and immutable cursor binding.
Backend tests cover token lifetime, temporary roots, caps and failure cleanup. Collector
fixtures cover deep21–32 paths, grouped synthetic texts, changed anchors, same-session chunks,
globaldepth, cyclic graphs, partial/stale output rejection and exact cost reporting.
No game data is used. Local SDK availability and executed/unrun status must be reported.

Completion means the approved bounded prefix cursor is exhausted, never the whole page.
ChunkTraversalBounded applies to that chunk only; prior chunks may also have omitted
depth/width-limited descendants. No final whole-subtree completeness assertion is emitted.
Known relative-path node cost plus34 reserved anchor visits is checked before work starts.

The output carries exact batch/page epoch/request/session/module/subtree provenance and
start/end times; PageIdentityVerified is alwaysfalse. Any eventual consumer must invalidate
the whole batch on terminal failure/page-epoch replacement and must not merge arbitrary
chunks into an atomic player record. No such publishing/aggregation service is enabled here.

## Source-derived exact fixture cost assertions (NOT executed yet)
The fake layout has two14-edge anchors and a selected container at globaldepth21 or32,
with four synthetic field leaves. Request setup resolves metadata again (27 units).
Depth21: one chunk1820units/293totalroots/90node visits/peak3live.
Depth32: three chunks1871,1904,1855units (total5630); totalroots305,310,303; nodes95,96,94;
peak3live each. Identity callbacks additionally include each reservation, each chargednode,
initial/final checks and admission. Exact assertions deliberately fail if accounting drifts.
Elapsed is injected0 for deterministic accounting; this establishes no real latency.
The2048 ceiling leaves144units above the most expensive syntheticchunk1904, not a promise
that all Windows class layouts or cold methods fit. CI execution is required to validate
these source-derived counts before proposing any runtime deployment.

The collector requires complete valid UTF-16 text of at most128 code units for fields too;
oversized text fails closed rather than silently projecting a truncated label/value.
An outer finalization guard terminates/accounts a consumed attempt even if final clock,
source construction, snapshot allocation or cursor hashing throws. No output is released
from such an attempt. CI runs the isolated fixture executable only, not a game host.
