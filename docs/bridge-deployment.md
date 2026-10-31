# User-owned bridge setup

The desktop now has an explicit discovery/plan/deploy/disable interface backed by
`football-assistant-backend --bridge-setup`. It reuses the existing private-shadow
preparer; it never downloads a payload on the user's computer and never launches,
stops, restarts or injects an existing game process.

Deployment requires all of: macOS arm64, the exact reviewed FM27 bundle version
27.0.0.2486716 and executable hash, an audited payload with every copied file
hash-listed, a fresh ten-minute plan, sufficient free disk, no running FM, and
three explicit UI confirmations (private copy, signing only that copy, JIT).
Original Steam game files, launch options and OS security settings are unchanged.
No game binary or save is redistributed. Read-only resource symlinks remain inputs.

Each deployment uses a new UUID directory under userData/bridge/instances. Only
a successfully prepared instance is recorded and configured as the backend's
bridge root. Failures never activate a partial copy. Disable is idempotent,
requires the game to be stopped by the user, clears the configured bridge root,
and retains the independent copy/logs. It never recursively deletes the original.
Backend health is reported separately from game-data health: process presence or
HTTP health never means that football data was read.

Windows returns unsupported_platform without executing deployment commands.
Missing or unreviewed payloads cannot be enabled. Current direct-host payloads
are candidates for later isolated game validation, not a claim of production
compatibility. Actual private-shadow signing and game validation on the user's
Mac are not performed by this implementation/CI task.

## Direct host versus legacy plugin

FootballAssistant.DirectBridge.csproj includes the existing C# readers, direct
Doorstop.Entrypoint, and CF main-runloop scheduler, excluding only Plugin.cs (the
optional BepInEx compatibility entry). It targets net10.0 rather than the legacy
net6.0 DLL; this removes the unreviewed community-core distribution dependency.
These packaging/target differences need isolated FM validation even though the
reader source is unchanged. The legacy project remains untouched.

Payload candidates must carry exact official runtime/loader URLs, cryptographic
hashes, source commit/archive, full licenses and runtime notices. A candidate's
manifest remains reviewed:false until the new direct build/runtime passes the
separate game acceptance gate; no setting silently overrides that gate.

## Reproducible candidate artifacts

The `Bridge payload candidate` workflow compiles only our direct host, runs the
existing offline tests plus reflection-only entry/dependency checks, then builds
a separate **NOT-DEPLOYABLE** artifact. It is not automatically inserted into
the desktop download. `payload-sources.json` pins the exact public inputs:

- Doorstop 4.6.0 debug archive: official release asset; SHA-256 matches the
  previously exercised library. Full LGPL-2.1 license and corresponding source
  archive at commit `1c3ece1f1e6c20f4aa74d5402baabf8a0098d282` are included.
- .NET 10.0.14 osx-arm64: official binary tarball, SHA-512 pinned from Microsoft's
  release metadata. Full LICENSE.txt and ThirdPartyNotices.txt are included.
  This security-patched candidate replaces historical 10.0.13 only after the
  separate game acceptance gate; no claim of equivalent in-game validation.

The runtime input was measured at 33,251,887 compressed bytes and 86,195,727
bytes for its runtime directory. Expect roughly 34 MB compressed / 87 MB on disk
for a complete candidate, plus the source-game executable copied during actual
shadow preparation; final CI artifact size is authoritative. Plan/deploy both
check free space against all copied binaries + source executable, with a 20%
margin and 64 MiB reserve. No game resources/saves are copied into the payload.
