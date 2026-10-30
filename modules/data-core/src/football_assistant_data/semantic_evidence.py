"""Offline candidate evidence only; no football/entity inference or game access."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import uuid

MAX_JSON_BYTES = 1_048_576
MAX_CHANGES = 512
MAX_OUTPUT_BYTES = 2_097_152
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("nonfinite_json")


def _bounded_tree(value, depth=0, budget=None):
    if budget is None:
        budget = [100_000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 48:
        raise ValueError("json_structure_budget")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if value.bit_length() > 64:
            raise ValueError("integer_budget")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite_json")
    elif type(value) is str:
        if len(value.encode("utf-8")) > 65_536:
            raise ValueError("string_budget")
    elif type(value) is list:
        for item in value:
            _bounded_tree(item, depth + 1, budget)
    elif type(value) is dict:
        for key, item in value.items():
            _bounded_tree(key, depth + 1, budget)
            _bounded_tree(item, depth + 1, budget)
    else:
        raise ValueError("unsupported_json_type")


def _read_json(path: Path, limit=MAX_JSON_BYTES, *, max_nodes=100_000):
    if path.is_symlink() or not path.is_file():
        raise ValueError("input_not_regular_file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("json_byte_budget")
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_reject_constant)
    _bounded_tree(value, budget=[max_nodes])
    if type(value) is not dict:
        raise ValueError("expected_json_object")
    return value, hashlib.sha256(raw).hexdigest()


def _uuid(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError("noncanonical_uuid")


def _sha(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError("invalid_digest")


def _source(source):
    if type(source) is not dict or source.get("synthetic") is not False:
        raise ValueError("invalid_source")
    _uuid(source.get("session_id"))
    for field in ("metadata_sha256", "game_assembly_sha256"):
        _sha(source.get(field))
    if type(source.get("game_build")) is not str or not 1 <= len(source["game_build"]) <= 256:
        raise ValueError("invalid_game_build")


def _manifest(path):
    value, digest = _read_json(path, 65_536)
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("invalid_manifest_version")
    for field in ("packet_id", "session_id"):
        _uuid(value.get(field))
    _source(value.get("source"))
    for field in ("keys_file", "payload_file"):
        name = value.get(field)
        if type(name) is not str or not name or name in (".", "..") or any(c in name for c in "/\\\x00"):
            raise ValueError("invalid_packet_filename")
    return value, digest


def _registry(path):
    if path is None:
        return None, None
    # A full 16,384-row registry with five descriptor fields needs over
    # 180,000 key/value/container nodes. Keep this allowance registry-only.
    frame, digest = _read_json(path, max_nodes=200_000)
    _source(frame.get("source"))
    rows = frame.get("registry_enumerations")
    if type(rows) is not list or len(rows) > 128 or any(type(row) is not dict for row in rows):
        raise ValueError("invalid_registry_rows")
    matches = [row for row in rows if row.get("registry_id") == "PropertyIdentifierSet"]
    if len(matches) != 1:
        raise ValueError("one_property_registry_required")
    row = matches[0]
    if type(row.get("complete")) is not bool:
        raise ValueError("invalid_registry_completion")
    version = row.get("dictionary_version")
    if version is not None and (type(version) is not int or not -2147483648 <= version <= 2147483647):
        raise ValueError("invalid_registry_version")
    expected = row.get("expected_count")
    if expected is not None and (type(expected) is not int or not 0 <= expected <= 1_000_000):
        raise ValueError("invalid_registry_count")
    if row["complete"] and expected is None:
        raise ValueError("unknown_registry_count_cannot_be_complete")
    if type(row.get("enumeration_id")) is not str or not 1 <= len(row["enumeration_id"]) <= 256:
        raise ValueError("invalid_registry_epoch")
    entries = row.get("entries")
    if type(entries) is not list or len(entries) > 16_384 or any(type(entry) is not dict for entry in entries):
        raise ValueError("invalid_registry_entries")
    if expected is not None and len(entries) > expected:
        raise ValueError("registry_exceeds_expected_count")
    # decode_packet additionally validates unique uint32 IDs, names and completion.
    return frame, digest


def _load_decoder():
    """Import only checkout-owned files; never import code beside input manifests."""
    scripts = Path(__file__).resolve().parents[4] / "modules/game-bridge/scripts"
    modules = []
    for name in ("wire_decoder", "decode_native_packet"):
        spec = importlib.util.spec_from_file_location(name, scripts / (name + ".py"))
        if spec is None or spec.loader is None:
            raise ValueError("decoder_unavailable")
        module = importlib.util.module_from_spec(spec)
        if name == "wire_decoder":
            spec.loader.exec_module(module)
            modules.append(module)
        else:
            previous = sys.modules.get("wire_decoder")
            sys.modules["wire_decoder"] = modules[0]
            try:
                spec.loader.exec_module(module)
            finally:
                if previous is None:
                    sys.modules.pop("wire_decoder", None)
                else:
                    sys.modules["wire_decoder"] = previous
            return module
    raise ValueError("decoder_unavailable")


def _node_material(node):
    """Exclude byte offsets/registry labels, preserve prefix, order and duplicates."""
    value = node["value"]
    if node["tag"] == 10:
        value = [{"property_id": row["property_id"], "value": _node_material(row["value"])}
                 for row in value["properties"]]
    elif node["tag"] == 11:
        value = [_node_material(child) for child in value]
    return {"tag": node["tag"], "prefix": node["raw_prefix_byte"], "value": value}


def _flatten(node, path=()):
    yield path, node
    if node["tag"] == 10:
        occurrences = {}
        for row in node["value"]["properties"]:
            number = row["property_id"]
            occurrence = occurrences.get(number, 0)
            occurrences[number] = occurrence + 1
            yield from _flatten(row["value"], path + (f"property:{number}:{occurrence}",))
    elif node["tag"] == 11:
        for index, child in enumerate(node["value"]):
            yield from _flatten(child, path + (f"index:{index}",))


def _summary(node):
    if node is None:
        return {"observation": "not_observed"}
    return {"observation": "observed", "tag": node["tag"], "kind": node["kind"],
            "structural_sha256": _digest(_node_material(node))}


def _provenance(manifest, decoded, registry_sha):
    source = manifest["source"]
    return {"packet_id": decoded["packet_id"], "session_id": decoded["session_id"],
            "packet_manifest_sha256": decoded["packet_manifest_sha256"],
            "keys_sha256": manifest["keys_sha256"], "payload_sha256": decoded["payload_sha256"],
            "metadata_sha256": source["metadata_sha256"],
            "game_assembly_sha256": source["game_assembly_sha256"],
            "game_build_label_sha256": _digest(source["game_build"]),
            "game_plugin_sha256": decoded["game_plugin_sha256"],
            "managed_build_sha256": decoded["managed_build_sha256"],
            "observer_sha256": decoded["observer_sha256"],
            "registry_sidecar_sha256": registry_sha,
            "keys_count": decoded["keys_count"], "payload_bytes": decoded["payload_bytes"],
            "grammar_complete_for_payload": decoded["grammar_complete_for_payload"],
            "key_to_value_mapping_known": decoded["key_to_value_mapping_known"],
            "copy_integrity_verified": True, "live_origin_independently_verified": False}


def compare_manifests(a: Path, b: Path, return_a: Path | None = None,
                      registry_sidecar: Path | None = None, *, max_changes=128) -> dict:
    """Reverify raw files then report bounded candidates, never verified semantics.

    Run offline in one process. This is not a decoded-JSON ingestion interface.
    The optional return capture is user-declared ordering, not verified chronology.
    """
    if type(max_changes) is not int or not 1 <= max_changes <= MAX_CHANGES:
        raise ValueError("invalid_change_budget")
    registry, registry_sha = _registry(registry_sidecar)
    decoder = _load_decoder()
    captures = []
    for label, path in (("a", a), ("b", b), ("return_a", return_a)):
        if path is None:
            continue
        manifest, digest = _manifest(Path(path))
        decoded = decoder.decode_packet(Path(path), registry)
        if decoded["packet_manifest_sha256"] != digest:
            raise ValueError("manifest_changed_during_verification")
        captures.append((label, manifest, decoded))
    if len({row[2]["packet_id"] for row in captures}) != len(captures):
        raise ValueError("distinct_packet_ids_required")
    basis = ("session_id", "game_build", "metadata_sha256", "game_assembly_sha256")
    for _, manifest, _ in captures[1:]:
        first = captures[0][1]
        if any(manifest["source"][field] != first["source"][field] for field in basis) or any(
            manifest[field] != first[field] for field in ("game_plugin_sha256", "managed_build_sha256", "observer_sha256")
        ):
            raise ValueError("capture_session_or_build_mismatch")
    report = {"schema_version": 1, "status": "candidate_evidence_only", "business_semantics_complete": False,
              "entity_identity_known": False, "causality_established": False,
              "capture_order": "user_supplied_not_independently_verified",
              "channel_lifetime_mapping_known": False, "values_disclosed": False,
              "verification_scope": "local_copy_hash_length_and_pinned_decoder_only",
              "captures": {label: _provenance(manifest, decoded, registry_sha)
                           for label, manifest, decoded in captures},
              "candidate_changes": [], "candidate_change_count": 0, "truncated": False}
    if any(not row[2]["key_to_value_mapping_known"] for row in captures):
        report.update(status="not_comparable", reason="incomplete_grammar_or_key_value_count_mismatch")
        return report
    channels = []
    for _, _, decoded in captures:
        rows = decoded["channel_values"]
        if len({row["key"] for row in rows}) != len(rows):
            report.update(status="not_comparable", reason="duplicate_channel_keys")
            return report
        channels.append({row["key"]: row["typed_value"] for row in rows})
    def alignment(left, right, right_label):
        shared = left.keys() & right.keys()
        return {"shared_key_count": len(shared),
                "a_only_key_count": len(left.keys() - right.keys()),
                right_label + "_only_key_count": len(right.keys() - left.keys()),
                "scope": "shared_numeric_keys_only" if shared else "unpaired_presence_only"}

    report["channel_alignment"] = {
        "a_b": alignment(channels[0], channels[1], "b"),
        "channel_lifetime_mapping_known": False,
    }
    if len(channels) == 3:
        report["channel_alignment"]["a_return_a"] = alignment(channels[0], channels[2], "return_a")
        first, returned = captures[0][2], captures[2][2]
        payload_matches = first["payload_sha256"] == returned["payload_sha256"]
        keys_match = captures[0][1]["keys_sha256"] == captures[2][1]["keys_sha256"]
        report["return_payload_diagnostic"] = {
            "payload_sha256_matches_a": payload_matches,
            "keys_sha256_matches_a": keys_match,
            "repeated_payload_with_different_keys": payload_matches and not keys_match,
            "identity_join_established": False,
        }
    counts = {"shared_key_value_comparison": 0, "shared_key_path_presence_only": 0,
              "unpaired_channel_presence_only": 0}
    report["candidate_change_counts_by_scope"] = counts
    for key in sorted(channels[0].keys() | channels[1].keys(), key=int):
        maps = [dict(_flatten(channel[key])) if key in channel else {} for channel in channels]
        for path in sorted(maps[0].keys() | maps[1].keys()):
            before, after = _summary(maps[0].get(path)), _summary(maps[1].get(path))
            if before == after:
                continue
            if key not in channels[0] or key not in channels[1]:
                scope = "unpaired_channel_presence_only"
            elif path not in maps[0] or path not in maps[1]:
                scope = "shared_key_path_presence_only"
            else:
                scope = "shared_key_value_comparison"
            counts[scope] += 1
            report["candidate_change_count"] += 1
            if len(report["candidate_changes"]) >= max_changes:
                report["truncated"] = True
                continue
            change = {"classification": "candidate_not_confirmed", "channel_key": key,
                      "path": list(path), "a": before, "b": after,
                      "comparison_scope": scope,
                      "comparison_basis": ("observed_channel_presence_only" if scope ==
                                           "unpaired_channel_presence_only" else
                                           "same_numeric_channel_and_structural_path_only")}
            if len(maps) == 3:
                returned = _summary(maps[2].get(path))
                change["return_a"] = returned
                change["return_matches_a"] = (returned == before if returned["observation"] ==
                                               before["observation"] == "observed" else None)
            report["candidate_changes"].append(change)
    report["limits"] = {"max_changes": max_changes, "max_packet_payload_bytes": 65_536,
                        "max_keys_per_packet": 4096, "max_output_bytes": MAX_OUTPUT_BYTES}
    if len(_canonical(report)) > MAX_OUTPUT_BYTES:
        raise ValueError("report_byte_budget")
    return report
