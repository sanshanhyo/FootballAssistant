#!/usr/bin/env python3
"""Bounded, game-independent FM27 wire subset decoder. Never invokes game code.

Grammar evidence is pinned to GameAssembly SHA 266d02a5...09dd7 and game_plugin
SHA 2e915b0f...65f431 in local-data/interface-catalog/native-channel-abi.
Unknown tags stop the complete decode; no length or business meaning is guessed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct

GAME_ASSEMBLY_SHA = "266d02a57471b44f381b7b647828c58fd394e8222c3083613324a93a9db09dd7"
GAME_PLUGIN_SHA = "2e915b0f264920ae1205b111f45d50e354ac0e7d0b6e136b99189c24b265f431"


class WireError(ValueError):
    def __init__(self, reason: str, offset: int, tag: int | None = None):
        self.reason, self.offset, self.tag = reason, offset, tag
        super().__init__(reason)


class Reader:
    def __init__(self, payload: bytes, *, max_bytes=1_048_576, max_values=16_384, max_depth=16, max_string_bytes=262_144):
        if len(payload) > max_bytes:
            raise WireError("payload_exceeds_decoder_byte_budget", 0)
        self.data = memoryview(payload)
        self.at = 0
        self.values = 0
        self.max_values = max_values
        self.max_depth = max_depth
        self.max_string_bytes = max_string_bytes

    def take(self, size: int):
        if size < 0 or size > len(self.data) - self.at:
            raise WireError("truncated_payload", self.at)
        result = self.data[self.at:self.at + size]
        self.at += size
        return result

    def number(self, fmt: str):
        result = struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]
        if isinstance(result, float) and not math.isfinite(result):
            raise WireError("nonfinite_number_not_projected_to_json", self.at - struct.calcsize(fmt))
        return result

    def count(self, width: str, minimum: int) -> int:
        count = self.number(width)
        if count > self.max_values - self.values:
            raise WireError("value_count_exceeds_shared_node_budget", self.at - struct.calcsize(width))
        if count * minimum > len(self.data) - self.at:
            raise WireError("count_exceeds_remaining_bytes", self.at - struct.calcsize(width))
        return count

    def typed_list(self, depth=0):
        if depth > self.max_depth:
            raise WireError("nested_value_depth_exceeds_budget", self.at)
        return [self.value(depth) for _ in range(self.count("<I", 2))]

    def value(self, depth: int):
        if depth > self.max_depth:
            raise WireError("nested_value_depth_exceeds_budget", self.at)
        if self.values >= self.max_values:
            raise WireError("value_count_exceeds_shared_node_budget", self.at)
        self.values += 1
        start = self.at
        prefix, tag = self.number("<B"), self.number("<B")
        fixed = {1: ("<i", "int32"), 21: ("<i", "int32_alias"), 2: ("<I", "uint32"),
                 5: ("<d", "float64"), 15: ("<q", "int64_decimal"), 17: ("<b", "int8"),
                 19: ("<b", "int8_alias"), 18: ("<h", "int16"), 20: ("<h", "int16_alias"),
                 24: ("<Q", "uint64_decimal"), 25: ("<f", "float32")}
        if tag == 0:
            kind, value = "null", None
        elif tag == 3:
            kind, value = "boolean", self.number("<B") != 0
        elif tag in fixed:
            fmt, kind = fixed[tag]
            value = self.number(fmt)
            if tag in (15, 24):
                value = str(value)  # Keep exact values through JSON consumers.
        elif tag in (14, 26):
            kind = "utf8_string" if tag == 14 else "utf8_string_alias"
            length = self.number("<I")
            if length > self.max_string_bytes:
                raise WireError("string_exceeds_decoder_byte_budget", self.at - 4, tag)
            raw = self.take(length)
            try:
                value = bytes(raw).decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise WireError("invalid_utf8_not_projected_as_text", self.at - length + error.start, tag) from None
        elif tag == 11:
            kind, value = "typed_list", self.typed_list(depth + 1)
        elif tag == 10:
            kind = "dynamic_reference_descriptor"
            count = self.count("<I", 6)
            value = {"properties": [{"property_id": self.number("<I"), "value": self.value(depth + 1)} for _ in range(count)],
                     "game_factory_invoked": False, "property_order_and_duplicates_preserved": True}
        elif tag == 32:
            kind = "GameDate_encoded"
            value = {"encoded_u32": self.number("<I"), "calendar_decoded": False, "game_factory_invoked": False}
        elif tag == 34:
            kind = "interop_reference_descriptor"
            count = self.count("<B", 8)
            value = {"null_id_list_sentinel": count == 0,
                     "pairs": [{"id": self.number("<I"), "value": self.number("<i")} for _ in range(count)],
                     "semantics": "opaque_identifier_pairs", "game_factory_invoked": False}
        elif tag == 13:
            kind = "UnityEngine.Color32"
            raw = self.number("<I")
            b0, b1, b2, b3 = raw & 255, (raw >> 8) & 255, (raw >> 16) & 255, (raw >> 24) & 255
            value = {"wire_u32": raw, "rgba": [b2, b1, b0, b3],
                     "packed_color32_u32": (raw & 0xFF00FF00) | (b0 << 16) | b2}
        elif tag == 16:
            kind = "SI.Core.SmallMessage_descriptor"
            ordering, local = self.number("<B"), self.number("<B") != 0
            length = self.number("<I")
            if length >= 0x80000000:
                raise WireError("ReadBytes_length_is_negative_int32", self.at - 4, tag)
            raw = self.take(length)
            value = {"m_byteOrdering": ordering, "m_isLocal": local, "declared_buffer_bytes": length,
                     "m_buffer_base64": base64.b64encode(raw).decode("ascii"), "buffer_semantics": "opaque",
                     "game_constructor_invoked": False}
        elif tag == 27:
            kind = "SI.Core.DateTime_encoded"
            value = {"Data1_i64_decimal": str(self.number("<q")), "calendar_decoded": False,
                     "game_constructor_invoked": False}
        else:
            raise WireError("unsupported_tag_no_cursor_guess", start + 1, tag)
        return {"wire_start": start, "wire_end": self.at, "raw_prefix_byte": prefix, "tag": tag, "kind": kind, "value": value}


def decode(payload: bytes, **budgets) -> dict:
    result = {"payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_bytes": len(payload),
              "decoder_game_assembly_sha256": GAME_ASSEMBLY_SHA, "decoder_game_plugin_sha256": GAME_PLUGIN_SHA,
              "complete_protocol": False, "business_semantics_complete": False, "game_methods_invoked": False,
              "prefix_byte_semantics_known": False, "key_to_value_mapping_known": False}
    reader = None
    try:
        reader = Reader(payload, **budgets)
        values = reader.typed_list()
        if reader.at != len(reader.data):
            raise WireError("unconsumed_trailing_bytes", reader.at)
        result.update(status="decoded_known_grammar", grammar_complete_for_payload=True,
                      bytes_consumed=reader.at, decoded_node_count=reader.values, values=values)
    except WireError as error:
        result.update(status="unsupported_or_incomplete", grammar_complete_for_payload=False,
                      bytes_consumed=reader.at if reader is not None else 0,
                      error={"reason": error.reason, "offset": error.offset, "tag": error.tag}, values=None)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True, help="Already copied private bytes, never a game pointer")
    parser.add_argument("--output", type=Path, help="New output file; existing files are not overwritten")
    args = parser.parse_args()
    with args.payload.open("rb") as stream:
        payload = stream.read(1_048_577)
    result = decode(payload)
    result["input_origin"] = "unverified_binary_file"  # Capture provenance belongs to the independent packet manifest.
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print(json.dumps({"status": result["status"], "grammar_complete_for_payload": result["grammar_complete_for_payload"], "output": str(args.output)}))
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
