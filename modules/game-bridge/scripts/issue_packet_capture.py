#!/usr/bin/env python3
"""Issue one bounded packet arm/cancel for the already installed private observer."""
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
    parser.add_argument("--cancel", action="store_true", help="Cancel a pending one-shot; ready bytes are preserved")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    host = json.loads((PRIVATE / "diagnostics/host-session.json").read_text())
    if host["pid"] != args.pid or host.get("native_packet_abi_version") != 1 or not host["native_observer_enabled"]:
        raise ValueError("This PID has no reviewed packet-capable observer host")
    uuid.UUID(host["session_id"])
    executable = PRIVATE / "fm.app/Contents/MacOS/Football Manager 27"
    process = subprocess.run(["/bin/ps", "-p", str(args.pid), "-o", "comm="], capture_output=True, text=True, check=True).stdout.strip()
    if process != str(executable):
        raise ValueError("PID is not the private game executable")
    files = [(PRIVATE / "BepInEx/core/FootballAssistant.GameBridge.dll", host["managed_build_sha256"]),
             (PRIVATE / "native-observer/libfootballassistant_native_observer.dylib", host["observer_sha256"])]
    for path, expected in files:
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("A reviewed host/observer file changed since process startup")
    native = json.loads((PRIVATE / "diagnostics/native-observer.json").read_text())
    if native["session_id"] != host["session_id"] or native["snapshot"]["installed"] is not True:
        raise ValueError("The native observer is not installed for this host session")
    signal = {key: host[key] for key in ("pid", "session_id", "managed_build_sha256", "game_plugin_sha256", "observer_sha256")}
    signal.update(request_id=str(uuid.uuid4()), operation="cancel" if args.cancel else "arm", requested_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"apply": args.apply, **signal, "fixed_limits": {"min_keys": 1, "max_keys": 4096, "min_payload_bytes": 64, "max_payload_bytes": 65536, "max_total_bytes": 98304}}, indent=2))
    if not args.apply:
        return
    directory = PRIVATE / "control"
    if directory.is_symlink() or directory.resolve() != directory:
        raise ValueError("Control directory is not private")
    temporary = directory / ("packet-" + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(signal, stream)
    os.chmod(temporary, 0o600)
    temporary.replace(directory / "native-packet-request.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit("Packet signal refused (" + type(error).__name__ + ")") from None
