# Alpha desktop update contract

## Implemented capability and intentional limits

The previous desktop had no update mechanism. `src/update-controller.cjs` adds a
main-process-only background checker/downloader with observable status. It has no
Electron dependency and never quits, executes a downloaded package, overwrites the
running app, or touches model credentials, runtime configuration, game files or saves.
`start()` checks immediately and every 30 minutes, downloading a verified compatible
candidate in the background. Duplicate operations are coalesced; already downloaded
packages remain ready. `stop()` cancels the request and timer. Network failures are
visible and retried on a later interval. Downloads use exclusive temporary files,
SHA-256 and exact size checks, fsync, then rename; failures remove the partial file.

| Distribution | This implementation | Automatic replacement |
| --- | --- | --- |
| Unsigned macOS application | Signed-feed detection + verified ZIP/DMG download, manual installation | Not supported |
| Windows ZIP/portable EXE | Signed-feed detection + verified download, manual installation | Not supported |
| Future signed macOS / installed Windows NSIS | Same compatibility gate can precede a native installer | Not implemented or tested here |

Without a signed feed/public key the default is **public GitHub release detection**,
not disabled. It makes unauthenticated read-only requests to the fixed official
`api.github.com/repos/sanshanhyo/FootballAssistant/releases` endpoint every 30 minutes
and at startup. Only published, non-draft prereleases with exact tags
`[v]X.Y.Z-alpha.N` belong to this Alpha channel. The highest semantic version is
compared against `app.getVersion()`; packaging and release tags must agree.
Drafts, stable tags, beta tags and arbitrary names are excluded. Pages are checked
(up to 1,000 entries); exceeding the bound is an inconclusive error, not up-to-date.
The app does not follow API redirects, send tokens, download release assets or execute
anything in this mode. Release links are constructed from validated tags, not copied
from untrusted response URLs. A GitHub listing is **not a verified package signature**
and does not establish platform/protocol compatibility. Users review the official
release page and install manually. Private/unavailable repos, rate limits and network
failures remain visible as `network_error`; they are not reported as no update.

Status states: `idle`, `checking`, `up_to_date`, `update_available`, `manual_required`,
`no_release`, `network_error`; signed mode also uses `downloading`, `downloaded`, `error`.
`source` is `github-releases` or `signed-manifest`; `signedDownloadAvailable` explicitly
separates public listing detection from authenticated automatic package downloads.

This checkout contains neither a production signing key nor a fabricated signed feed.
A maintainer must authorize/configure release signing and publish a signed manifest
before signed background downloads work. No release or credential was created.
Private repositories requiring authentication are intentionally not supported: do not
embed GitHub credentials in an application to work around that restriction.

