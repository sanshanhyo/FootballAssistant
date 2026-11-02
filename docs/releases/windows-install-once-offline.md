# One-path Windows installation: offline dependency boundary

Candidate versions: `0.0.1-alpha.4` and `0.0.2-alpha.3`. This document records implementation evidence, not real-game acceptance. No new test campaign or game launch is claimed.

## Dependency policy

The NSIS path-selection flow must deploy the owned reader components and write their local backend/snapshot configuration without asking the user to repeat setup in Settings. The existing bundled Python backend, self-contained offseason CLI, .NET loader runtime, native loader and MatchReader remain package resources. Installation and the first reader/game startup must not download dependencies. User-configured online model or TTS requests are a separate, explicit application capability; this is not a claim that an online model works without a network.

The official BepInEx archive remains the same 34,335,572-byte input, SHA-256 `2a7cbf74d26abe4765c3e662db1721b923bac39849ebfef2ca5dc7de7e2d9b7f`. It is reconstructed from the existing pinned repository binary parts. Every part and the complete archive must match before extraction. No network fallback to the previously blocked archive service is used. Build-time retrieval of fixed open-source corresponding-source archives is distinct from installation/runtime dependency downloading.

## Official local-generation mode

The installer writes this owned BepInEx configuration:

```ini
[IL2CPP]
UnityBaseLibrariesSource =
UpdateInteropAssemblies = true

[Logging]
UnityLogListening = false
```

This is not a fake base-library ZIP, fake interop hash, or a cache imported from a research machine. BepInEx continues to generate interop locally from the user's own `GameAssembly.dll` and `global-metadata.dat`, and retains its normal input-hash regeneration logic. No Unity DLLs or generated game interop are distributed.

Evidence from the exact pinned upstream source:

- [BepInEx 6abdba4 Il2CppInteropManager](https://github.com/BepInEx/BepInEx/blob/6abdba47eeebe08552282e7a58ef0f4a9ab60b62/Runtimes/Unity/BepInEx.Unity.IL2CPP/Il2CppInteropManager.cs): `DownloadUnityAssemblies` returns immediately for an empty source; `RunCpp2Il` uses the local native binary and metadata. `UpdateInteropAssemblies` and `ComputeHash` are not disabled or replaced.
- [Il2CppInterop dbda1cb generator](https://github.com/BepInEx/Il2CppInterop/blob/dbda1cb353b0f4253345dc45136d170b9e50a5a0/Il2CppInterop.Generator/Runners/InteropAssemblyGenerator.cs): no Unity base-libraries directory uses `NullMetadataAccess`; optional unstripping passes restore types, fields and methods only when base libraries are supplied.
- [Cpp2IL 558ddd9 metadata reader](https://github.com/SamboyCoding/Cpp2IL/blob/558ddd98642010897d54316b51fbaa7889fda093/LibCpp2IL/Metadata/Il2CppMetadata.cs): includes metadata-v39 dynamic parameter/index handling. This is static compatibility evidence, not proof of successful generation on the specific game.
- [BepInEx chainloader](https://github.com/BepInEx/BepInEx/blob/6abdba47eeebe08552282e7a58ef0f4a9ab60b62/Runtimes/Unity/BepInEx.Unity.IL2CPP/IL2CPPChainloader.cs): Unity log forwarding is optional. Disabling it avoids the optional `UnityEngine.Application` log callback; normal loader and plugin logs remain available.

The FA MatchReader uses `BasePlugin` and native hooks, not `UnityEngine` components. Omitting optional unstripping therefore avoids introducing a dependency it does not intentionally use. It does not guarantee every runtime type required indirectly by BepInEx/Interop exists in this custom game's metadata. Missing types or local-generation errors must be reported, never hidden with network fallback or a false-ready status.

## Exact observed game boundary

Read-only Windows file-version evidence identifies Unity `6000.3.18f1-custom (96cdb67fb884)`, file version `6000.3.18.9883062`, x86_64 UnityPlayer SHA-256 `c927f41849e3347cfc430a90b05f072df07ac45b0b2a3b39e9412c776f7c0d57`. This records the target; it does not prove compatibility with generic `6000.3.18` Unity libraries. No such libraries are bundled, and no independent Unity binary redistribution permission is asserted.

The inspected installation had neither `fm_Data/Managed` nor `BepInEx/unity-libs`. The installer must not claim that a missing library cache exists or copy arbitrary third-party libraries from another installation. Existing unowned loader/configuration conflicts remain fail-closed; rollback must preserve user data and other mods.

## Delivery limits

Offline deployment and local-generation behavior are the intended package design. Compilation and resource/hash/license checks are necessary build evidence. Actual custom-build interop generation, match plugin startup and match data are not newly verified by these checks. Production signing, Release publication and main merges remain separate actions.

## Existing CI scope after the installation contract changes

Hosted Windows runners contain no authorized FM game directory. The production Setup check now requires silent fresh installation without a game path to exit with code 3 without a success channel marker or committed reader configuration, without claiming profile-preservation coverage. Application files may already be extracted because the installer runs its own bundled headless helper to resolve the real user-data/settings location; this is an explicitly incomplete installation, not success. Its report explicitly marks full installation, reinstall/uninstall lifecycle and actual game deployment `not_run`; a successful rejection is not installation success. The helper intentionally uses Electron's real user-data location, not the portable-smoke test override. The separately built two-version updater fixture retains its existing checks but does not include the production installer/game-path flow. Its success is evidence about the updater primitive only, not full product deployment or real-game acceptance. No production bypass flag or fake game directory is introduced.
