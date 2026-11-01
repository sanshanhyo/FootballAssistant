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
