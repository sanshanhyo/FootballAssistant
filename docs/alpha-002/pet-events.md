# Alpha 0.0.2 result reactions — adapter boundary, not live reader integration

Status: independently testable gate, persisted journal, agent delivery adapter and motion interface. **Real win/loss/draw triggering is not connected.** Existing experimental `match-reader.cjs` provides scores but does not establish trusted final status, stable save identity or player-controlled team identity. No additional memory investigation is authorized or included.

## Required reader evidence

A trusted future adapter must supply `verified: true`, stable string `saveId`, `matchId`, `playerTeamId`, `homeTeamId`, `awayTeamId`, `phase: live|final`, nonnegative integer `homeScore`, `awayScore`, numeric UTC milliseconds `observedAt`, and for final results `finishedAt`. These are internal adapter inputs, not a new game-reader or character package schema. `verified` is a caller's evidence assertion, not authentication. Do not map raw period, score change, UI text, connectivity, or the experimental native transport to it. Unknown/missing/stale data yields no result. Penalty shootouts/aggregate results require a separately agreed authoritative result representation; this version interprets only the supplied match score and must not be fed ambiguous knockout results.

## Wiring contract

- Construct `FileResultJournal` using a dedicated application-data file (not runtime/chat history), then `ResultEventGate({journal})`. Journal writes precede effects; failures fail closed. Dedup key is save + match + result. History is never evicted silently; 10,000 entries requires explicit archive policy. Single application process; shared state-file CAS protects against stale concurrent writes.
- Construct `PetReactions({gate, suggest, deliver, motion})`. `suggest(event, {signal})` delegates to the **existing agent** with only event facts plus its normal verified context. Do not create a second model provider or hard-code tactical/causal claims. `deliver({event,suggestion},{signal})` must validate the signal and active character/session immediately before committing a bubble or speech side effect.
- Call `configure({enabled, muted, proactivity, characterId, sessionGeneration})` on connection/session/character changes and preference changes. `enabled` is opt-in; proactivity is a number in 0–100 (zero disables). No probabilistic frequency rule is invented. Configure aborts pending work and resets the observation baseline; no old result is replayed after mute is lifted.
- Call `observe(normalizedObservation)` for fresh observations only. A final result must follow an observed live state for the same save, match and player/team identities. First connection to a completed match is consumed silently. Suppressed/cooldown outcomes are consumed rather than queued. Defaults: 15 s freshness, 60 s cooldown; constructor permits validated overrides. Cooldown persists across restart.
- Result mapping: win → happy, loss → sad, draw → thinking; settle/cancel → idle. `dispose()` on close/disconnect cancels work and motion. A failed agent request is not automatically replayed (at-most-once claim, not exactly-once delivery).
- Motion is an injected `setState(label)` / `reset()` interface. The separate feat4 branch owns sad/idle motion support. This branch does not add renderer scheduling, artwork or settings controls.

Character IDs and session generations are opaque dispatch guards only; no role package schema, unknown-character fallback, or asset installation convention is defined here.

## Checks

`cd apps/companion && npm run check`

Fixture tests establish gate behavior and cancellation. They do not verify FM output, live model suggestions, Electron visual quality or native platform behavior.
