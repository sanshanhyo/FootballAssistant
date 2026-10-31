# Alpha desktop update contract

## Current implementation and deployment state

The installed Windows NSIS channel has a connected path:

1. Startup/30-minute HTTPS signed-feed checks.
2. Verify Ed25519 signature, expiry, monotonically newer version, configuration
   schema, backend/bridge compatibility generation, platform and CPU architecture.
3. Stage the full NSIS installer through pinned electron-updater 6.6.2; match native
   metadata version and verify actual downloaded EXE size/SHA-256 against the signed
   manifest. NSIS-web and arbitrary secondary package payloads are not accepted.
4. Wait for FM to be absent, the system idle for at least 60 seconds, and no chat,
   recording/transcription/speech, draft, focused app/settings, model edit, bridge
   operation or pending write. Unknown process inspection is busy, never safe.
5. Check the package again; save a durable settings recovery checkpoint; flush
   conversation persistence and stop only this app's owned backend.
6. Silent NSIS install and relaunch. Never terminate FM or an externally owned backend.
7. New-version first launch validates its journal, starts backend and renderer, and
   acknowledges health. Missing health, old-version restart or corrupt recovery state
   pauses subsequent automatic upgrades and preserves recovery data.

This is **implemented code, not evidence of a production update**. No Release has
been published. A missing signed feed reports `no_release`. The real two-version
Windows fixture is wired into CI; read its exact run result before claiming it passed.
macOS and portable/unknown Windows installations remain manual-install channels.
A CPU architecture switch or unsupported protocol/schema migration is never automatic.

## Explicit Windows trust decision

The owner approved `trustPolicy: 'ed25519-pinned'` on 2026-10-31. The reviewed public
key and fingerprint live in `src/update-trust.cjs`; private material is not present
in this repository/application. This policy verifies a project-controlled release
signature and actual package bytes, **not an Authenticode publisher identity**.
SmartScreen, AppLocker, WDAC, antivirus and OS prompts are neither changed nor bypassed.
First-install provenance still needs a trusted download channel. Some machines may
warn or block; universally prompt-free Windows execution is not promised.

The optional stricter `authenticode-and-ed25519` policy additionally requires
`Get-AuthenticodeSignature` status `Valid` and a pinned certificate thumbprint. It
remains the default when no explicit policy is selected. Unknown policy names fail
closed. Certificate thumbprints identify X.509 certificates and are not file hashes.
macOS native Squirrel.Mac updating separately requires code signing; Windows's extra
Authenticode requirement was our policy, not a universal NSIS platform requirement.

