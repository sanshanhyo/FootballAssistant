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

## Two-chunk layout/eligibility diagnostic

`tactics_layout_diagnostic` explicitly selects exactly two profiles, in order:

1. `tactics_root_census`: focus panel0/0. Freshly require childCount==20 before
   obtaining any child. Inspect only those20 immediate children0..19, one scoped
   handle at a time: visibility, positive-finite bounds flag, text type, child count.
   Never obtain grandchildren, read text/names, or extend the generic DFS width8.
2. `tactics_frontier35`: fixed focus
   `0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/1` (22 edges).
   This is the previously observed but unvisited child1 of the recorded depth21
   node, not a guessed semantic root. Freshly require that parent has count2.
   Reuse bounded DFS below this one subtree, excluding the seven previously visited
   text-type leaves in its sibling branch. No other remaining frontier is enabled.

Both profiles use raw `source_kind=tactics_frontier_probe`, never normal tactics.
The finite manifest is two chunks, at least2s cooldown, maximum4096 reserved units
and2000ms summed soft capture time. Each retains the existing1000ms/2048 ceiling,
800ms/1792 cooperative cutoff, node96, globaldepth48, text8/128each/1024total,
live64/allocated512 roots. A native call is not preemptible. No six-chunk manifest,
automatic root substitution, generic cursor or cross-request handles are introduced.

Topology additionally records three integers from existing DFS read results:
`BoundsEligible`=-1 unknown,0 not positive-finite,1 positive-finite;
`TextReadCompleted`=-1 not attempted,0 getter attempt begun,1 returned;
`TextLength`=-1 unknown or the actual returned/copied UTF16 length. A nonzero length
may still be whitespace; it is not semantic acceptance. Getter attempts include
prechecks and resolution, so begun does not assert native invocation completed.
Census deliberately never calls the getter: its text read state/length stay-1,
even if type and bounds are eligible. Hidden nodes keep unknown bounds, not zero.
These fields distinguish layout-ineligible text types from blank getters without
relaxing bounds or obtaining any additional DFS native values. Existing bounds
and complete-string/UTF16 checks remain mandatory. Failed captures retain only
numeric metadata; raw strings are still discarded.

The census can establish layout eligibility, not identify which top-level slot is
semantically current. A zero-bounds slot suggests an inactive layout but does not
prove a cached scene or authorize another slot. The frontier may still yield no
eligible text. Neither outcome is promoted to page/team facts or tactical values.

## Remaining observed paths: fixed six-chunk diagnostic

`tactics_remaining_diagnostic` is one explicit finite operation, in this order:

1. `tactics_leaf_eligibility7`: common root
   `0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0` (25 edges),
   selecting only these seven relative paths:
   `0/0/0`, `0/0/1`, `0/0/2`, `1/0/0/0/0`, `1/0/0/0/1/0`,
   `1/0/0/0/2/0`, `1/0/0/0/3/0`.
2. `tactics_remaining45_1`: same common root + `1/1`.
3. `tactics_remaining46_1`: same common root + `1/0/1`.
4. `tactics_remaining46_2`: same common root + `1/0/2`.
5. `tactics_remaining56_1`: same common root + `1/0/0/0/4/1`.
6. `tactics_remaining56_2`: same common root + `1/0/0/0/4/2`.

All appended suffixes have a separating `/`. These are fixed paths from prior
numeric observations, not semantic identities or a generic continuation cursor.
The five remaining roots freshly require their parent counts: depth26=>2,
depth27=>3,depth30=>3. The own child count of the formerly partial56/1 is unknown
and is read normally; it is never treated as zero. No top-level slots17/18 or
previously exhausted35/1 branch are included.

The first chunk uses a shared fixed trie:42 nodes including25 ancestors,17 subtree
nodes,maxdepth31. It records visibility/type/bounds/getter state/returned length
and child count for the seven targets. Internal trie nodes need only existing
visibility/count reads. Zero/nonfinite bounds or a nontext target prevent the text
getter but do not abort inspection of the other selected targets. No child below
a selected target is obtained, even if its actual child count is nonzero. Missing
required path/native failure still stops the batch and discards raw text. Normal
complete-string,UTF16,visibility,bounds and fresh ownership checks are not relaxed.

Complete selected-target inspection returns raw status with reason
`approved_leaf_eligibility_complete`; it does NOT mean seven strings were read,
that the parent subtree was exhausted, or that tactical fields were identified.
A cooperative/visibility cutoff stays `bounded_raw_diagnostics`. Other five chunks
use the existing bounded DFS. Every emitted string remains source-path-associated
raw diagnostics under `source_kind=tactics_remaining_probe`, outside normal tactics.

