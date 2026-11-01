# Fixed tactics, next-match and schedule page captures

These opt-in scopes reuse the existing finite candidate, fresh guards, scoped
roots and source/lifecycle envelope. They do not navigate the game or combine
separate pages. Open the intended page first, confirm it once, then submit one
explicit fixed manifest with `-StableProfileAsserted -FiniteManifestConfirmed`.
No per-row command is required. Unknown layout or missing targets stop; no retry,
search, alternate page, extra row or automatic new manifest follows.

| Scope | Page to open | Chunks | Texts/chunk | Global depth | Synthetic reserved units/chunk |
|---|---|---:|---:|---:|---:|
| `tactics_current` | Existing configured tactical page | 1 | 4 | 44 | 1241 |
| `next_match_card` | Viewed club overview with next-match card | 1 | 3 | 36 | 817 |
| `schedule_rows0_9` | Chinese schedule view | 10 | 5 | 48 | 1341 |

Per chunk remains1000ms soft /2048 units, nodes96, texts8, live roots64,
allocations512,128 UTF-16 code units per text and1024 total. Traversal work stop
remains800ms/1792 units. At least2 seconds cooldown separates schedule chunks;
its declared aggregate cap is10000ms/20480 units, expiry120 seconds. One-shot
scopes declare1000ms/2048 units. No limit was raised for these profiles.

Tactics' focus root is35 edges deep: only its exact pinned profile+panel0+root
gets that admission exception. The generic focus parser remains limited to32
edges; global traversal depth remains48. Schedule's opponent leaf reaches48.
Two schedule rows would require98 nodes and9 texts, so that plan is not exposed.

## Source and semantics

Paths and display grammars are pinned to existing Mac production modules:
`tactics_projection.py`, `next_match_projection.py`, `schedule_projection.py`,
and the restricted formatting parser in `display_profile.py`. Historical Mac
records corroborate actual tactical three-field reads, a three-text next-match
card, and10 schedule rows with40 field paths. This is source/history evidence,
not proof that a Windows page has the same layout; Windows must verify each set.

- Tactics: four leaves are selected title, independent style, independent
  mentality, and `队形`. Formation is obtained only if title/mentality/style
  agree and the formation digits sum to10. The observed `偏向防守` title versus
  `防守` mentality alias is preserved. Lineup, roles and instructions stay unknown.
- Next-match: date title must match `下一场比赛（yyyy-M-d）` and a valid calendar
  date; opponent and competition use only the observed optional fixed rich-text
  wrapper. No club/team/player ID, home/away, kickoff or current game date follows.
- Schedule: each chunk includes exact `赛程安排` title plus one row's date,
  opponent, home/away (`主`/`客`) and competition. Display formatting accepts only
  the existing bounded link/style/color grammar. Dates retain two-digit years;
  the century, ISO date and kickoff stay unknown. Never infer current game date
  from a future match or fill absent rows from another capture.

Raw field length stays128, which may reject unusually long rich-text strings;
that is a bounded failure, not permission to truncate or increase the budget.
No expected team names, match values or tactical settings are hardcoded.

## Event contract

`source_kind` is `attributes`, `tactics`, `next_match`, or `schedule`.
Attribute events retain their category key; other kinds have `category_key=null`.
Non-row one-shot profiles have `row_start=-1,row_count=0`; schedule chunks have
row_start0..9,row_count1 and selection_profile `schedule_row0`..`schedule_row9`.
All use the existing schema4 immutable manifest, source bindings, derived nonce,
real capture UTC interval, strict completion acknowledgment and failure lifecycle.
`PageIdentityVerified=false`, unknown business identity and non-atomic batch
semantics remain mandatory. Old consumers must reject unknown modes rather than
pretend the Windows adapter is the Mac reader.

Synthetic native fixtures assert exact path unions, export/guard/root costs,
cleanup and fail-closed behavior. C#/PowerShell tests need CI; no local SDK is
available. All captured example values in tests are invented.

## Numeric focus divergence diagnostic

The finite event's top-level `focus_diagnostic` survives rejection even when `result`
is intentionally null. It is copied through `DiscoveryPublication`, the same tested
publication boundary that discards rejected raw text. An unavailable collector result
produces null diagnostics, not invented zeros. `DiscoveryResult.FocusDiagnostic` and
the top-level diagnostic contain exactly five integers from existing reads;
it does not scan siblings, obtain names/types/text, or change admission, guards or budgets.
`ResolvedDepth` is the number of successfully obtained focus edges (0 = panel root,
-1 = panel root not yet obtained). Its deepest prefix is the first `ResolvedDepth`
edges of the already approved `FocusPath`; this is topology, not semantic page identity.
`AttemptedEdge` is zero-based and `RequestedChildIndex` is the fixed selector's edge.
`ObservedChildCount` is -1 until that edge's count read completes, including hidden
ancestor failures; 0 is an actually observed empty container, never an unknown value.
`Stage`: 0 before panel attempt, 1 panel attempt, 2 ancestor charge/visibility,
3 count attempt or out-of-range rejection, 4 child acquisition, 5 entire focus resolved.
A stage describes an attempt, not proof that a native call completed; existing `Reason`
and failure status remain authoritative. After focus resolution the pending edge,
index and count are reset to -1. Diagnostics survive terminal failure, but raw text
observations still discard on failure and final ownership/cleanup checks are unchanged.

