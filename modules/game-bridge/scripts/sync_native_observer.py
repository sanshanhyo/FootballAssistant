#!/usr/bin/env python3
"""Relay pointer-free native header diagnostics; never loads a library or installs a hook."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[3]
PRIVATE = REPO / "local-game/fm27-runtime"
OBSERVER_SHA = "9848cdf11e5470d9d5d63a97aeb0323686fe96714f32d3cb7af498d0bcc0e73c"
LEGACY_OBSERVER_SHA = "39aebea4e1569fea801ac29a322199de1b7cc7be050dff5da55e447e6bd51182"
ANCHOR = "game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr"
COUNTERS = ("invocation_count", "enqueued_count", "drained_count", "overflow_dropped",
            "contention_dropped", "stopped_invocations", "in_flight", "queue_size", "queue_capacity")
INSTALL_FIELDS = ("abi_version", "struct_size", "result", "install_state", "checks", "prepare_result", "commit_result")
SOURCE_FIELDS = ("adapter_id", "session_id", "game_build", "bundle_version", "metadata_sha256", "game_assembly_sha256")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "Native diagnostic redirects disabled", headers, file_pointer)


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("Private diagnostic exceeds byte budget")
    return json.loads(data)


def u64(value) -> str | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("Unsigned native counter is not an exact uint64 integer")
    return str(value)


def project(frame: dict, source: dict, host: dict, observer_sha: str) -> dict:
    """Use native capture time, exact decimal counters, and an explicit field allowlist."""
    if frame.get("synthetic") is not False or source.get("synthetic") is not False:
        raise ValueError("Synthetic data cannot be relayed as a game observation")
    session = frame["session_id"]
    uuid.UUID(session)
    if session != source["session_id"] or session != host["session_id"]:
        raise ValueError("Native, registry, and host sessions differ")
    if observer_sha != OBSERVER_SHA:
        raise ValueError("Observer library differs from the reviewed header-only release")
    if host.get("observer_sha256") is not None and host["observer_sha256"] != observer_sha:
        raise ValueError("Host and relay observer builds differ")
    if host.get("observer_sha256") is None and observer_sha != LEGACY_OBSERVER_SHA:
        raise ValueError("A packet-capable relay requires its host's explicit observer digest")
    # CoreCLR writes seven fractional digits; macOS's system Python 3.9 only
    # parses six. Preserve the original sample/capture string in the report.
    timestamp = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", frame["captured_at"].replace("Z", "+00:00"))
    captured = datetime.fromisoformat(timestamp)
    if captured.tzinfo is None:
        raise ValueError("Native capture needs a timezone")
    snapshot = frame["snapshot"]
    if snapshot["abi_version"] != 1 or snapshot.get("payload_data_read") is not False:
        raise ValueError("This relay only accepts the reviewed header-only ABI")
    records = snapshot["records"]
    if not isinstance(records, list) or len(records) > 256:
        raise ValueError("Native poll record budget differs from the reviewed ABI")
    projected = []
    ages = []
    for row in records:
        flags = row["flags"]
        if type(flags) is not int or not 0 <= flags <= 0xFFFFFFFF:
            raise ValueError("Invalid native flags")
        if bool(flags & 1) != (row.get("keys_count") is not None) or bool(flags & 2) != (row.get("payload_count") is not None):
            raise ValueError("Native header known flags disagree with nullable counts")
        age = row.get("age_seconds")
        if age is not None:
            if type(age) not in (float, int) or not math.isfinite(age) or age < 0:
                raise ValueError("Invalid native header age")
            ages.append(age)
        projected.append({"call_sequence": u64(row["call_sequence"]),
                          "native_thread_id": None if flags & 32 else u64(row.get("native_thread_id")),
                          "keys_count": u64(row.get("keys_count")), "payload_count": u64(row.get("payload_count")),
                          "flags": flags, "age_seconds": age})
    if len({row["call_sequence"] for row in projected}) != len(projected):
        raise ValueError("Duplicate native header sequence")
    installed = snapshot["installed"]
    enabled = snapshot["capture_enabled"]
    if type(installed) is not bool or type(enabled) is not bool:
        raise ValueError("Unknown native installation state")
    report = snapshot.get("install_report")
    status = "available" if installed else "error" if report is not None else "not_probed"
    body = {key: source.get(key) for key in SOURCE_FIELDS}
    body.update(adapter_id="footballassistant.native-observer", captured_at=frame["captured_at"], synthetic=False,
                game_plugin_sha256=host["game_plugin_sha256"], observer_sha256=observer_sha,
                sample_id=frame["captured_at"], status=status, abi_version=1,
                reason="Passive bounded native dispatch header observation; payload bytes and business values are not read.",
                target={"kind": "dispatch_thunk", "anchor_export": ANCHOR, "anchor_offset_bytes": 12, "dispatch_rva": "0x16c24"},
                installed=installed, capture_enabled=enabled, install_state=snapshot["install_state"],
                records_total=str(len(records)), latest_header_age_seconds=min(ages) if ages else None,
                records=projected[-16:], install_report=None if report is None else {key: report.get(key) for key in INSTALL_FIELDS},
                completeness="bounded_header_observation_only", payload_data_read=False, field_values_known=False, complete=False)
    body.update({key: u64(snapshot.get(key)) for key in COUNTERS})
    return body


def post(body: dict, runtime_file: Path) -> dict:
    connection = read_json(runtime_file)
    address = urllib.parse.urlsplit(connection["base_url"])
    if address.scheme != "http" or address.username or address.password or address.query or address.fragment or not ipaddress.ip_address(address.hostname).is_loopback:
        raise ValueError("Only literal loopback HTTP is allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 100_000:
        raise ValueError("Native report exceeds request byte budget")
    request = urllib.request.Request(connection["base_url"].rstrip("/") + "/v1/interfaces/native-observers", data=encoded,
                                    headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"}, method="POST")
    with opener.open(request, timeout=5) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=PRIVATE)
    parser.add_argument("--runtime-file", type=Path, default=REPO / "local-data/runtime.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Poll existing sidecars continuously; no game operation is performed")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        raise ValueError("Polling interval must be between 1 and 60 seconds")
    observer = args.private_root / "native-observer/libfootballassistant_native_observer.dylib"
    observer_sha = hashlib.sha256(observer.read_bytes()).hexdigest()
    last_sample = None
    previous_state = None
    posts = 0
    while True:
        try:
            host = read_json(args.private_root / "diagnostics/host-session.json")
            frame = read_json(args.private_root / "diagnostics/native-observer.json")
            source = read_json(args.private_root / "diagnostics/runtime-inspection.json")["source"]
            body = project(frame, source, host, observer_sha)
            identity = (body["session_id"], body["sample_id"])
            if identity != last_sample:
                if args.apply:
                    post(body, args.runtime_file)
                last_sample = identity
                posts += 1
                state = (body["session_id"], body["status"], body["installed"], body["capture_enabled"])
                if not args.watch or state != previous_state or posts % 60 == 0:
                    print(json.dumps({"apply": args.apply, "status": body["status"], "installed": body["installed"],
                                      "invocation_count": body["invocation_count"], "records_total": body["records_total"],
                                      "records_included": len(body["records"]), "payload_data_read": False}), flush=True)
                previous_state = state
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
            if not args.watch:
                raise
            print("Native relay awaiting diagnostics/backend (" + type(error).__name__ + ").", flush=True)
        if not args.watch:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
        raise SystemExit("Native relay stopped (" + type(error).__name__ + ")") from None
