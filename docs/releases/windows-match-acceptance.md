# Windows match-reader technical acceptance reference

The checklist below is retained technical reference, not a request for further
user testing. Following the user's latest instruction, this delivery does not
add onsite validation or use this checklist to block packaging. Prior automated
results remain recorded; unverified live-game behavior must not be presented as
verified. CI build success is not live-game acceptance.

Transport: plugin `io.footballassistant.matchreader` version `0.1.0`, snapshot
`fa-match-snapshot/0.1`. Deployment creates `<userData>/match-reader/active`.
BepInEx `[Output] SnapshotPath` and backend `FOOTBALL_ASSISTANT_MATCH_FILE` must
both be the absolute path `<userData>/match-reader/active/match.json`.
The plugin uses configured `Output.SnapshotPath` first. Only an empty setting
falls back to ambient `FOOTBALL_ASSISTANT_MATCH_FILE`; a conflicting environment
value is ignored with a warning. An invalid nonempty configured path disables
reading rather than silently using another location. `Config.SaveOnConfigSet`
is disabled before binding: the plugin must not rewrite the installer's config
bytes or invalidate the rollback ownership receipt.
`status.json` is derived from its directory, never a separately supplied URL.
No game data or saved-game identity is inferred from the process session.

Plugin status distinguishes `loading`, `hook_installed`, `hook_timeout` (120 s),
and `stopped`. `hook_installed` only proves the hook installation code returned;
it does not prove match observations. Status heartbeat does not refresh tick
`captured_at`. A pause without new ticks becomes unavailable after 15 seconds.
Restarting the game changes process-start identity; reloading the plugin changes
instance identity. Old process files, mismatched sidecars, ended/stopped matches,
unknown producer versions and unsupported game hashes fail closed.

Authenticated `GET /v1/reader/match` remains the only backend endpoint.
`readerStatus` contains only a current, fresh process-bound status (or null).
`producerVerified=true` means protocol/process checks passed, NOT authenticated
native provenance, accurate game facts, final result, player-team identity, or
release acceptance. Same-user tampering with files is not prevented by this
transport. The supplied binary hash is checked against the fixed supported
build; the backend does not re-read game memory or independently inspect modules.

## Retained local checklist (not scheduled for this delivery)

1. Exit the game. Use the installer backup/consent flow. Check the two absolute
   output paths agree; no token or provider secret belongs in plugin config.
2. Launch the game normally. Status should become `hook_installed`, with a new
   process/instance identity. Loading alone is not a reading success.
3. Enter a real match. Ask the desktop “当前比分”. Compare the two team names and
   current score against the visible game. Repeat after a visible update.
4. Exit the match or game: no old score should remain presented as current.
   Restart and check an old snapshot cannot populate a new session.
5. Roll back deployment, restart, confirm no reader hook/status is claimed active.

Optional PowerShell **local-only** health summary (replace the app profile path):

```powershell
$root = 'C:\path\to\userData\match-reader\active'
$s = Get-Content -LiteralPath (Join-Path $root 'status.json') -Raw | ConvertFrom-Json
$m = Get-Content -LiteralPath (Join-Path $root 'match.json') -Raw | ConvertFrom-Json
[pscustomobject]@{
  Protocol = $s.producer.protocol
  Version = $s.producer.version
  LoadState = $s.state
  MatchState = $s.matchState
  ProcessId = $s.process.pid
  SameInstance = ($s.instanceId -eq $m.instanceId)
  SameProcessSession = ($s.process.sessionId -eq $m.process.sessionId)
  HeartbeatAgeSeconds = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($s.observedAt)).TotalSeconds
  HasTickTimestamp = [bool]$m.captured_at
}
```

This prints no names, player attributes, raw samples, full process paths or
credentials; it is a diagnostic summary, not the backend's liveness validation.
Share only version, state, age, pass/fail of displayed-score comparison and
restart/rollback results. Do not upload full JSON, logs, game DLLs or saves.
