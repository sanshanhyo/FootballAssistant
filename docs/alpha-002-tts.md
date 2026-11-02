# Alpha 0.0.2 TTS integration contract

## Implemented and boundaries

`speech-service.cjs` owns cancellable synthesis; `tts-providers.cjs` contains Edge,
OpenAI-compatible and existing Azure adapters. Trusted main code may inject extra
adapters through `ttsProviders: Map<id, { synthesize(payload, signal) }>` returning
`{ bytes: Uint8Array, mimeType, volume }`. This is not an IPC plugin-code API.
The service bounds bytes/time, rejects unsupported providers, and sanitizes errors.
No automatic fallback to another cloud provider (or fake successful mock audio).

`speak` accepts existing operation/conversation/generation IDs plus `text`, provider,
voice, speed (0.5–2, default 1), volume (0–1, default 1). Voice IDs are validated.
Speed maps to Edge rate percentage and OpenAI `speed`; volume is applied once at
renderer playback, not sent as an unsupported OpenAI API field. System TTS retains
its existing behavior; custom speed/volume controls should only be enabled for
renderer-audio providers. Capabilities `available` means configured locally;
`connectivity: unverified` never promises the remote service is currently reachable.

## Integration still required (owned by UI integration)

- Build environment: install `.[agent,speech]` before `build_desktop_backend.py`.
  The pinned speech extra is `edge-tts==7.3.1`. Existing backend extraResources
  copies the entire backend directory, including the new source sidecar.
- Main: pass `bundledEdgePath` (absolute installed backend executable path) into
  `createSpeechService`. Never accept executable paths or credentials from a speak
  payload. Explicit external CLI override remains supported for development.
- Settings: provider, voice, speed, volume, endpoint, model, secret and explicit
  external-text consent. Endpoint/model must be supplied for third-party services;
  do not guess a vendor's URL or reuse a chat model/key automatically.
- Credential persistence: reuse `createCredentialConfig` with a separate TTS
  userData subdirectory and `openai-compatible` provider. That existing layer
  binds keys to endpoint/provider, encrypts with Electron safeStorage, rejects
  basic_text, and falls back to session-only if secure storage is unavailable.
  Main can construct FA_SPEECH_* env in memory from its `backendEnv()` result when
  recreating the speech service after save. Never put keys in preferences, IPC
  capability results, logs, .env files, or character packages. No new secret store
  is implemented in this feature branch.
- Load `tts-queue.js`; create queue with synthesize=IPC speak, cancel=IPC cancel,
  stopPlayback=existing player cleanup. `play(result, signal)` MUST resolve on
  audio ended, reject on error/abort, set `Audio.volume=result.volume`, and stop
  audio/revoke object URLs on abort. It must not resolve just at Audio.play().
  System mode needs its finished event to resolve (or keep its existing path).
- `enqueue(payload)` appends; `{interrupt:true}` replaces. `stop`,
  `switchContext` and `dispose` abort active and queued items and reject them with
  `cancelled`. Connect character/session change, hide, new conversation and user
  interrupt to switchContext/stop; retain existing generation fences.
- Display response text BEFORE enqueuing; synthesis/playback rejection must only
  change voice status, never erase text or block chat/UI interaction.

## Packaging, provenance, and licensing

Upstream primary references checked 2026-11-02:
- https://github.com/rany2/edge-tts/tree/360fa8e1de354e1dda74c09bd695887d6a44df74 (7.3.1)
- https://github.com/rany2/edge-tts/blob/7.3.1/LICENSE
- https://github.com/rany2/edge-tts/blob/7.3.1/README.md
- https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create

Edge-tts is a third-party client of Edge's online service, not Microsoft's official
stable/supported TTS API. Availability, voices, terms and cost can change. No
permanent free-use or uptime promise; failure leaves text readable. This code does
not bypass service restrictions. Azure/OpenAI services may require paid accounts.

Edge-tts is LGPLv3 except srt_composer.py (MIT), NOT all MIT. The unmodified package's
Python source is copied beside the backend, loaded explicitly from there and
replaceable without rebuilding the application. Full upstream LGPL/MIT and GPLv3
texts are retained in packaging/edge-tts-notices and copied with source. The
sidecar manifest records hashes for release QA, not a runtime replacement ban.
Re-sign a modified macOS development app as described in REPLACEMENT.txt. Frozen
Python dependencies remain covered by the existing actual-analysis license
collector. This does not relicense FootballAssistant's own MIT code. Final target
artifacts still require notice/source/replaceability audit before publication.

No user text, secrets or existing private data is used by tests. Unit tests use
fake credentials and injected fetch/spawn/player. Optional real network smoke uses
only the fixed sentence “Football Assistant speech test.” and is not a release
availability guarantee. Desktop playback, signed macOS/Windows packaging and
settings wiring require integration/target-platform checks.

### Verification in the cloud workspace

- Companion `npm run check`: 332 tests passed including the bundled backend invocation test.
- Installed 7.3.1 CLI help and source packaging succeeded. Linux PyInstaller
  sidecar smoke loads the external source; editing its version to 7.3.999 is
  reflected by the same binary's `--version` without rebuilding. This workspace's
  patched Python SSL module required its own `codex-rejected-cas.pem` in the smoke
  bundle; this environment-only file is not a project dependency/change.
- Fixed-text network synthesis failed with TLS certificate verification error
  (`speech.platform.bing.com`, self-signed certificate in certificate chain).
  TLS verification was not disabled. No usable audio generated; real service and
  playback remain unverified from this cloud environment.
