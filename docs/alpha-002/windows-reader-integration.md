# Windows reader integration into 0.0.2-alpha.1

This integration merges the 0.0.1-alpha.2 first-install fix while retaining character
packages and per-character scopes, opt-in TTS, light motion, font size and bubble
duration. It is a test candidate, not a Release or approval to merge main.

The user reported passing the alpha.2 installation acceptance. That report does
not establish every field's semantics, complete squad coverage or match-plugin
acceptance. The fixed game binary fingerprint and limited readback capabilities
remain those documented in `../releases/windows-reader-onboarding.md`.

Existing `settings.json` version 1 and alpha.2 `windowsReaderEnabled` consent are
preserved; an authorized installation does not need to opt in again. The bundled
reader inventory is still revalidated on startup. Old version-1 settings without
reader fields remain supported and require explicit consent. Onboarding does not
rewrite persona or companion preferences. Existing 0.0.2 character migration and
scoping rules are retained, including preservation of user edits and backups.

Reader process-start identity must not become a save identity. Native readbacks
remain in the current character/session scope; switching character cancels old
requests and discards late responses. No game-directory installation or changes
are performed. Match/BepInEx and win/loss reactions remain outside this integration.

Verification includes the existing feature suites plus upgrade-consent/file
preservation and native-readback cancellation regressions. Windows CI must build
the real self-contained CLI, run its offline self-test, audit bundled resources,
and test packaging. Offline fixtures and CLI self-tests do not assert live game
reads. This branch uses `0.0.2-alpha.1`, distinct from the alpha.2 0.0.1 installer.
