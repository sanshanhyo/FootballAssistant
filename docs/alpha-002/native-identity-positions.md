# Alpha 0.0.2: native current-manager and position handoff

Source: original FMAPI research at commit `99aba1d2aed7dc38a43d542e6abf87793a4ad1ce`, based on `1c0c561ef1e38e01c35f1c1576491979ee9cb23c`. Relevant source files are `tools/FMAPI.MessageProbe/EntityLinks.cs`, `PositionFields.cs`, and `docs/research/native-entity-evidence.md`. The transfer bundle was verified against its prerequisite commit before integration. No game binaries, captures, user rosters, private paths, or game-generated interop assemblies are added.

## Evidence and limits

The supported profile pins the researched native binary, GameAssembly and metadata fingerprints. New semantic claims fail closed when that profile is unavailable; existing independent date/raw/candidate reads remain compatible.

The current manager is the native GCuM-selected local human PERSON, matched exactly once in the bounded human-owner collection, with the validated employment contract → team → club chain. It is not a guessed single candidate, a save identifier, or proof of multiplayer authority. Reads are checked again for changes, but are not atomic snapshots. Live research confirmed one loaded session; manager switching, reload and hotseat behavior have not been established by that capture.

The 14 named position familiarities come from the researched native mask mapping. GK familiarity >= 15 implements the native goalkeeper predicate. Natural-position bits use >= 18. The unused byte between GK and DL emits no position bit. These familiarities are distinct from the four existing raw attribute bytes: raw attributes must not be presented as 1–20 ratings. Goalkeeper eligibility does not establish current match assignment or best overall ability.

## Consumption

A fresh validated current-manager binding can select the current local club without requiring users to type UIDs or reconfirm a candidate. Unverified/legacy producers retain natural-language confirmation. Team rows receive position blocks during the existing bounded double-read roster walk. There is no 27-player full-registry fan-out.

Keeper questions filter only fully validated position evidence and read attributes for at most two eligible candidates. More than two are named explicitly for selection, rather than silently dropping people. Missing positions are not treated as negative eligibility. Users can still select roster names explicitly.

Conversation, character, process or current-manager/team/club changes invalidate selected people and cached data. Related attribute reads must match the same producer session and native binding. Missing/changed evidence suppresses the comparison. The existing character-context response check, consent gates, partial-data labeling and business-snapshot gate remain in effect.

Synthetic Python/C# tests exercise these contracts. They do not constitute a new live-game acceptance, and the release remains subject to user validation.
