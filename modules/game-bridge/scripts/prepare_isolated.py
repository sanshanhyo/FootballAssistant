#!/usr/bin/env python3
"""Print a private FM27 plan by default. --apply includes shadow signing; needs user approval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
PRIVATE = REPO / "local-game" / "fm27-runtime"
GAME = Path("/Users/husky/Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app")
CORE_HASHES = {
    "BepInEx.Core.dll": "dd8dd33cab8b383af4066a2d0abdc3f290e7dcfa50bc322602b607135efbec78",
    "BepInEx.Unity.Common.dll": "35bcf26bfaf2379a6ec5877a4dd599943b5ae3436f4db6f24e4a2cca83c342b3",
    "BepInEx.Unity.IL2CPP.dll": "80fc9b577e2ee1cf284466778deeffc7fee2624b281bfdfe0a12ea619a5c68e9",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular source file: {path.name}")
    return path


def copy_new(source: Path, target: Path) -> None:
    regular(source)
    if not target.parent.resolve().is_relative_to(PRIVATE.resolve()):
        raise ValueError("Copy destination escaped private root")
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    target.chmod(stat.S_IMODE(source.stat().st_mode))


def main(argv=None) -> None:
    global PRIVATE, GAME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compat-dir", type=Path, help="Already extracted, fixed-commit compatibility source; never executes its scripts")
    parser.add_argument("--runtime-dir", type=Path, required=True, help="Existing arm64 Microsoft.NETCore.App runtime directory")
    parser.add_argument("--doorstop-path", type=Path, required=True, help="Verified UnityDoorstop 4.6+ macOS library (Unity 6.3 chained fixups support)")
    parser.add_argument("--direct-host", action="store_true", help="Use our direct Doorstop entry without optional BepInEx compatibility core")
    parser.add_argument("--apply", action="store_true", help="Prepare and sign private shadow only after explicit user approval; never launches")
    parser.add_argument("--game-path", type=Path, default=GAME)
    parser.add_argument("--private-root", type=Path, default=PRIVATE)
    parser.add_argument("--plugin-path", type=Path)
    parser.add_argument("--allow-shadow-signing", action="store_true", help="Explicit consent to ad-hoc sign only the new independent shadow executable")
    args = parser.parse_args(argv)
    GAME = args.game_path.expanduser().absolute()
    PRIVATE = args.private_root.expanduser().absolute()
    if args.apply and not args.allow_shadow_signing:
        raise ValueError("Explicit consent to private-shadow signing is required; no files changed")
    if sys.platform != "darwin":
        raise ValueError("This preparation path is macOS only")
    if PRIVATE.exists() or PRIVATE.is_symlink():
        raise ValueError("Private root already exists; refusing to overwrite or remove it")
    if PRIVATE.absolute() != PRIVATE.resolve() or REPO.absolute() != REPO.resolve():
        raise ValueError("Private root ancestors must not be symbolic links")
    if not args.direct_host and not args.compat_dir:
        raise ValueError("Compatibility source is required for the optional BepInEx route")
    compat = args.compat_dir.resolve(strict=True) if args.compat_dir else None
    runtime = args.runtime_dir.resolve(strict=True)
    info = plistlib.loads(regular(GAME / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "com.SportsInteractive.FootballManager27" or info.get("CFBundleShortVersionString") != "27.0.0.2486716":
        raise ValueError("Game build changed; repeat offline verification before preparing")
    executable = regular(GAME / "Contents/MacOS" / info["CFBundleExecutable"])
    if digest(executable) != "1c478ecc9a3d984c649a22289ce74cf403d86af7629318177fdc80c7f252c1e5":
        raise ValueError("Original executable fingerprint changed")
    core_source = compat / "dist/bepinex-core" if compat else None
    if not args.direct_host:
        for name, expected in CORE_HASHES.items():
            if digest(regular(core_source / name)) != expected:
                raise ValueError("Compatibility core does not match reviewed build")
    doorstop = regular(args.doorstop_path.resolve(strict=True))
    regular(runtime / "libcoreclr.dylib")
    for source in ([] if args.direct_host else core_source.iterdir()):
        regular(source)
    for source in ([] if args.direct_host else (compat / "dist/dotnet-extras").iterdir()):
        regular(source)
        if (runtime / source.name).exists():
            raise ValueError("Runtime/helper filename collision; review the exact runtime before preparing")
    for source in runtime.iterdir():
        if source.suffix in (".dll", ".dylib"):
            regular(source)
    plugin = regular(args.plugin_path or REPO / "modules/game-bridge/bin/Debug/net6.0/FootballAssistant.GameBridge.dll")
    architecture = subprocess.run(["/usr/bin/file", str(runtime / "libcoreclr.dylib")], capture_output=True, text=True, check=True).stdout
    if "arm64" not in architecture:
        raise ValueError("CoreCLR runtime is not arm64")
    plan = {
        "apply": args.apply,
        "private_root": str(PRIVATE),
        "game_version": info["CFBundleShortVersionString"],
        "original_executable_sha256": digest(executable),
        "native_api_only": True,
        "interop_generation": False,
        "loader_network_downloads": False,
        "entry_mode": "direct" if args.direct_host else "bepinex-compatible",
        "launches_game": False,
        "writes_original_or_steam": False,
        "runtime": str(runtime),
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return

    # There are no archive extractors or third-party setup scripts in this path.
    PRIVATE.mkdir(parents=True, exist_ok=False)
    PRIVATE.chmod(0o700)
    contents = PRIVATE / "fm.app/Contents"
    (contents / "MacOS").mkdir(parents=True)
    shadow_executable = contents / "MacOS" / info["CFBundleExecutable"]
    copy_new(executable, shadow_executable)
    copy_new(GAME / "Contents/Info.plist", contents / "Info.plist")
    for name in ("Frameworks", "Resources", "PlugIns"):
        source = GAME / "Contents" / name
        if source.exists():
            (contents / name).symlink_to(source, target_is_directory=True)
    (PRIVATE / "Data").symlink_to(GAME / "Contents/Resources/Data", target_is_directory=True)
    # Chainloader NativeLibrary.TryLoad("GameAssembly") has a different lookup
    # path than its P/Invoke resolver; keep this read-only basename alias too.
    (PRIVATE / "GameAssembly.dylib").symlink_to(GAME / "Contents/Frameworks/GameAssembly.dylib")

    bepinex = PRIVATE / "BepInEx"
    core = bepinex / "core"
    for directory in (core, bepinex / "config", bepinex / "plugins", bepinex / "patchers", bepinex / "cache", PRIVATE / "generated/interop", PRIVATE / "generated/unity-libs", PRIVATE / "tmp", PRIVATE / "logs", PRIVATE / "diagnostics", PRIVATE / "control", PRIVATE / "dotnet_arm64"):
        directory.mkdir(parents=True, exist_ok=True)
    for source in ([] if args.direct_host else sorted(core_source.iterdir())):
        copy_new(source, core / source.name)
    for source in sorted(runtime.iterdir()):
        if source.suffix in (".dll", ".dylib"):
            copy_new(source, PRIVATE / "dotnet_arm64" / source.name)
    for source in ([] if args.direct_host else sorted((compat / "dist/dotnet-extras").iterdir())):
        copy_new(source, PRIVATE / "dotnet_arm64" / source.name)
    copy_new(doorstop, PRIVATE / "libdoorstop.dylib")
    copy_new(plugin, bepinex / "plugins/FootballAssistant.GameBridge.dll")
    copy_new(plugin, core / "FootballAssistant.GameBridge.dll")
    (bepinex / "config/BepInEx.cfg").write_text(
        "[Logging]\nUnityLogListening = false\n"
        "[Logging.Console]\nEnabled = false\n"
        "[IL2CPP]\nUpdateInteropAssemblies = false\nPreloadIL2CPPInteropAssemblies = false\n"
        f"IL2CPPInteropAssembliesPath = {PRIVATE / 'generated'}\n"
        f"GlobalMetadataPath = {GAME / 'Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat'}\n"
        "UnityBaseLibrariesSource = \nScanMethodRefs = false\nDumpDummyAssemblies = false\n",
        encoding="utf-8",
    )
    (PRIVATE / "steam_appid.txt").write_text("4530370\n", encoding="ascii")
    entitlement_result = subprocess.run(["/usr/bin/codesign", "-d", "--entitlements", ":-", "--xml", str(executable)], capture_output=True, check=True)
    entitlements = plistlib.loads(entitlement_result.stdout)
    entitlements["com.apple.security.cs.allow-jit"] = True
    entitlements["com.apple.security.cs.allow-unsigned-executable-memory"] = True
    entitlement_path = PRIVATE / "shadow-entitlements.plist"
    entitlement_path.write_bytes(plistlib.dumps(entitlements))
    if shadow_executable.is_symlink() or shadow_executable.stat().st_nlink != 1 or shadow_executable.resolve().parent != contents / "MacOS":
        raise ValueError("Signing target is not an independent private executable")
    # Deliberately no --deep: Frameworks/Resources are read-only input symlinks.
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime", "--entitlements", str(entitlement_path), str(shadow_executable)], check=True)
    if digest(executable) != plan["original_executable_sha256"]:
        raise ValueError("Original executable changed during preparation")
    plan["shadow_executable"] = str(shadow_executable)
    plan["core_hashes"] = {p.name: digest(p) for p in sorted(core.iterdir())}
    (PRIVATE / "preparation.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print("Prepared private shadow; no game process was launched.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Preparation stopped: {error}") from None
