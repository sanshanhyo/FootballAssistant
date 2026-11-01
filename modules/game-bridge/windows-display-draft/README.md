# Offline Windows labelled-position display projection

Unregistered pure-Python prototype. No host, API, transport, game calls, persistent
cache, automatic anchor installation or entity/business-fact conversion.

## Concrete topology evidence

For the one authorized Windows body discovery, both numeric paths exactly equal
`display_profile.py`'s Mac `position_label` and `position` selectors after adding
`panel0/`. This is a comparison of selectors, not a claim that the whole Windows
profile matches the Mac layout.

- Common container depth22: `0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0`.
- Label depth23: container + `/0`.
- Value depth25: container + `/1/0/0`.
- The observed comparison control is outside that common container; it is not
  another position-value candidate. No adjacency/fuzzy/path-search fallback is used.

The repository fixture uses invented TEST text only. Private player data, screenshot
pixels, real session/nonce/hash records and raw captured values are not fixtures.

## Smallest useful MVP contract

Accept exactly one successful schema3 raw-discovery event, plus the caller's
independently retained expected PID/session/candidate-build/module/entry-thread
context. Check event nonce against the inner request, fixed panel0/focus0/6,
known game module hash, text/path bounds, duplicate paths and exact two selectors.
Do not copy expected context out of the event being checked. These checks detect
accidental mixing; they do not authenticate arbitrary JSON or replace a trusted
bounded private transport. No new reader or weakened runtime guard is introduced.

Normalize only observed U+200B, then trim whitespace. Do not remove every invisible
Unicode character, apply NFKC, parse arbitrary markup or transliterate. Reject
remaining controls/format characters, malformed UTF16, markup and oversized text.
The normalization mirrors the relevant U+200B handling in the Mac projection,
not the Mac projection's separate, more expansive markup parser.

With both paths and the normalized literal label `位置`, emit only:

- `status=partial_display_state`, `fields.displayed_position=<display string>`;
- exact container/label/value paths and the single source event nonce;
- `source_identity_unverified=true`, `page_identity_verified=false`;
- `business_identity_known=false`, `entity_id=null`, `snapshot_atomic=false`;
- `source_freshness=unknown`, `captured_at=null`.

This is a narrow UI label/value association. It is not proof of a player's ID,
name, active-page consistency, current position fact or complete profile. A bounded
capture is allowed because both required observations came from one event, but
`partial` remains true even when the first-eight-child prefix was exhausted.
Never merge observations from separate events or retain a previous field when a
new event lacks either leaf. Every failure clears all fields/provenance/context.

An optional operator-supplied page description is a separate object labelled
`bridge_verified=false`, `used_for_identity=false`. It never supplies a name field,
changes validation or turns a display value into a player-owned fact. No real
operator/player name is hardcoded.

## Freshness and identity gaps

The current discovery host's result envelope has no capture start/end timestamp.
Its elapsed duration, file modification time, request creation time and the time
we happen to read the log are not a reliable capture timestamp. Do not import the
Mac adapter's15-second freshness claim or mark an old replay live. A future reviewed
host change could add explicit capture start/end and a consumer freshness policy;
that still would not establish atomic page identity.

Two anchors consisting of a position label and its value cannot identify a player:
many players share them. They can at most check repeated local display content.
The existing anchored batch must still reject absent/unknown anchors and must not
be enabled by this projection. To attach a name later, collect independently
validated header/name evidence with its own exact path and page-consistency
contract; a screenshot/operator context is not a native player ID. Do not infer a
Windows header selector merely because these two body selectors matched.

## Tests

Run `python -m unittest discover -s modules/game-bridge/windows-display-draft -v`.
The14 synthetic tests cover exact topology and asymmetric tails, U+200B-only
normalization/UTF16 bounds, missing/reversed/duplicate paths, no cross-event cache,
nonce/session/hash/thread mixing, negative capture status, manual-context separation,
and unknown freshness/identity. This does not validate a live transport or another
player/build/skin. No script opens the private real evidence or a game process.
