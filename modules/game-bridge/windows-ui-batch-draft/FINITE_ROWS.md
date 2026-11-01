# Finite profile attribute display diagnostic (opt-in candidate)

Separate experimental candidate, not an enabled background collector. No player
ID/name, verified page identity, or atomic multi-chunk snapshot is produced.

## Explicit immutable manifests

`Request-FiniteRows.ps1 -Scope <name> -StableProfileAsserted -FiniteManifestConfirmed`
creates one approved manifest in a fresh private candidate directory. No enabling
configuration/request ships in the artifact. No timer native work occurs without
that request. A stale or replacement request is rejected, never retried.

| Scope | Fixed chunks | Selected rows | Aggregate reserved units / soft execution time |
|---|---:|---:|---:|
| `goalkeeper_rows0_3` (legacy default) | 2 | GK 0–3: 4 | 4096 / 2000 ms |
| `profile_rows0_3` (smaller fixed subset) | 6 | GK, mental, physical 0–3: 12 | 12288 / 6000 ms |
| `profile_all_rows` (full fixed collection; explicit approval required) | 18 | GK 0–12, mental 0–13, physical 0–7: 35 | 36864 / 18000 ms |

Legacy `-FiniteTwoChunksConfirmed` is accepted only for the legacy scope. It cannot
approve a larger manifest. Expanded requests are rejected by older candidate
parsers. No scope accepts arbitrary category names, paths, row lists, or counts.

For a full collection, one command with `-Scope profile_all_rows` starts all18
authorized internal chunks automatically. It does not require18 commands or
per-chunk confirmation. Final `completed` means every fixed target succeeded;
any failure is reported as `failed`, never a silently complete partial result.
The internal cooldowns can make the overall collection take roughly50 seconds,
not one continuous18-second main-thread pause.

Each category is visited in the table order, at most two rows per chunk; GK row12
is a singleton. Each chunk obtains only category title and selected label/value
leaves with a shared-prefix trie. It never enumerates other rows, skips a failure,
substitutes a panel/path, or retries. Actual child counts and complete targets
must validate even if a source-defined row exists in the allowlist.

Paths and label allowlists come from the Mac
`current_page_attributes_projection.py` table. Label count limits this capability;
it is NOT proof of native row counts, and whitelist ordering is not assumed to
be row ordering. Windows has verified GK rows0–3 only before this extension.
Mental/physical layouts and remaining rows remain hypotheses until measured.

## Bounds and checks

Per chunk: 2048 reserved units, 1000 ms soft time, depth48, nodes96, live roots64,
allocated roots512, text items8, UTF-16 units128/item and1024 total. A two-row plan
requests five items, a singleton three. Traversal cooperatively stops at1792 units
or800 ms; incomplete groups are discarded. Mandatory cleanup always runs and its
time counts. Native calls cannot be preempted; a one-second return is not promised.

At least two monotonic seconds elapse after each chunk finishes before the next
starts. Cooldown is not native execution time. Expiry remains120 seconds. Every
native boundary retains fresh full window/owner/thread/module checks; outer and
child admission pin the same HWND. No cached UI pointer or handle crosses chunks.
GC return-to-root critical sections are unchanged. Output queue capacity32 is a
bounded metadata queue, not an increase to native budgets.

Every completed chunk must contain exact expected paths, the actual expected
category title, distinct labels from that category's Mac allowlist, and canonical
ASCII ratings1–20. Only U+200B is removed; no trim/NFKC/markup/value repair. Duplicate
labels within a category across chunks stop the manifest. Missing/unknown/hidden
rows, changed ownership, timeout, expiry, replay, or cleanup failure stop without
skip/retry. There is no automatic next manifest.

## Source and lifecycle contract

Private output remains `windows-finite-rows-private/finite-rows-evidence.jsonl`.
Each `finite_rows_chunk_result` event contains source PID/session/thread/build
hashes, batch ID, asserted page epoch, chunk index, child nonce, manifest name,
category/row range, declared caps, genuine capture UTC start/end, and costs.
`result` is null unless collection, cleanup, final fresh guard, semantic validation
and outer budget accounting all succeed. Each result retains its own provenance.

`finite-rows-state.json` distinguishes `running`, `completed`, `cancelled`, and
`failed`, reports batch/epoch/scope, last successful/failed chunk and actual totals.
Dispose writes module status `stopped`. Completion stops the native timer; there
is no hidden continued page/window scan. A downstream live adapter must enforce
its own approved producer/session/process binding, expiry and capture-time TTL;
file rereads never refresh an observation's timestamp.

A stable-profile/page-epoch assertion is not native player identity proof. The
same category and labels can appear for another player. Keep identity unknown,
mark partial results, and do not merge chunks into a verified player or atomic
page snapshot. No hardcoded player name or observed real rating is used.

## Offline cost evidence

Owned fixtures cover all18 fixed plans with independent literal Mac topology:
- GK/mental pair:1305 units,67 nodes,209 allocations,peak21,1375 guards.
- Physical pair:1323 units,68 nodes,212 allocations,peak21,1394 guards.
- GK singleton:961 units,49 nodes,153 allocations,peak21,1013 guards.
- First six:7866 units; all eighteen:23218 units across chunks.

The real preceding GK pair measured1378 units and about674–695 ms. Carrying its
73-unit overhead forward is only a planning estimate; new categories may differ.
Neither fixture zero-time nor aggregate estimates promise actual responsiveness.
C#/PowerShell tests must run in CI; this cloud workspace has no SDK or PowerShell.

### Windows status-reader protocol

Status replacement preserves complete snapshots for opened handles; it does not
promise uninterrupted pathname availability. Windows CI observed a transient
`FileNotFoundException` when another thread opened the destination during
`File.Replace`. A trusted consumer may defer that specific transient absence
within a bounded running-producer window, without producing an observation or
advancing capture freshness. Permission, malformed JSON, identity/ACL change, or
writer failure is not that condition. Permanent absence, expiration or loss of
the producer must invalidate the source; never defer indefinitely. The owned
fixture bounds active-writer deferral to4096 attempts/10 seconds, propagates the
writer task result, then unconditionally requires the complete final sequence32
and no leaked temporary files. The production adapter must use its own approved
producer/lifecycle and time bounds rather than copying a test's task predicate.