Official sources:
- [builder v26 auto update](https://www.electron.build/v26/docs/features/auto-update/)
- [v26→v27 Windows verification behavior](https://www.electron.build/docs/migration/v27-build-changes/)
- [Electron autoUpdater platform requirements](https://www.electronjs.org/docs/latest/api/auto-updater)

## Feed and release preparation

Fixed signed channel:
`https://github.com/sanshanhyo/FootballAssistant/releases/download/alpha-channel/alpha-update.json`

Versioned installer assets and native `alpha.yml`/blockmap metadata belong to the
same official repository under version tags `X.Y.Z-alpha.N`. The payload EXE URL is
fixed to that repository's HTTPS release-asset route. Redirects are restricted to
GitHub and its exact release-assets host. No embedded GitHub token is used.

`packaging/sign-alpha-update.cjs` takes the completed NSIS installer, hashes it,
checks the secret's derived public key matches the pinned client key, and writes a
14-day signed manifest. It never creates keys, logs private material, or publishes.
The desktop workflow runs signing **only on explicit workflow_dispatch of the
reviewed integration branch**, using `FA_ALPHA_UPDATE_SIGNING_KEY`. It does not expose
that secret to the pull_request path. Workflow permissions remain contents:read and
build commands use `--publish never`. Artifact preparation is not Release permission;
creating/updating the version release and alpha-channel release requires separate
owner authorization after acceptance. Expired feeds fail closed and require a newly
signed manifest. Secret availability is not proof that a signing run has succeeded.

Envelope: `{ "payload": "<exact JSON text>", "signature": "<base64 Ed25519>" }`.
The signature covers exact UTF-8 payload bytes. Payload example structure:

```json
{
  "schema": 1, "channel": "alpha", "version": "0.0.2-alpha.1",
  "expiresAt": "2026-11-14T00:00:00Z", "configSchemas": [1],
  "backendProtocol": 1, "bridgeProtocol": 1,
  "artifacts": [{
    "platform": "win32", "arch": "x64", "format": "exe", "installerType": "nsis",
    "url": "https://github.com/sanshanhyo/FootballAssistant/releases/download/0.0.2-alpha.1/FootballAssistant-0.0.2-alpha.1-Setup-x64.exe",
    "sha256": "<64 lowercase hex characters>", "size": 123
  }]
}
```

The example is not a valid published manifest. Schema/protocol integers are update
compatibility generations, not existing wire-schema strings. `configSchemas` means
the new package explicitly supports those source schemas; it does not magically
implement a migration. Current settings schema remains 1.

## State, integration and safety

Top-level `automaticInstallEnabled` requires signed feed/key plus an eligible installed
NSIS adapter. `installMode` is `idle-restart` or `manual`. `installation.trustPolicy`
identifies the selected verification policy; `publisherVerificationRequired` does not
claim that a publisher was already verified. `recovery.state === recovery_required`
pauses the scheduler regardless of configured capability.

`createUpdateController` handles network checks/staging, `createInstalledUpdater`
checks and dispatches native installation, `createUpdateLifecycle` schedules only idle
attempts, and main owns process/IPC/window/recording checks and shutdown. Renderer IPC
cannot provide trust configuration, URLs, paths, signed envelopes or install commands.
Native `autoDownload` and `autoInstallOnAppQuit` defaults are disabled so no native
quit handler bypasses these gates. Shutdown/logoff suppresses the idle installer.

Absent pinned trust, the fallback is unauthenticated read-only public GitHub Releases
checking. Only published prereleases matching `[v]X.Y.Z-alpha.N` are considered.
Fallback never downloads or executes release assets, nor claims package verification.
No match, older/equal version and failed/rate-limited/private-repo requests are distinct
`no_release`, `up_to_date`, `network_error` states. Listing is capped at 1,000 entries;
exceeding the cap is inconclusive, not up-to-date.

## Recovery guarantees and limits

`update-recovery.cjs` writes an atomic journal and immutable UUID-named backup of
allowlisted, non-secret `settings.json` only. It never copies API keys, credential
stores, backend environment files, persona/history or a full profile. Current
configuration is never overwritten automatically during recovery.

`prepare()` must return `prepared` before dispatch. `beginLaunch()` runs before app
configuration writes; the target's first launch is `awaiting_health`, then health
acknowledgement makes it `healthy`. A second unacknowledged launch, startup failure,
old executable after preparation, missing backup or malformed journal means
`recovery_required`. Existing settings/backups remain available. Hash mismatch or
untrusted downloads never execute.

There is **no automatic binary downgrade/rollback claim**. NSIS may fail after it has
started replacing binaries; a user may need to reinstall the retained prior authorized
installer or a forward-fix release. The current gate retains native cached update
artifacts/journal but does not bundle a verified previous-version installer. Full
crash-proof binary rollback requires a separately tested installer/first-launch
supervisor design. This implementation does not restore an incompatible old schema
or overwrite newer user edits to pretend recovery succeeded.

## Verification

`npm run check` covers trust rejection, download integrity, explicit policy choice,
recovery checkpoints, safe-activity deferral and main/UI security tests.
`test/update-native-fixture.cjs` runs only on disposable Windows GitHub Actions: it
builds isolated real NSIS v1/v2 apps, uses an in-memory ephemeral Ed25519 fixture key
and loopback generic provider, performs a native download/install/relaunch, checks
settings preservation and records health. It never changes OS trust stores, uses a
production private key or publishes a release. Report:
`RUNNER_TEMP/companion-smoke-update-fixture.json`.
Its `productionReadiness:false` and `authenticodeValidated:false` are intentional.
Only a completed passing Windows run establishes the native fixture path passed;
Linux syntax/unit checks alone do not.