Official documentation checked during implementation:
- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases#list-releases): public release listing works without authentication.
- [Electron autoUpdater](https://www.electronjs.org/docs/latest/api/auto-updater): macOS Squirrel.Mac requires code signing.
- [electron-builder v26 auto update](https://www.electron.build/v26/docs/features/auto-update/): simplified Windows updating targets NSIS; macOS requires ZIP metadata and signing.

The installed builder is v26, so do not assume newer v27 updater behavior. Neither
removing quarantine nor bypassing Gatekeeper is part of this update path. A future
signed/NSIS implementation must disable forced auto-install, observe active gameplay,
recording and conversation work, and install only at a confirmed safe exit/relaunch.
This implementation is safe during those activities because it never installs anything.

## Main-process API

```js
const { createUpdateController } = require('./update-controller.cjs');
const updater = createUpdateController({
  currentVersion: app.getVersion(), platform: process.platform, arch: process.arch,
  configSchema: 1, backendProtocol: 1, bridgeProtocol: 1,
  cacheDir: path.join(app.getPath('userData'), 'updates'),
  // Build-time trusted configuration only; absent until release setup is authorized.
  feedUrl: undefined, publicKey: undefined,
  onStatus: status => { /* forward a structured status to trusted settings renderer */ }
});
updater.start();
// read updater.status; await updater.check(); await updater.download();
// call updater.stop() when shutting down
```

Compatibility protocol values are integer **update compatibility generations**, not
wire-schema strings. Backend and game bridge currently use generation 1 here. Changes
to either generation require a coordinated package and explicit migration design.
Do not accept feed URLs, public keys, cache paths or protocol overrides from renderer
IPC or a user-editable model settings file. Settings UI may request check/download;
it must not invent a native install action. A reveal-download action should use only
the controller's verified path, never an arbitrary renderer-provided path.

## Signed manifest wire format

Envelope: `{ "payload": "<literal JSON string>", "signature": "<base64 Ed25519 signature>" }`.
The signature is over the exact UTF-8 payload bytes, verified against a build-pinned
Ed25519 public PEM key **before** parsing any payload fields. The manifest is limited
to 256 KiB. SHA-256 alone is not publisher authentication; authenticity comes from the
pinned signing key, with HTTPS and an exact repository allowlist as additional layers.

Illustrative payload (hash/size placeholders are not a publishable release):

```json
{
  "schema": 1,
  "channel": "alpha",
  "version": "0.2.0-alpha.1",
  "expiresAt": "2026-12-01T00:00:00Z",
  "configSchemas": [1],
  "backendProtocol": 1,
  "bridgeProtocol": 1,
  "artifacts": [{
    "platform": "darwin", "arch": "arm64", "format": "zip",
    "url": "https://github.com/sanshanhyo/FootballAssistant/releases/download/0.2.0-alpha.1/app.zip",
    "sha256": "<64 lowercase hex characters>", "size": 123
  }]
}
```

In signed-manifest mode, the feed and artifact URLs must be HTTPS GitHub release assets under exactly
`sanshanhyo/FootballAssistant`; redirect destinations are restricted to that repository
or GitHub's exact `release-assets.githubusercontent.com` host. Credentials in URLs,
HTTP, unexpected hosts, expired manifests, unsupported schema/channel, downgrades,
unmatched/duplicate platform-architecture artifacts, invalid digest/size/format,
and incompatible configuration/protocol are rejected. Numeric alpha versions order
correctly (`alpha.10 > alpha.2`). Only `X.Y.Z` and `X.Y.Z-alpha.N` are supported.
Same-version signed feeds report up-to-date. Maximum artifact size is 2 GiB.

## Migration and recovery contract

An application architecture can evolve inside a whole-package release; that does not
mean arbitrary CPU architectures, native dependencies, or protocol generations can be
silently exchanged. An arm64 client will not receive x64. The package must carry its
matching backend; private game-derived bridge material must remain local, outside the
published artifact. No model keys/configuration may be included in the release asset.

`configSchemas` declares the schemas the **new package explicitly knows how to migrate**;
it is not itself a migration implementation. The bootstrap owns settings migrations
and backups. A future migration must validate before write, snapshot prior settings,
write atomically, preserve the old schema backup, and avoid mutating secrets. Unknown
schemas/protocols require manual coordinated recovery rather than optimistic overwrite.

Current failure rollback is prevention: failed/untrusted downloads are discarded and
the existing application/configuration remain untouched. Automatic binary rollback is
**not implemented**. Keep the previous package and validated configuration backup for
manual recovery after a manual install; never restore an older schema over live data
without explicit compatibility validation. Future unattended installation requires
persistent last-known-good package/config state, first-launch health acknowledgement,
and tested crash-recovery/rollback before the feature can be described as seamless.

## Verification scope

`node --test apps/companion/test/update.test.cjs` uses ephemeral test keys and mocked
HTTPS responses. It covers trust/compatibility rejection, version ordering, disabled
fallback detection, duplicate checks, successful verified caching, corrupted/oversized download
cleanup, and malicious redirects. Test-generated keys are not release credentials.
No live release download, native signature verification, automatic installation,
OS-level rollback or user-machine update has been executed.
