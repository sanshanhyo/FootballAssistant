#!/usr/bin/env python3
"""Register actual private registry snapshots; default dry-run never writes the backend."""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[3]
REGISTRIES = {"PropertyIdentifierSet", "ContextIdentifierSet", "ReferenceIdentifierSet"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "Registry redirects disabled", headers, file_pointer)


def prepare_batches(frame: dict):
    source = frame["source"]
    if source.get("synthetic") is not False:
        raise ValueError("Synthetic registry data cannot update the real registry catalog")
    uuid.UUID(source["session_id"])
    for snapshot in frame.get("registry_enumerations", []):
        name = snapshot["registry_id"]
        if name not in REGISTRIES:
            raise ValueError("Unexpected registry")
        uuid.UUID(snapshot["enumeration_id"])
        expected = snapshot["expected_count"]
        if expected is not None and (type(expected) is not int or not 0 <= expected <= 100_000):
            raise ValueError("Invalid expected count")
        entries = []
        ids = set()
        for row in snapshot["entries"]:
            if set(row) - {"id", "name", "owner", "display_name", "value_type"}:
                raise ValueError("Unexpected registry entry fields; metadata indexes are not business IDs")
            number = row["id"]
            if type(number) is not int or not 0 <= number <= 0xFFFFFFFF or number in ids:
                raise ValueError("Entries require unique actual uint32 IDs; zero is valid")
            ids.add(number)
            if any(row.get(key) is not None and not isinstance(row[key], str) for key in ["name", "owner", "display_name", "value_type"]):
                raise ValueError("Registry descriptors must be observed strings or null")
            entries.append({key: row.get(key) for key in ["id", "name", "owner", "display_name", "value_type"]})
        if expected is not None and len(entries) > expected:
            raise ValueError("More unique entries than the measured registry count")
        complete = snapshot.get("complete") is True
        if complete and (expected is None or len(entries) != expected or snapshot.get("status") != "complete"):
            raise ValueError("Local enumeration lacks consistent completion evidence")
        header = dict(source, registry_id=name, enumeration_id=snapshot["enumeration_id"], dictionary_version=snapshot["dictionary_version"], expected_count=expected)
        pending = []
        for entry in entries:
            body = dict(header, complete=False, entries=pending + [entry])
            if pending and (len(pending) >= 100 or len(json.dumps(body, ensure_ascii=False).encode()) > 100_000):
                yield dict(header, complete=False, entries=pending)
                pending = []
            pending.append(entry)
            if len(json.dumps(dict(header, complete=False, entries=pending), ensure_ascii=False).encode()) > 100_000:
                raise ValueError("A registry entry exceeds the body budget")
        if pending:
            yield dict(header, complete=False, entries=pending)
        if complete:
            # A distinct explicit last batch also establishes a real known-empty registry.
            yield dict(header, complete=True, entries=[])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, default=REPO / "local-game/fm27-runtime/diagnostics/registry-enumerations.json")
    parser.add_argument("--runtime-file", type=Path, default=REPO / "local-data/runtime.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Continuously relay newly copied entries and explicit completed epochs")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        raise ValueError("Polling interval must be between 1 and 60 seconds")
    delivered: dict[tuple, set[int]] = {}
    completed: set[tuple] = set()
    previous_summary = None
    acknowledged_file = None
    while True:
        try:
            stat = args.sidecar.stat()
            file_identity = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if args.watch and file_identity == acknowledged_file:
                time.sleep(args.interval)
                continue
            frame = json.loads(args.sidecar.read_text(encoding="utf-8"))
            bodies = list(prepare_batches(frame))
            summary = [{"registry_id": r["registry_id"], "observed_unique_local": len(r["entries"]), "expected_count": r["expected_count"], "local_complete": r["complete"], "status": r["status"]} for r in frame.get("registry_enumerations", [])]
            if summary != previous_summary or not args.watch:
                print(json.dumps({"apply": args.apply, "batches": len(bodies), "registries": summary}, ensure_ascii=False), flush=True)
                previous_summary = summary
            connection = None
            if args.apply:
                connection = json.loads(args.runtime_file.read_text(encoding="utf-8"))
                address = urllib.parse.urlsplit(connection["base_url"])
                if address.scheme != "http" or address.username or address.password or address.query or address.fragment or not ipaddress.ip_address(address.hostname).is_loopback:
                    raise ValueError("Only literal loopback HTTP is allowed")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            final = {}
            active = set()
            for body in bodies:
                key = (body["session_id"], body["registry_id"], body["enumeration_id"])
                active.add(key)
                acknowledged = delivered.setdefault(key, set())
                body["entries"] = [row for row in body["entries"] if row["id"] not in acknowledged]
                if body["complete"]:
                    if key in completed:
                        continue
                elif not body["entries"]:
                    continue
                if args.apply:
                    request = urllib.request.Request(connection["base_url"].rstrip("/") + "/v1/interfaces/registries/batches", data=json.dumps(body, ensure_ascii=False).encode(), headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"}, method="POST")
                    with opener.open(request, timeout=5) as response:
                        final[body["registry_id"]] = json.load(response)
                acknowledged.update(row["id"] for row in body["entries"])
                if body["complete"]:
                    completed.add(key)
            # Keep at most the current three registry epochs in memory. A
            # returning older epoch can safely replay its idempotent batches.
            delivered = {key: ids for key, ids in delivered.items() if key in active}
            completed.intersection_update(active)
            for name, result in final.items():
                print(json.dumps({"registry_id": name, "observed_unique_server": result["observed_unique_entries"], "expected_count": result["expected_count"], "server_complete": result["complete"], "field_values_known": result["field_values_known"]}, ensure_ascii=False), flush=True)
            # The producer replaces this file atomically only when an epoch's
            # progress changes. Skip parsing/serializing all 10,400 stable rows.
            acknowledged_file = file_identity
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            if not args.watch:
                raise
            print("Registry relay awaiting diagnostics/backend (" + type(error).__name__ + ").", flush=True)
        if not args.watch:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        raise SystemExit("Registry sync stopped (" + type(error).__name__ + ")") from None
