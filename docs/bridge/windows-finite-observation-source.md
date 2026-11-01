# Windows finite UI → local observations (opt-in)

This adapter reads **only an already authorized finite producer's private files**.
It never starts a game, submits a manifest, installs a bridge, or schedules game
captures. Ordinary Windows reader support and the pinned macOS adapter are unchanged.
Manual discovery import remains a separate diagnostic route, not live evidence.

## Server-owned registration

Before backend launch, the authorized prepare/launch operator supplies:

- `FOOTBALL_ASSISTANT_PRIVATE_ROOT`: exact approved finite producer directory on a
  fixed local Windows volume. No renderer path, URL, directory search or fallback.
- `FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION`: JSON object with exactly
  `pid`, `entry_tid`, `session_id`, `bridge_sha256`, `game_sha256`, `batch_id`,
  `page_epoch`, `manifest_name`, `window_class`, `first_nonce`, `second_nonce`,
  `expires_at`. Obtain these from the independently authorized preparation record
  and approved finite request, **not by accepting an event's claimed identity**.

Only `manifest_name=profile_rows0_3` or `profile_all_rows`, `window_class=UnityWndClass` and the pinned
Windows GameAssembly hash are accepted. All UUIDs must be canonical. Expiry is UTC.
The registration is invalid after process/session/module rollover; rebinding needs
new authorized configuration. Existing local backend authentication is unchanged.
There is no HTTP registration endpoint and this adapter ID cannot be HTTP-ingested.
This code does not itself register any real directory or request.

The Windows transport opens fixed filenames through held no-reparse directory
handles, checks current-user ownership and private write ACLs, rejects hardlinks,
bounds control files to 8 KiB and evidence to 256 KiB/64 records, and rejects duplicate
JSON keys/nonfinite numbers/unterminated lines. Production has no POSIX fallback.
A pinned process/thread handle and a matching visible window reject process, thread,
and window loss. Files/ACLs remain controlled by the registered local user and trusted
system/administrators; this is not protection against that user replacing their own
producer or a compromised administrator.

## Evidence and consumers

The file watcher reads at most twice per second and ends at manifest expiry.
It never renews capture timestamps from file presence or mtime. Actual capture UTC,
source/session/hash/thread/manifest/derived nonce/index/layout and same-row label/value
associations are checked. Replay, tampering, failure/cancellation, module loss or
window/process loss disconnect the stream. Valid file/process/window checks refresh
transport liveness only; ObservationStore capture freshness still expires after 10s.
Partial trailing JSONL writes and control changes defer ingestion without refreshing
anything; the next bounded poll must see consistent complete records.

The selected ObservationStore snapshot keeps only the latest chunk's raw text facts,
so generic monitoring never stamps an earlier row with a later capture time. Bounded
per-chunk diagnostics retain the independently validated capture metadata for the
registered batch. The current-page preview and explicit agent evidence prepare a
**non-atomic finite capture summary**, up to 18 chunks/35 rows across three categories.
Every row preserves its original capture start/end, chunk index and freshness. Rows
older than 10 seconds are labelled `stale`, not discarded or called current. Summary
retention ends at approved manifest expiry; source/process/window loss clears it.
No batches, sessions, pages or player identities are merged. Page epoch is an operator
assertion, not independently verified page identity.

The existing `/v1/reader/current-page-attributes` and Companion reader client expose
progress (`chunks_received/expected`, `rows_received/expected`, `complete`) and all
captured display pairs. Windows summary metadata is `capture_summary`, never `current`.
The Mac preview's 15-second rule is unchanged. No new settings diagnostics are added.

The existing explicit UI advice route accepts `player_info` through a separate
Windows validation gate. The existing AI service receives paired display evidence,
not a hardcoded answer, and rechecks freshness/session/content after generation.
It cannot provide individual-player advice or fabricate schedule/tactics data.
Ordinary companionship chat retains its existing no-game-context policy. No model
requests are made by polling, previews or offline tests.

## Verification boundary

Synthetic tests exercise binding, actual UTC checks, replay/tamper/cancel, all 18
chunks/35 rows including the singleton goalkeeper row, per-row stale summary retention,
expiry, HTTP spoof refusal and a stubbed AI refresh fence. Windows kernel/ACL/window tests require Windows and are skipped on
Linux. Passing these tests does not establish real game reads or desktop acceptance.
