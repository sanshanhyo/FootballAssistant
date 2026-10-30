#!/usr/bin/env python3
"""Map actual private runtime read proofs to the existing catalog; default is dry-run."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[3]
READ_METHODS = {"GetSortedPlayerPanels", "get_Count", "get_Item", "get_visible", "get_worldBound", "get_childCount", "get_text", "get_version"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "Catalog redirects are disabled", headers, file_pointer)


def build_updates(sidecar: dict, catalog_dir: Path) -> tuple[dict, list[dict]]:
    source = sidecar["source"]
    header = json.loads((catalog_dir / "header.json").read_text(encoding="utf-8"))
    if source.get("synthetic") is not False or source.get("metadata_sha256") != header["metadata_sha256"] or source.get("game_build") != header["game_build"]:
        raise ValueError("Only real read proofs matching the registered game/metadata may update this catalog")
    uuid.UUID(source["session_id"])
    proofs = []
    for proof in sidecar.get("read_proofs", []):
        if proof.get("member_kind") not in ("method", "field"):
            continue
        name = proof["name"]
        exact_array_read = name == "GetValue" and proof.get("assembly") == "mscorlib.dll" and proof.get("member_token") == 100666585 and proof.get("type_token") == 33554754
        if proof["member_kind"] == "method" and name not in READ_METHODS and not exact_array_read:
            continue  # Observing an action/callback never makes it safe to invoke.
        if not proof.get("verification") or not proof.get("context"):
            continue
        # CoreCLR emits seven fractional digits; the macOS Python 3.9 parser
        # accepts six. Normalization is used only for the timezone/future check.
        stamp = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", proof["last_verified_at"].replace("Z", "+00:00"))
        timestamp = datetime.fromisoformat(stamp)
        if timestamp.tzinfo is None or (timestamp - datetime.now(timezone.utc)).total_seconds() > 60:
            raise ValueError("Invalid read-proof timestamp")
        proofs.append(proof)
    method_proofs = {(p["assembly"], p["member_token"], p["type_token"], p["name"]): p for p in proofs if p["member_kind"] == "method"}
    field_proofs = {(p["assembly"], p["type_token"], p["name"]): p for p in proofs if p["member_kind"] == "field"}
    selected: dict[str, dict] = {}
    with (catalog_dir / "canonical-member-index.ndjson").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            proof = None
            if row["member_kind"] == "method":
                proof = method_proofs.get((row["assembly"], row["member_token"], row["declaring_type_token"], row["name"]))
            elif row["member_kind"] == "field":
                proof = field_proofs.get((row["assembly"], row["declaring_type_token"], row["name"]))
            if proof is not None:
                selected[row["interface_id"]] = proof
    # Keep the full immutable metadata record and its existing safety/field-path policy.
    updates = []
    with (catalog_dir / "registration.ndjson").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            proof = selected.get(row["interface_id"])
            if proof is None:
                continue
            row = deepcopy(row)
            row.update(
                access_status="verified_readable",
                side_effect_policy="read_only",
                reason="Actual read succeeded in the explicitly recorded runtime object context; other instances are not implied",
                verification=proof["verification"] + " Context: " + proof["context"] + "; session: " + source["session_id"],
                last_verified_at=proof["last_verified_at"],
            )
            updates.append(row)
    header["session_id"] = source["session_id"]
    header["captured_at"] = source["captured_at"]
    return header, updates


def batches(header: dict, updates: list[dict]):
    pending = []
    for row in updates:
        candidate = dict(header, records=pending + [row], complete=True)
        if pending and (len(pending) >= 50 or len(json.dumps(candidate, ensure_ascii=False).encode()) > 100_000):
            yield dict(header, records=pending, complete=True)
            pending = []
        pending.append(row)
        if len(json.dumps(dict(header, records=pending, complete=True), ensure_ascii=False).encode()) > 100_000:
            raise ValueError("A catalog record exceeds the byte budget")
    if pending:
        yield dict(header, records=pending, complete=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, default=REPO / "local-game/fm27-runtime/diagnostics/runtime-inspection.json")
    parser.add_argument("--catalog-dir", type=Path, default=REPO / "local-data/interface-catalog/with-binary")
    parser.add_argument("--runtime-file", type=Path, default=REPO / "local-data/runtime.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    header, updates = build_updates(json.loads(args.sidecar.read_text(encoding="utf-8")), args.catalog_dir)
    print(json.dumps({"apply": args.apply, "catalog_id": header["catalog_id"], "actual_read_updates": len(updates), "interface_ids": [r["interface_id"] for r in updates]}, ensure_ascii=False))
    if not args.apply:
        return
    connection = json.loads(args.runtime_file.read_text(encoding="utf-8"))
    url = urllib.parse.urlsplit(connection["base_url"])
    if url.scheme != "http" or url.username or url.password or url.query or url.fragment or not ipaddress.ip_address(url.hostname).is_loopback:
        raise ValueError("Only literal loopback HTTP is allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for body in batches(header, updates):
        request = urllib.request.Request(connection["base_url"].rstrip("/") + "/v1/interfaces/catalog", data=json.dumps(body, ensure_ascii=False).encode(), headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=3) as response:
            result = json.load(response)
        print(json.dumps({"batch_count": len(body["records"]), "accepted": True, "registered_count": result.get("registered_count")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        raise SystemExit("Read-proof sync stopped (" + type(error).__name__ + ")") from None
