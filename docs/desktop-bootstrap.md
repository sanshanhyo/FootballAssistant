# Desktop-owned backend (MVP)

End-user launch target: open **FootballAssistant.app** on macOS. Windows now
builds **FootballAssistant-…-Setup-x64.exe** (per-user NSIS installer) and
**FootballAssistant-…-Portable-x64.exe** (single-file portable fallback). The portable build
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

## Windows installer verification

The assisted NSIS installer defaults to per-user installation, permits selecting
the install directory, and does not request elevation or automatically launch
the app after setup. Uninstall explicitly retains user settings/data. Its
installation.json marker identifies the NSIS distribution only; it is not proof
of signature or authority to install updates. Portable distributions have no
installed marker and never receive the installed-app update path.

`apps/companion/test/nsis-smoke.ps1` is restricted to disposable GitHub Windows
runners. It silently installs into a unique RUNNER_TEMP directory, launches with
an isolated user-data directory, verifies the embedded backend, reinstalls the
same version, launches again, then uninstalls and checks that settings/persona
remain byte-for-byte unchanged. This is a CI test, not authorization to run a
silent installer on the user's machine.

`electron-updater` 6.6.2 is pinned for the guarded NSIS adapter. The adapter stays
manual-only until a reviewed release-signing key and Windows signing certificate
are provisioned. The current unsigned Alpha therefore does **not** claim that
automatic application replacement is operational. No signing keys, GitHub
secrets or Release publication are created by these build changes.

### CI downloads

Windows Setup and Portable are uploaded as **separate** artifacts:
`companion-windows-setup-x64` and `companion-windows-portable-x64`. Download only
the desired distribution; neither download includes the other EXE. Update
metadata and smoke diagnostics are separate maintainer artifacts. macOS remains
one `companion-macos-arm64` artifact containing one permission-preserving tar.gz.
Every upload fails if its file selection is empty.
