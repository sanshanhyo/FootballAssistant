# Experimental observed UI display profile

`football-assistant-reader profile` (or `profile` inside the JSON console) reads
`GET /v1/reader/profile`. The endpoint requires the same bearer authentication as
other reader endpoints; never put the token in command arguments. It works in the
reader-only service without a model/provider dependency. There is no profile
write endpoint.

This is **display text, not native player data**. A successful response has:

- `status: experimental_observed_display_profile`, `source_kind: ui`, `partial: true`
- `entity_id: null`, `business_identity_known: false`
- `fields`: `name_display` (string), `position_display` (string),
  `height_cm_display` (integer)
- `field_provenance`: exact UI paths, source event, game session, capture and
  observation times, adapter/version and game build for each field
- `evidence`: the selected normalized texts and paths, including required anchors
- `rule_id`, `reason`, and explicit `limitations`

The unavailable response always clears **all** fields, provenance and evidence.
There is no previous-player cache, guessed identity, fuzzy global string match,
native ID association, technical attribute mapping or current-club inference.
A club in a season/career row is not evidence of the current club and is omitted.
UI paths identify observed text locations, never football entities. Strings are
JSON data, not executable instructions or HTML.

## Deliberately narrow rule

Version 2 is frozen to FM27 build `27.0.0+2486695`, adapter
`footballassistant.runtime-ui-tree` version `0.4.0` on `macos-arm64` only, and the observed Chinese
player-overview layout. Exact name/header paths in `panel0/0/3` must coexist with
exact body paths in `panel0/0/6`. Required Chinese anchors are overview, contract,
transfer, growth, position, information and height. The contract anchor is resolved only as a unique normalized `合同` inside its
fixed header slot 2, at most eight numeric descendant segments deep; its actual
path is recorded in evidence. All other selectors remain exact. The labelled
position is the full display position. A separate secondary role is required
only as a structural marker and may legitimately differ; it does not corroborate
the position or appear in position provenance. The cached manager subtree `panel0/0/4` cannot provide profile values.
Other tab paths that varied during observation are not used. There is no skin-ID
detection or skin compatibility guarantee: changed structure or required text
fails closed. Appearance-only changes have not been independently validated.
Unknown, absent or non-Mac-ARM64 source platforms fail closed; portable unit tests
on another operating system do not establish compatibility with that game runtime.

Only balanced observed Unity `link` (numeric value), `style="Norml"`, and hex
`color` wrappers are stripped, along with U+200B. Unknown tags, malformed nesting,
control characters, oversized strings, missing/duplicate selectors, changed
anchors, ambiguous contract anchors, and non-centimeter/out-of-range heights fail
closed. Height is accepted only as three decimal digits followed by `厘米`,
between 100 and 250. Names and positions remain display strings; positions are
not converted to a business taxonomy.

## Source and freshness boundary

`project_display_profile(snapshot, *, now=None, max_age_seconds=15)` is a pure
projection callable. `now` can be a timezone-aware datetime for offline tests;
production uses current UTC. Callers can tighten but cannot increase the
15-second freshness bound. Capture, observation and last-seen timestamps must be
aware, not future-dated, and within that bound. The selected source must explicitly
be available, connected, fresh, live runtime and non-synthetic. Build, adapter,
session, snapshot event, status event and selected-fact metadata must agree.
A modern reader envelope is validated; legacy snapshots require per-fact source,
game, event, capture timestamp and `value_observed` metadata.

The endpoint projects one selected `reader_snapshot(0, 80)` under the existing
storage selection policy. It does not combine streams, bypass selection, or
raise the adapter's capture budget. The full bounded response must fit in 80
facts, with consistent counts and no more pages. That is **not** a full UI tree:
the adapter itself has an 80-text cap, 15 ms time budget and node/depth limits.
Per-element visibility, occlusion and active page are not independently verified;
no screenshot is captured or verified by this feature. Exact layout evidence
reduces ambiguity but does not make the source a native/entity-level reader.

`ReaderClient.profile()` prefers the new endpoint. Only HTTP 404 triggers local
projection of the already-supported snapshot API (including legacy monitoring
fields). It then re-reads source status and rejects event/source/session/time
changes between independent requests instead of returning the old player. It
uses the existing literal-loopback, no-proxy, no-redirect transport and response
size limit. Authentication errors and disconnects are not silently converted to
successful profile results. Error responses do not echo raw metadata or secrets.

## Evidence and validation limits

The initial selectors were derived from private UI observations of two players,
A → B → A, plus a non-player negative. Those observations and real player values
are **not** repository fixtures. Repository tests use invented TEST-marked data.
Historical observations can validate the rule offline with injected time; they
must not be described as current live data. An initial third-player held-out observation failed closed and exposed a
conditional contract-tab wrapper and a distinct secondary-role display. Version 2
incorporates those two bounded corrections; that observation is now regression
evidence, not independent held-out validation. The subsequent fourth-player
replay is recorded below. Other languages/builds/skins and deployment into the
running service remain unverified. Additional live acceptance should bracket
page reads with UI observations, include a fresh frame and a non-player negative,
and avoid silently changing rules to fit held-out values.

## Recorded validation for v2

- 119 synthetic projection/API/client/CLI tests pass; together with the existing
  reader tests, 130 pass. The complete Linux Python suite reports 244 passed and
  the same one pre-existing local model SDK fixture failure documented in the
  workbench validation. No paid model endpoint or game write was tested.
- Private captures of the initial two players and a manager-page negative pass
  offline replay at their recorded read times. The first held-out player exposed
  a conditional contract-tab leaf and the difference between the labelled
  position list and a secondary role. These informed v2 and are regression data,
  not an independent v2 acceptance claim.
- After freezing v2, two distinct event snapshots of a fourth player project the
  displayed name, labelled position and height consistently with operator UI
  notes. A fresh manager-page negative clears the profile. The prior contract
  and squad-page negatives also remain rejected. No rule change was made using
  the fourth player's values. These samples remain private and outside Git.
- This is replay validation of authentic observations plus operator page notes,
  not deployment of the new endpoint into the currently running Mac service.
  The legacy fields and status requests are independent, and a screenshot is not
  a cryptographic proof of snapshot ownership. Skin, language, game-build,
  Windows game runtime and arbitrary navigation coverage are not established.