Maximum six chunks,total12288 reserved operations/6000ms summed soft capture time,
at least2s cooldown. Each retains1000ms/2048 ceiling,800ms/1792 cooperative cutoff,
node96/globaldepth48,first8DFS children,text8/128each/1024total,live64/allocated512
roots. The selected-leaf chunk emits at most7strings. Actual fixture costs must be
verified in CI; node arithmetic is not a measured latency claim. One native call
cannot be forcibly interrupted at the soft deadline. All handles are cleaned each
chunk; no retries,automatic alternate roots,window actions or crosschunk pointers.

## Explicit seven-object ineligible-text diagnostic (one chunk)

`tactics_ineligible_text7` is a separate opt-in manifest/profile, selecting only the
same seven known paths of `tactics_leaf_eligibility7`. It adds no parent/navigation
read, top-level17/18 scope, other frontier, generic query, new export or retry.
The helper requires both `-FiniteManifestConfirmed` and the scope-specific
`-IneligibleTextDiagnosticConfirmed`; the latter is rejected for every other scope.
The exact mode remains bound in the existing immutable14-field request/grant.

The user-approved exception is only geometry eligibility for a diagnostic getter.
Every selected object must still be freshly owned, rooted and type-compatible
with TextElement; visibility, module/window/thread/grant checks, object return type,
string limits/UTF16 validation and final cleanup/ownership checks remain intact.
The normal reader and all other profiles still do not call get_text for invalid
bounds. No pointer is used outside its root lifetime, and the invoke→gcNew critical
section is unchanged.

All strings from this mode, even those with positive bounds, are placed only in
`DiagnosticTexts` as `{Path,Text,CurrentUiEligible:false}`. `Observations` stays empty.
Blank/empty returns are retained here as diagnostic results, not normalized into
facts. The separate source kind is `tactics_ineligible_probe`; no data-core/agent
adapter is enabled for it. This can identify labels retained in inactive/template
objects, but neither proves caching nor establishes current visible game data.
All safety, getter, oversized/invalid string, cleanup, accounting or final-guard
failures discard BOTH text arrays; failed outer publication also drops the entire
result while retaining only bounded numeric diagnostics.

Topology appends `RectXClass`, `RectYClass`, `WidthClass`, `HeightClass`, computed
from the same already-read worldBound four-float copy: -1 unknown,0 zero (including
negative zero),1 positive finite,2 negative finite,3 NaN,4 positive infinity,
5 negative infinity. No raw coordinates/NaN JSON values or additional Rect getter
calls are emitted. X/Y signs alone do not invalidate bounds; the original rule
requires all four components finite and width/height strictly positive.

Exactly one chunk under the original1000ms/2048 ceiling,800ms/1792 cooperative
cutoff,node96/globaldepth48/live64/allocated512 roots. Shared trie42nodes/depth31;
at most7diagnostic strings,128UTF16 units each,896total. Normal combinedtext8/1024
ceiling is also retained. Completion reason `approved_ineligible_diagnostic_complete`
means selected diagnostic work finished, not that current UI/business facts were
read. Partial work remains explicitly bounded. CI must verify actual fixture cost;
no timing or exactdeadline guarantee follows from node arithmetic.

## Fixed active-container inventory (normal eligibility only)

`tactics_active_inventory` runs exactly two fresh chunks: panel0 relative `0/17`,
then `0/18`. These roots come from an observed immediate-child census with
positive finite bounds and one child; they are not semantic tactical selectors.
Each chunk requires fresh childCount20 on `0` before selecting its fixed slot,
and childCount1 on that selected container before traversing its descendants.
A mismatch fails the manifest; there is no fallback, sibling search or retry.

Use `-Scope tactics_active_inventory -StableProfileAsserted -FiniteManifestConfirmed`.
Do not pass `-IneligibleTextDiagnosticConfirmed`: the seven-object exception is
not active here. Normal visibility, TextElement type and positive finite bounds
are required before any text getter. DiagnosticTexts remains empty. Existing
14-field numeric topology records bounds classifications and getter outcomes;
normal observations remain raw, unverified UI text, never tactical facts merely
because a subtree contains words. Empty/bounded is not proof the page is empty.

Each chunk retains1000ms/2048 units, cooperative800ms/1792,96 nodes, depth48,
first8 children per node,8 texts of128 UTF-16 units/1024 total,64 live and512
total roots. Declared total2000ms/4096 units, cooldown at least2 seconds, expiry
120 seconds. No pointers survive chunks; each re-resolves and revalidates its
root. No slots1/3, old0/4 frontier or extra panel is selected. Synthetic native
fixture costs are printed by CI, not estimates of real Windows elapsed time.
