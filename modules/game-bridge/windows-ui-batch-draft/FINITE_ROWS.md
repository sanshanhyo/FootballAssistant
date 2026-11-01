# Finite goalkeeper display diagnostic (opt-in candidate)

This is a separate experimental candidate, not the production Windows reader and
not an enabled background collector. It does not supply a player ID, player name,
verified page identity, or an atomic multi-chunk snapshot.

## Fixed scope

One explicit request authorizes exactly two chunks, in order:

1. Panel 0, the source-defined goalkeeper category, rows 0 and 1.
2. The same category, rows 2 and 3, only after chunk 1 succeeds and at least two
   monotonic seconds have elapsed since its completion.

Each chunk obtains only the category title and the two rows' label/value leaves
using a shared-prefix trie. It does not enumerate other rows, substitute another
panel, seek an alternate path, retry a failed chunk, or expand to all attributes.
The manifest is fixed in code; request JSON cannot supply native paths.

The paths originate from the macOS selector implementation. Windows has confirmed
only category title and row 0 as of this candidate's development. The next rows
are hypotheses, not prevalidated facts. The Mac label list is an observed-label
allowlist, not a promise that a particular label occupies a particular row.

## Bounds and identity

Per chunk: 2048 reserved operation units, 1000 ms soft total time, global depth 48,
96 nodes, 64 simultaneously live roots, 512 total root allocations, at most 8 text
items / 128 UTF-16 code units each / 1024 total. This plan requests five items.
Cooperative traversal stops at 1792 units or 800 ms; any incomplete target group
is rejected. Mandatory cleanup still runs and its time counts. A single native
call cannot be preempted, so the soft limit is not a responsiveness guarantee.
The finite request additionally caps the two chunks at 4096 reserved units and
2000 ms cumulative execution time. Cooldown is not native execution time.

Every native boundary retains the existing fresh window/owner/thread/module
checks. No identity/grant caching, extra native export, or relaxed GC lifetime is
introduced. Every chunk creates its own backend/root scope and releases all UI
handles before output; no native pointer or handle survives into the next chunk.
The outer immutable manifest is checked at every existing guarded boundary.

The caller asserts a stable profile and supplies a page epoch. That assertion is
not native page verification: another player's profile may have the same category
and labels. Outputs must retain `PageIdentityVerified: false`, keep each chunk's
source/nonce/timestamps separate, and must not be merged into a verified player
record. Actual UTC capture boundaries are not a promise of ongoing freshness.

Each completed chunk must have the exact five expected paths, title `守门`, two
distinct observed labels from the Mac goalkeeper allowlist, and canonical ASCII
ratings 1–20. Only U+200B is removed for comparison. There is no trimming, NFKC,
markup removal, guessed label, expected player value, or sibling fallback.
Repeated labels across chunks, unexpected labels/paths, ownership/scene failures,
expiry, replay, time/operation failure, or cleanup failure terminate the manifest.

## Cost evidence and test status

Owned fake-native fixtures assert 1305 reserved units, 67 visited nodes, 209 root
allocations, peak 21 live roots, and 1375 fresh guard invocations per two-row chunk.
An additional synthetic inherited-method lookup case exercises extra lookup
cost. These are deterministic fixture assertions, not measured game latency.

The preceding real single-row experiment used 1034 reserved units versus its
fixture's 961 and took about 526 ms. Adding that observed 73-unit difference to
the two-row fixture gives a planning estimate of 1378 units, not a guarantee.
Real method hierarchy and guard timing may differ; timeout must stop, not enlarge
the budget. Four rows cannot fit the existing text/node/cooperative limits in one
chunk, which is why this manifest uses two bounded chunks.

Use a fresh private candidate directory for this manifest. A stale prior request
is rejected terminally, not overwritten or retried; preparation does not delete
evidence.

No enabling config or request is shipped. Runtime use requires the explicit
private preparation/request workflow and reviewed CI artifacts. The current
cloud environment lacks .NET and PowerShell: C# and helper tests require Windows
CI before this candidate is used. No local compile/test pass is claimed here.
