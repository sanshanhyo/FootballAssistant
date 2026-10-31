# Desktop-owned backend (MVP)

End-user launch target: open **FootballAssistant.app** on macOS, or the single
**FootballAssistant-…-win-x64.exe** portable distribution on Windows. The latter
extracts its internal resources and runs Electron plus a backend child; “single
EXE” describes distribution, not a single running process. Neither requires the
user to install Python, uv, Node or use a terminal when the complete bundle exists.

## Startup and ownership

- Electron takes a single-instance lock and generates version-1 `settings.json`
  in Electron's per-user `userData` directory, not inside the installed app.
- A local runtime with an authenticated `/v1/status` response is reused. An
  explicitly selected external runtime is never silently replaced.
- Otherwise the packaged `resources/backend/football-assistant-backend[.exe]`
  is spawned. Only this child is terminated on app exit. Failed readiness does
  not kill another service, change OS settings, or start/inject/restart FM.
- Missing/corrupt configuration is reported without overwriting it. No `.env`,
  key, game save or private bridge is distributed. Ordinary settings contain
  only backend port and optional explicitly selected local paths.
- Settings UI handles model configuration; secrets are managed by the separate
  credentials module, not `settings.json`. Saving does not call the model.
- Existing external backend configurations remain compatible; the app does
  not migrate secrets or reconfigure an external process.
- Game process detection is informational only, never proof of data connection.
  Bridge/data status remains the reader's responsibility. A fresh install has
  no private bridge. Windows page-reading remains `unsupported_platform`.

## Maintainer builds, not end-user steps

On each target OS/architecture, install this project with the `agent` extra and
PyInstaller 6.16.0, then run `python scripts/build_desktop_backend.py`. It creates
`build/desktop-backend/football-assistant-backend/`, including the Python runtime.
Then `npm ci` and `npm run pack:mac` / `npm run pack:win` from `apps/companion`.
Electron-builder copies that target-specific backend into resources. Do not
package a Linux backend into a Mac/Windows app. Desktop CI performs these steps
on native macOS arm64 and Windows x64 runners. No Release is published by it.

The historical `scripts/run_mvp.py` is a developer/existing-local-install helper,
not the universal installer. Its uv dependency is not used by packaged startup.

## Release boundaries

Current packaging is unsigned. macOS signing/notarization and Windows signing
must be completed separately for a normal trusted public distribution; this
change does not bypass Gatekeeper/SmartScreen. Windows portable target does not
support silent replacement through the current updater. The default updater checks public GitHub Alpha release metadata and offers manual
installation. Signed automatic downloads remain unavailable until a reviewed
feed and public key are configured.

A successful frozen Linux smoke test proves dependency bundling there only.
Native .app/portable build and clean-machine first-run tests remain necessary
before calling Mac/Windows distribution verified. No private FM bridge or full
Windows game data support is implied by a backend/package build.
