#!/usr/bin/env python3
"""Issue one PID/session/build-bound native test checkpoint after fresh-menu confirmation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

REPO = Path(__file__).resolve().parents[3]
PRIVATE = REPO / "local-game/fm27-runtime"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--confirmed-fresh-main-menu", action="store_true", help="Operator has just received the media agent's fresh-menu/no-career confirmation for this PID")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.confirmed_fresh_main_menu:
        raise ValueError("Fresh main menu must be independently confirmed for this exact PID")
    host = json.loads((PRIVATE / "diagnostics/host-session.json").read_text(encoding="utf-8"))
    if host["pid"] != args.pid or not host["native_observer_enabled"]:
        raise ValueError("Wrong process or observer is disabled")
    uuid.UUID(host["session_id"])
    executable = PRIVATE / "fm.app/Contents/MacOS/Football Manager 27"
    process = subprocess.run(["/bin/ps", "-p", str(args.pid), "-o", "comm="], capture_output=True, text=True, check=True).stdout.strip()
    if process != str(executable):
        raise ValueError("PID is not the private executable")
    assembly = PRIVATE / "BepInEx/core/FootballAssistant.GameBridge.dll"
    if hashlib.sha256(assembly.read_bytes()).hexdigest() != host["managed_build_sha256"]:
        raise ValueError("Managed build changed since host startup")
    signal = {key: host[key] for key in ["pid", "session_id", "managed_build_sha256", "game_plugin_sha256"]}
    signal.update(checkpoint="fresh_main_menu_before_career", requested_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"apply": args.apply, **signal}, indent=2))
    if not args.apply:
        return
    directory = PRIVATE / "control"
    if directory.is_symlink() or directory.resolve() != directory:
        raise ValueError("Control directory is not private")
    directory.mkdir(exist_ok=True)
    temporary = directory / ("checkpoint-" + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(signal, stream)
    os.chmod(temporary, 0o600)
    temporary.replace(directory / "native-observer-checkpoint.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit("Native checkpoint refused (" + type(error).__name__ + ")") from None
