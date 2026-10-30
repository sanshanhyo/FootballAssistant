# Offline reader semantics workbench

This is a **candidate-finding tool, not a football field mapper**. It compares
private copied native packets without opening the game, invoking game methods,
calling a model, using a network, or modifying runtime state. It does not make
player/team/entity claims and cannot control the game.

## Run from a repository checkout

Python 3.12+ and the checkout are sufficient; no package installation is needed.
Keep the manifest and its copied keys/payload files together in each capture
folder. These are the manifest inputs supported by `decode_native_packet.py`,
not its exported decoded JSON. Do not upload raw packets to use this command.

```sh
python scripts/reader_semantics.py \
  --a private-captures/a/packet.json \
  --b private-captures/b/packet.json \
  --return-a private-captures/return-a/packet.json \
  --max-changes 128 \
  --output private-captures/comparison.json
```

`--return-a` is optional. `--registry-sidecar private-captures/registry.json`
optionally supplies one matching property registry. Omit `--output` to write JSON
to stdout. An output file must not already exist; directories are not created.
Exit codes: **0** comparison produced (including zero differences), **2** valid
copies but comparison not established, **1** input/output refused. CLI errors
are deliberately generic and do not echo private filenames or contents.

## How to collect useful evidence

1. Capture A on one known screen/state using the existing capture workflow.
2. Change only one visible factor and capture B in the same game session.
3. If possible return to the original state and capture a new return-A packet.
4. Keep your screen/action notes separately; the CLI does not accept or disclose
   them. Inspect the candidate paths against those notes locally.

The command does **not** establish capture chronology, control other changing
variables, or verify your action notes. Packets can be partial channel updates:
a missing channel/property means **not observed**, never deletion or zero.
Distinct packet IDs do not prove independent captures; identical bytes are
allowed and yield no difference. Return-A agreement strengthens a question to
investigate, not a confirmed meaning or cause.

## What the report says

- Each capture retains packet/session IDs, manifest/keys/payload hashes, pinned
  assembly/metadata/plugin hashes, observer/managed build hashes, and optional
  registry sidecar hash. The arbitrary game-build label is represented by its
  canonical JSON SHA-256, not copied verbatim.
- The existing `decode_packet()` rechecks complete-copy flags, file sizes,
  hashes, pinned decoder build and optional registry provenance. This proves
  local **copy integrity**, not that the manifest is authentic or that bytes
  independently came from a live game. Merely setting `synthetic: false` is
  never reported as independent verification.
- Only complete supported grammar with a proven positional key/value count
  match can be compared. Unknown tags stop comparison; no cursor, type or
  business meaning is guessed. Duplicate channel keys stop comparison.
- Sessions, game-build labels, assembly/metadata/plugin builds and observer/
  managed builds must match. Cross-session numeric channels are not joined.
- `candidate_changes` is ordered deterministically by numeric channel key and
  structural path. `property:80:0` means the first occurrence of property ID 80;
  duplicate property IDs retain separate occurrence positions. `index:0` means
  list position, **not** an entity ID. An empty path means the channel root.
- Each changed node has tag, decoder kind and structural SHA-256. Parent
  container changes and nested changes can both appear; these are not
  independent observations. Offsets and registry labels are excluded from
  structural hashes; tag, prefix byte, order and property duplicates remain.
- Strings, scalar values, opaque buffers, arbitrary source metadata, registry
  names and absolute paths are not emitted. Even numeric values remain hashed:
  without semantics they could be private identifiers. Property IDs and channel
  IDs remain visible for local investigation; treat the report as private.
- Optional `return_matches_a` is true/false only when the corresponding A and
  return-A nodes were both observed. Otherwise it is null. It never confirms
  stable channel lifetimes, entity identity or a football mapping.

## Bounds and limitations

Input manifest: 64 KiB each; registry sidecar: 1 MiB. Strict JSON rejects duplicate
object keys, NaN/infinities, excessive depth/nodes/strings and oversized integers.
The existing capture limits remain 4,096 keys and 64 KiB payload per packet.
Report changes default to 128, configurable from 1 through 512; the report also
includes the full candidate count and `truncated` flag. Output has a 2 MiB cap.
No unbounded globbing, recursion through directories, subprocesses or remote
inputs are used. Payload/key files must be direct independent files beside the
manifest, not symlinks/path escapes. Keep captures stable during the run; this
is an offline local tool, not a concurrent hostile-filesystem service.

Optional registry input is structurally/provenance checked by this workbench
and the existing decoder, but is not independently authenticated. Its hash
preserves the exact sidecar provenance without publishing names. A missing
registry does not prevent comparing numeric property IDs.

This first milestone is checkout-only: no HTTP endpoint, installed console
entrypoint, automatic watcher, candidate promotion, football ontology, UI,
pet integration or runtime write capability is added. Real semantic validation
still requires repeated controlled captures and explicit human review. Synthetic
unit fixtures test software behavior only, never live-game success.

## Validation recorded for this milestone

Cloud Linux, Python 3.12.14, dependencies synchronized from the committed lockfile
with `uv sync --frozen --extra agent --extra save`:

- New workbench tests: **42 passed** (includes real CLI subprocess smoke tests).
- Existing packet-file and wire-decoder tests: **20 passed**.
- Complete configured Python suite: **107 passed, 1 failed**. The failure is the
  existing `test_real_sdk_wiring_and_history_with_local_provider_fixture`: model
  fixture returns 502, with an `AsyncHttpxClientWrapper._mounts` attribute error.
  The same test also fails in a separate untouched `f7d1055` baseline worktree
  using the same environment. No unrelated Agent/dependency fix is included.
- No FM27 process, real captured packet set, Mac/Windows runtime or game write
  was exercised. No paid model API was called.

These are local test results, not a claim that all GitHub Actions checks pass.
