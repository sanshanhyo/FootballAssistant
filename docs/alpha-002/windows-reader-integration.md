# Windows reader integration into 0.0.2-alpha.3

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
requests and discards late responses. Offseason reads do not modify the game.

Alpha.3 includes Windows BepInEx + MatchReader
deployment and one-choice offline installer from 0.0.1-alpha.4. It writes the displayed loader/plugin files only
after explicit consent with the game closed; conflicting third-party components
are preserved. Backups, owned upgrades and rollback use the same transactional
installer. The installer path selection and install confirmation authorize deployment.
Runtime dependencies are bundled; BepInEx is configured for local metadata
generation without unstripping or Unity library downloads. Existing nonempty
Unity library directories fail closed instead of being deleted or silently used. Real injection, first-run offline generation and match fields
have not been newly verified; existing alpha.2 offseason acceptance is not match
acceptance. Win/loss proactive reactions remain disabled and out of scope.

Verification includes the existing feature suites plus upgrade-consent/file
preservation and native-readback cancellation regressions. Windows CI must build
the real self-contained CLI, run its offline self-test, audit bundled resources,
and test packaging. Offline fixtures and CLI self-tests do not assert live game
reads. This branch uses `0.0.2-alpha.3`, distinct from earlier 0.0.2 packages and
0.0.1-alpha.4. Silent setup without a provided or previously saved FM path must
fail explicitly; isolated CI cannot establish complete game installation. Per the latest user direction, this match integration adds no new
tests or live-game acceptance round; syntax/build/resource checks remain. Earlier
verification counts refer to the earlier offseason integration, not this change.
