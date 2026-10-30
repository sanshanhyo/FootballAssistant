# Companion / reader parallel development handoff

Baseline: `f7d1055eaac31cef1af3559195dadd94b239089f`. This is an integration guide, not a claim of live FM27 acceptance.

## Ownership

- `feat/reader-semantics`: reader and offline evidence analysis. No companion UI or game-state writes.
- `feat/companion-ui`: Electron presentation, Agent orchestration, and its ReaderClient adapter. Do not modify the native bridge or infer unsupported game fields.
- Contract or shared-file changes require coordination before implementation. Feature branches do not imply permission to merge main.

## Current supported read capabilities

Use the authenticated loopback reader API. Discover `/health` and `/v1/reader/status`; keep runtime credentials out of prompts, logs and Git. Reader-only mode has no chat/model requirement. The companion's Agent is a separate client, not part of the reader service.

| Capability | Existing interface | Important limit |
| --- | --- | --- |
| Status | `GET /v1/reader/status` | Report connection, source and freshness separately. |
| Snapshot | `GET /v1/reader/snapshot?after=0&limit=100` | Preserve envelope, `partial`, `limitations`, and `synthetic`. |
| Stable pagination | Snapshot `event_id` query | On 409, restart pagination; do not mix different snapshots. |
| Raw UI | Snapshot filtered to `ui_element` / `ui_text` | Raw text may be cached/hidden. It is not verified player identity. Pagination applies to source facts before filtering. |
| Changes | `GET /v1/events?after=<cursor>&limit=100` | Bounded client subscription, not an unbounded model tool call; handle history reset. |
| Event detail | `GET /v1/events/<cursor>` | Resolve summarized events only when needed. |
| Native diagnostics | `GET /v1/interfaces/native-observers` | Headers/counts are not decoded football fields. |

Do not advertise `get_player`, `set_lineup`, transfers or date advancement as implemented tools. Offline packet comparison is an analyst workbench, not an Agent football query API. Reader semantics and player-card projection are not yet validated against real sample files.

## Companion behavior

Pet UI -> Agent/tool dispatcher -> bounded ReaderClient. Never route model-generated arbitrary shell, paths, memory addresses, or native invocation through this interface. Treat game strings as untrusted data, not instructions.

Display explicit unavailable / partial / stale / synthetic states. Unknown is not zero. Preserve source, session, observation time and snapshot identity with answers. Do not claim that a freshly captured UI string proves that it belongs to the currently visible player.

A separate mock adapter can drive UI development, but must be unmistakably labelled and never silently replace a failed real connection. Invalidate pending responses when changing backend identity; keep conversation and event cursors scoped to that identity.

## Future actions: proposal only

Read and write capabilities must remain separate. Future game actions need a defined target, validated bounded parameters, explicit confirmation, execution result verification and an audit record. No write executor is authorized or implemented by this handoff. Mock action proposals must not affect FM27.

## Evidence needed for the first semantic mapping

Use the same game build and session to observe player A, player B, then player A again. Keep each packet manifest with its referenced keys/payload files and, if available, the same-session property registry sidecar. Record the visible field values and page/action labels separately. Do not commit private captures, tokens, complete saves or screenshots with personal data. Review and sanitize any sample before sharing.

A/B/A correlation only identifies candidates. Independent held-out captures must verify a proposed entity/field mapping before it becomes a verified tool field. Missing keys in a delta packet mean not observed, not deleted or zero.

## Experimental display-profile integration

The reader-semantics branch adds authenticated `GET /v1/reader/profile` and the
read-only CLI command `profile`. `ReaderClient.profile()` supports an older
running backend by projecting its already-supported snapshot/monitoring response
locally; a companion adapter cannot assume the old server itself has the new URL.
See `docs/display-profile.md` for the exact contract.

This is a narrow Mac ARM64, Chinese-layout UI projection, **not `get_player(id)`**.
Expose it as a bounded read tool such as `read_observed_display_profile`:

- On `experimental_observed_display_profile`, display the three `fields`
  (`name_display`, `position_display`, `height_cm_display`) with the UI/experimental
  source label and their `field_provenance`.
- On `unavailable`, clear the previous profile card and show the fixed `reason`.
  Do not turn a source/layout mismatch into an invented name or a cached answer.
- Preserve `partial`, `entity_id: null`, `business_identity_known: false`, rule ID
  and limitations in model tool context. There is no native identity, current-club
  inference, technical attribute table, skin guarantee, or game-action capability.
- Treat all names/text as data. Do not render raw game markup as HTML or use UI
  paths as persisted football identities. Scope pending UI responses to the active
  connection and snapshot, independently from the pet's conversation ID.