Alignment procedure: compare the exact failing prefix against the corrected Mac selector
and its recorded child topology before proposing a changed Windows selector. A missing
edge proves that selector does not fit this observed tree, not that a neighbouring edge
has equivalent meaning. If source evidence cannot determine the replacement, obtain an
explicitly bounded structural inspection plan for the divergent parent; do not iterate
full guessed paths, scan arbitrary text, widen the generic focus parser, or silently
fall back to another panel. No alignment native calls are enabled by this diagnostic.

## Isolated Windows tactics alignment candidate

`tactics_alignment_candidate` is a one-chunk diagnostic manifest, not a replacement
for `tactics_current` and not a normal tactics data source (`source_kind` is
`tactics_alignment`). Its fixed panel0 parent is
`0/4/0/0/0/0/0/0/0/0/0/0/0/0` (14 edges). A prior Windows diagnostic found
exactly one child there whereas the corrected Mac selector requested child1.
This justifies investigating the sole child, **not** asserting equivalent semantics.
The candidate rechecks count==1, obtains only child0, then follows the original
remaining Mac suffix and four leaf suffixes. Count0 or count2+ immediately stops;
there is no sibling scan, fallback, alternate panel or automatic retry.

The manifest still requires explicit finite-manifest confirmation and immutable
nonce/session/window/module/expiry binding. It has one chunk under the unchanged
1000ms soft/2048 reserved-operation ceiling, 800ms/1792 cooperative stop,
depth48/node96/text8/live64/total512 limits. Generic focus parsing stays depth32;
only this exact fixed35-edge candidate is separately admitted. Existing profiles
and their selectors remain unchanged.

Candidate-only `focus_edges` contains at most35 value-type entries from already
required focus reads: Depth(zero-based source depth), RequestedChildIndex,
ObservedChildCount(-1 unknown), Stage(2 visibility attempt,3 count attempt or
rejection,4 child attempt,5 child obtained). Slots are preallocated before native
calls. The snapshot is taken before elapsed accounting; there is no code inserted
inside runtimeInvoke→gcNew. The top-level array survives a rejected/null result,
without leaking raw failed text; other profiles emit null. Scalar focus diagnostics
remain available as before. Target collection still uses only the four fixed leaves.

Successful four-leaf grammar/title/style/mentality consistency is necessary but
not proof of page/team identity or business facts. Output stays raw, identityfalse,
non-atomic, and outside the normal tactics adapter. Actual Windows paths and texts
must be reviewed against the visible page before a subsequent explicit fixed
Windows selector can be accepted. Synthetic fixtures are not real page evidence.

## Fixed three-sibling raw inventory

The alignment attempt reached an actual empty container at global depth16. It did
not locate tactical fields. The observed ancestry had exactly three earlier forks,
at depths12,7,4, each with two children; all chosen edges were child0. The explicit
`tactics_sibling_inventory` manifest therefore samples only the three previously
unread child1 subtrees, nearest first:

1. `tactics_sibling12`: `0/4/0/0/0/0/0/0/0/0/0/0/1`
2. `tactics_sibling7`: `0/4/0/0/0/0/0/1`
3. `tactics_sibling4`: `0/4/0/0/1`

These are disjoint numeric scopes, not claims about their semantic roles. Each
request reacquires the panel/focus and requires its corresponding parent still
has exactly two children before obtaining child1. A mismatch is a safety stop,
not a request to skip to another scope. No other top-level panel0/0 children are
selected, no pointers/cursors survive chunks, and no alternate focus is accepted.

One explicit invocation schedules exactly three chunks with at least2s cooldown;
maximum total6144 reserved operations and3000ms summed soft capture time. Each
chunk retains1000ms/2048 hard-accounting ceilings,800ms/1792 cooperative stop,
globaldepth48/node96 (including ancestors), first8children per node,8complete
texts of128UTF16 units each/1024total, live64/allocated512 roots. A single native
call is not preempted and wall-clock pause is not guaranteed below1s. Traversal
is the existing child0-first DFS, not a new unbounded search or speculative
breadth-first native-handle prefetch. The three disjoint branches are scheduled
fairly as separate chunks, avoiding repeated restarts or a giant one-frame scan.

`source_kind=tactics_sibling_probe` is raw diagnostic only, not a tactics adapter.
Texts are sparse possible anchors; none are automatically associated as fields,
team identity, game date or page identity. Empty output is not evidence that the
page has no tactical data. A bounded chunk may complete the finite manifest step
without exhausting its subtree; the terminal manifest means all three attempts
finished, not that the page was completely read.

Candidate-only top-level `topology` (also in an accepted result) contains at most96
numeric records from existing reads: ParentRecordIndex(-1 for selected root),
ChildEdge(-1 at selected root), GlobalDepth, Visible, TextElement, ChildCount,
and Stage. Unknown values are -1. Stages mark completed work:1 entered,
2 visibility completed,3 type completed,4 child count completed. The graph contains
only visited nodes, not fabricated nodes for unvisited siblings. Parent references
plus approved focus reconstruct numeric paths without names, pointers or extra
native calls. Visibility pruning, width/depth/text/node/cooperative limits set
TraversalBounded; partial records explicitly retain unknown counts. Failure also
preserves numeric topology/focus diagnostics but discards all raw text. No standalone
"complete" flag promotes a partial or hidden subtree to full page coverage.
