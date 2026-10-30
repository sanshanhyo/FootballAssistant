#!/usr/bin/env python3
"""Verify copied packet files and decode outside FM27; no process access or game calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import uuid

from wire_decoder import decode, GAME_ASSEMBLY_SHA, GAME_PLUGIN_SHA

METADATA_SHA = "ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d"


def exact_u64(value) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value) or int(value) > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("Packet count is not an exact uint64 decimal string")
    return int(value)


def copied_bytes(directory: Path, name, count: int, expected_sha: str) -> bytes:
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Packet file must be a direct child of its manifest directory")
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory.resolve() or not path.is_file():
        raise ValueError("Packet file is not an independent local file")
    if path.stat().st_size != count:
        raise ValueError("Copied packet length disagrees with its complete count")
    data = path.read_bytes()
    if len(data) != count or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("Copied packet hash/length mismatch")
    return data


def property_names(frame: dict, source: dict) -> tuple[dict[int, str | None], dict | None]:
    registry_source = frame["source"]
    if registry_source.get("synthetic") is not False:
        raise ValueError("A synthetic registry cannot label a real packet")
    for field in ("session_id", "metadata_sha256", "game_assembly_sha256", "game_build"):
        if registry_source.get(field) != source.get(field):
            raise ValueError("Packet and property registry provenance differ")
    matching = [r for r in frame["registry_enumerations"] if r["registry_id"] == "PropertyIdentifierSet"]
    if len(matching) != 1:
        raise ValueError("One actual property registry epoch is required")
    registry = matching[0]
    rows = registry["entries"]
    names = {}
    for row in rows:
        number, name = row["id"], row.get("name")
        if type(number) is not int or not 0 <= number <= 0xFFFFFFFF or number in names or (name is not None and not isinstance(name, str)):
            raise ValueError("Property registry IDs/names are inconsistent")
        names[number] = name
    if registry["complete"] and (registry.get("status") != "complete" or len(rows) != registry["expected_count"]):
        raise ValueError("Property registry completion lacks unique entry evidence")
    return names, {"enumeration_id": registry["enumeration_id"], "dictionary_version": registry["dictionary_version"],
                   "expected_count": registry["expected_count"], "observed_unique_entries": len(rows),
                   "complete": registry["complete"], "source": registry_source}


def annotate(values: list[dict], names: dict[int, str | None]) -> None:
    for node in values:
        if node["tag"] == 10:
            for row in node["value"]["properties"]:
                row["property_name"] = names.get(row["property_id"])
                row["property_name_observed"] = row["property_id"] in names and names[row["property_id"]] is not None
                annotate([row["value"]], names)
        elif node["tag"] == 11:
            annotate(node["value"], names)


def decode_packet(manifest_path: Path, registry_frame: dict | None = None) -> dict:
    if manifest_path.is_symlink():
        raise ValueError("Packet manifest must not be a symbolic link")
    with manifest_path.open("rb") as stream:
        encoded = stream.read(65_537)
    if len(encoded) > 65_536:
        raise ValueError("Packet manifest exceeds byte budget")
    manifest = json.loads(encoded)
    if manifest.get("schema_version") != 1 or manifest.get("synthetic") is not False or manifest.get("complete_copy") is not True:
        raise ValueError("A real complete copied packet manifest is required")
    uuid.UUID(manifest["packet_id"])
    uuid.UUID(manifest["session_id"])
    source = manifest["source"]
    if source.get("synthetic") is not False or source.get("session_id") != manifest["session_id"]:
        raise ValueError("Packet source session is inconsistent")
    if source.get("metadata_sha256") != METADATA_SHA or source.get("game_assembly_sha256") != GAME_ASSEMBLY_SHA or manifest.get("game_plugin_sha256") != GAME_PLUGIN_SHA:
        raise ValueError("Packet bytes are from a different game build than this decoder")
    for name in ("managed_build_sha256", "observer_sha256", "keys_sha256", "payload_sha256"):
        if not isinstance(manifest.get(name), str) or not re.fullmatch(r"[0-9a-f]{64}", manifest[name]):
            raise ValueError("Packet build/file digest is malformed")
    keys_count, payload_count = exact_u64(manifest["keys_count"]), exact_u64(manifest["payload_bytes"])
    if keys_count > 4096 or payload_count > 65_536:
        raise ValueError("Packet exceeds the first live capture resource limits")
    directory = manifest_path.parent
    keys_data = copied_bytes(directory, manifest["keys_file"], keys_count * 8, manifest["keys_sha256"])
    payload = copied_bytes(directory, manifest["payload_file"], payload_count, manifest["payload_sha256"])
    result = decode(payload)
    result.update(input_origin="verified_private_packet_files", packet_id=manifest["packet_id"], session_id=manifest["session_id"],
                  complete_copy=True, source=source, game_plugin_sha256=manifest["game_plugin_sha256"],
                  managed_build_sha256=manifest["managed_build_sha256"], observer_sha256=manifest["observer_sha256"],
                  keys=[str(row[0]) for row in struct.iter_unpack("<Q", keys_data)], keys_count=keys_count,
                  key_units="uint64_elements", key_to_value_mapping_known=False,
                  packet_manifest_sha256=hashlib.sha256(encoded).hexdigest(), property_registry=None)
    if registry_frame is not None:
        names, registry = property_names(registry_frame, source)
        result["property_registry"] = registry
        if result["grammar_complete_for_payload"]:
            annotate(result["values"], names)
    # The pinned OnChannelDataChanged consumer uses the same i for keys[i]
    # and List<TypedValue>.get_Item(i). This proves position only, not a field
    # name, page/entity identity, or the lifetime of a channel mapping table.
    if result["grammar_complete_for_payload"] and len(result["values"]) == keys_count:
        result.update(key_to_value_mapping_known=True, key_to_value_mapping_basis="managed_consumer_verified",
                      channel_values=[{"key": key, "typed_value": value, "property_name": None, "entity_identity_known": False}
                                      for key, value in zip(result["keys"], result["values"])])
    else:
        result.update(channel_values=None, key_to_value_mapping_basis="not_established",
                      key_value_count_matches=None if not result["grammar_complete_for_payload"] else len(result["values"]) == keys_count)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registry-sidecar", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New output file; no existing result is overwritten")
    args = parser.parse_args()
    registry = None if args.registry_sidecar is None else json.loads(args.registry_sidecar.read_text(encoding="utf-8"))
    result = decode_packet(args.manifest, registry)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps({"packet_id": result["packet_id"], "status": result["status"], "keys_count": result["keys_count"],
                      "payload_bytes": result["payload_bytes"], "grammar_complete_for_payload": result["grammar_complete_for_payload"],
                      "business_semantics_complete": False, "output": str(args.output)}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("Native packet decode refused (" + type(error).__name__ + ")") from None
