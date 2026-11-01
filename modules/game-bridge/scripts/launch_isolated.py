#!/usr/bin/env python3
"""Show the private launch plan. --launch requires explicit approval and an exited game."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import shutil
import plistlib

REPO = Path(__file__).resolve().parents[3]
PRIVATE = REPO / "local-game/fm27-runtime"
GAME = Path("/Users/husky/Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app")


def main(argv=None) -> None:
    global PRIVATE, GAME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true", help="Launch exactly one private game instance after explicit user approval")
    parser.add_argument("--native-observer", action="store_true", help="Enable reviewed header-only native observer at the fresh main-menu checkpoint")
    parser.add_argument("--game-path", type=Path, default=GAME)
    parser.add_argument("--private-root", type=Path, default=PRIVATE)
    parser.add_argument("--runtime-file", type=Path, default=REPO / "local-data/runtime.json")
    args = parser.parse_args(argv)
    GAME = args.game_path.expanduser().absolute()
    PRIVATE = args.private_root.expanduser().absolute()
    manifest_path = PRIVATE / "preparation.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("Private preparation manifest is missing")
    plan = json.loads(manifest_path.read_text(encoding="utf-8"))
    if PRIVATE.absolute() != PRIVATE.resolve() or plan.get("private_root") != str(PRIVATE):
        raise ValueError("Private root does not match reviewed location")
    bundle = plistlib.loads((GAME / "Contents/Info.plist").read_bytes())
    if bundle.get("CFBundleIdentifier") != "com.SportsInteractive.FootballManager27" or bundle.get("CFBundleShortVersionString") != plan["game_version"]:
        raise ValueError("Original game bundle changed; refresh the private preparation and evidence")
    original = GAME / "Contents/MacOS" / bundle["CFBundleExecutable"]
    if hashlib.sha256(original.read_bytes()).hexdigest() != plan["original_executable_sha256"]:
        raise ValueError("Original executable changed since private preparation")
    executable = PRIVATE / "fm.app/Contents/MacOS/Football Manager 27"
    if executable.is_symlink() or executable.resolve() != executable or executable.stat().st_nlink != 1:
        raise ValueError("Shadow executable is not a private independent file")
    for directory in ("BepInEx", "BepInEx/config", "BepInEx/core", "BepInEx/plugins", "BepInEx/cache", "generated", "generated/interop", "generated/unity-libs", "tmp", "logs", "diagnostics", "control", "dotnet_arm64"):
        path = PRIVATE / directory
        if not path.is_dir() or path.resolve() != path:
            raise ValueError("A writable directory is missing or points outside private root")
    # Every writable subtree is private. Reject links left by an earlier run,
    # including cfg/log files, before handing these paths to the loader.
    for directory in ("BepInEx", "generated", "tmp", "logs", "diagnostics", "control", "dotnet_arm64"):
        for current, directories, files in os.walk(PRIVATE / directory, followlinks=False):
            for name in directories + files:
                path = Path(current) / name
                if path.is_symlink() or not path.resolve().is_relative_to(PRIVATE):
                    raise ValueError("A writable subtree contains a symbolic link")
                if path.is_file() and path.stat().st_nlink != 1:
                    raise ValueError("A writable subtree contains a hard-linked file")
    for name, expected in plan["core_hashes"].items():
        path = PRIVATE / "BepInEx/core" / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed compatibility core changed")
    runtime_file = args.runtime_file.expanduser().absolute()
    if not runtime_file.is_file():
        raise ValueError("Start the backend before the isolated game")
    attempt = PRIVATE / "logs" / datetime.now(timezone.utc).strftime("attempt-%Y%m%dT%H%M%S%fZ")
    command = ["/usr/bin/arch", "-arm64", "-e", f"DYLD_INSERT_LIBRARIES={PRIVATE / 'libdoorstop.dylib'}", "-e", f"DYLD_LIBRARY_PATH={PRIVATE}:{PRIVATE / 'dotnet_arm64'}", str(executable), "-logFile", str(attempt / "unity.log")]
    print(json.dumps({"launch": args.launch, "cwd": str(PRIVATE), "command": command, "log": str(attempt / "game-launch.log"), "rollback": "Exit this shadow game; launch the original normally in Steam."}, indent=2))
    if not args.launch:
        return
    processes = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=True)
    running = any(line.strip().partition(" ")[2].strip().endswith("/fm.app/Contents/MacOS/Football Manager 27") for line in processes.stdout.splitlines())
    if running:
        raise ValueError("FM27 is still running; save and exit it yourself before this single-instance test")
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("DYLD_", "DOORSTOP_", "BEPINEX_", "FM26_"))}
    environment.update({
        "FOOTBALL_ASSISTANT_RUNTIME_FILE": str(runtime_file),
        "FOOTBALL_ASSISTANT_PRIVATE_ROOT": str(PRIVATE),
        "FOOTBALL_ASSISTANT_GAME_ASSEMBLY": str(GAME / "Contents/Frameworks/GameAssembly.dylib"),
        "FOOTBALL_ASSISTANT_GAME_PLUGIN_PATH": str(GAME / "Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin"),
        "FOOTBALL_ASSISTANT_GAME_PLUGIN_SHA256": hashlib.sha256((GAME / "Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin").read_bytes()).hexdigest(),
        "FOOTBALL_ASSISTANT_ENABLE_NATIVE_OBSERVER": "1" if args.native_observer else "0",
        "FOOTBALL_ASSISTANT_ASSEMBLY_SHA256": hashlib.sha256((GAME / "Contents/Frameworks/GameAssembly.dylib").read_bytes()).hexdigest(),
        "FOOTBALL_ASSISTANT_METADATA_SHA256": hashlib.sha256((GAME / "Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat").read_bytes()).hexdigest(),
        "FOOTBALL_ASSISTANT_BUNDLE_VERSION": bundle["CFBundleShortVersionString"],
        "BEPINEX_GAME_ASSEMBLY_PATH": str(GAME / "Contents/Frameworks/GameAssembly.dylib"),
        "DOORSTOP_ENABLED": "1",
        "DOORSTOP_TARGET_ASSEMBLY": str(PRIVATE / "BepInEx/core/FootballAssistant.GameBridge.dll"),
        "DOORSTOP_CLR_RUNTIME_CORECLR_PATH": str(PRIVATE / "dotnet_arm64/libcoreclr.dylib"),
        "DOORSTOP_CLR_CORLIB_DIR": str(PRIVATE / "dotnet_arm64"),
        "DOTNET_ROLL_FORWARD": "LatestMajor",
        "ARCHPREFERENCE": "arm64",
        "SteamAppId": "4530370",
        "SteamGameId": "4530370",
        "SteamOverlayGameId": "4530370",
        "TMPDIR": str(PRIVATE / "tmp"),
        "TMP": str(PRIVATE / "tmp"),
        "TEMP": str(PRIVATE / "tmp"),
    })
    build_evidence = PRIVATE / "game-plugin-build.json"
    if build_evidence.is_file() and not build_evidence.is_symlink():
        evidence = json.loads(build_evidence.read_text(encoding="utf-8"))
        game_plugin = GAME / "Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin"
        if hashlib.sha256(game_plugin.read_bytes()).hexdigest() != evidence["game_plugin_sha256"]:
            raise ValueError("Game plugin changed since version evidence was recorded")
        environment["FOOTBALL_ASSISTANT_GAME_BUILD"] = evidence["game_plugin_build"]
    latest = PRIVATE / "launch.json"
    if latest.is_symlink() or (latest.exists() and latest.stat().st_nlink != 1):
        raise ValueError("Latest launch record is not a private regular file")
    if latest.exists():
        previous_attempt = Path(json.loads(latest.read_text(encoding="utf-8"))["attempt"])
        previous_log = PRIVATE / "BepInEx/LogOutput.log"
        archived_log = previous_attempt / "BepInEx.log"
        if previous_attempt.resolve().is_relative_to(PRIVATE / "logs") and previous_log.is_file() and not archived_log.exists():
            shutil.copyfile(previous_log, archived_log)
    attempt.mkdir(exist_ok=False)
    with (attempt / "game-launch.log").open("xb") as log:
        process = subprocess.Popen(command, cwd=PRIVATE, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    plugin = PRIVATE / "BepInEx/plugins/FootballAssistant.GameBridge.dll"
    launch_info = json.dumps({"pid": process.pid, "executable": str(executable), "attempt": str(attempt), "command": command, "plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest()}, indent=2) + "\n"
    (attempt / "launch.json").write_text(launch_info, encoding="utf-8")
    latest.write_text(launch_info, encoding="utf-8")
    print(f"Started one private game process (PID {process.pid}). No Steam settings were changed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Launch stopped: {error}") from None
