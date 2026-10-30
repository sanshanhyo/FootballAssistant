import importlib.util
from pathlib import Path
import struct
import unittest


spec = importlib.util.spec_from_file_location("wire_decoder", Path(__file__).parents[1] / "scripts/wire_decoder.py")
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


def value(tag, raw=b"", prefix=0):
    return bytes([prefix, tag]) + raw


def values(*items):
    return struct.pack("<I", len(items)) + b"".join(items)


class WireDecoderTests(unittest.TestCase):
    def decoded(self, payload, **budgets):
        result = wire.decode(payload, **budgets)
        self.assertTrue(result["grammar_complete_for_payload"], result)
        self.assertEqual(result["bytes_consumed"], len(payload))
        self.assertFalse(result["game_methods_invoked"])
        return result["values"]

    def rejected(self, payload, reason=None, **budgets):
        result = wire.decode(payload, **budgets)
        self.assertFalse(result["grammar_complete_for_payload"])
        self.assertIsNone(result["values"])
        if reason:
            self.assertEqual(result["error"]["reason"], reason)
        return result

    def test_empty_and_exact_integer_widths(self):
        self.assertEqual(self.decoded(values()), [])
        row = self.decoded(values(value(1, struct.pack("<i", -2147483648), 7), value(2, struct.pack("<I", 4294967295))))
        self.assertEqual([x["value"] for x in row], [-2147483648, 4294967295])
        self.assertEqual(row[0]["raw_prefix_byte"], 7)
        self.assertEqual((row[0]["wire_start"], row[0]["wire_end"]), (4, 10))

    def test_uint64_int64_remain_decimal_strings(self):
        rows = self.decoded(values(value(24, struct.pack("<Q", 18446744073709551615)), value(15, struct.pack("<q", -9223372036854775808))))
        self.assertEqual([x["value"] for x in rows], ["18446744073709551615", "-9223372036854775808"])

    def test_utf8_uses_u32_byte_length(self):
        text = "曼联".encode()
        row = self.decoded(values(value(14, struct.pack("<I", len(text)) + text)))[0]
        self.assertEqual(row["value"], "曼联")
        self.rejected(values(value(14, struct.pack("<I", 99) + b"x")), "truncated_payload")

    def test_nonfinite_and_invalid_utf8_fail_without_json_fabrication(self):
        self.rejected(values(value(5, struct.pack("<d", float("nan")))), "nonfinite_number_not_projected_to_json")
        self.rejected(values(value(26, struct.pack("<I", 1) + b"\xff")), "invalid_utf8_not_projected_as_text")

    def test_dynamic_properties_keep_order_duplicates_and_opaque_date(self):
        date = value(32, struct.pack("<I", 0x07EA1AC2))
        dynamic = value(10, struct.pack("<I", 2) + struct.pack("<I", 80) + date + struct.pack("<I", 80) + value(0))
        descriptor = self.decoded(values(dynamic))[0]["value"]
        self.assertEqual([p["property_id"] for p in descriptor["properties"]], [80, 80])
        date_value = descriptor["properties"][0]["value"]["value"]
        self.assertEqual(date_value["encoded_u32"], 0x07EA1AC2)
        self.assertFalse(date_value["calendar_decoded"])
        self.assertFalse(descriptor["game_factory_invoked"])

    def test_interop_pairs_are_opaque_and_zero_is_null_list_sentinel(self):
        rows = self.decoded(values(value(34, bytes([2]) + struct.pack("<IiIi", 7, -3, 900, 123)), value(34, b"\0")))
        self.assertEqual(rows[0]["value"]["pairs"], [{"id": 7, "value": -3}, {"id": 900, "value": 123}])
        self.assertTrue(rows[1]["value"]["null_id_list_sentinel"])
        self.assertEqual(rows[0]["value"]["semantics"], "opaque_identifier_pairs")

    def test_nested_list_and_boolean(self):
        result = self.decoded(values(value(11, values(value(3, b"\x02"), value(18, struct.pack("<h", -17))))))
        self.assertEqual([x["value"] for x in result[0]["value"]], [True, -17])

    def test_unknown_tag_stops_whole_decode(self):
        for tag in (4, 6, 255):
            result = self.rejected(values(value(0), value(tag) + b"plausible trailing bytes"), "unsupported_tag_no_cursor_guess")
            self.assertEqual(result["error"]["tag"], tag)
            self.assertEqual(result["error"]["offset"], 7)

    def test_color32_actual_channel_order(self):
        row = self.decoded(values(value(13, bytes([0x11, 0x22, 0x33, 0x44]))))[0]
        self.assertEqual(row["value"]["rgba"], [0x33, 0x22, 0x11, 0x44])
        self.assertEqual(row["value"]["packed_color32_u32"], 0x44112233)

    def test_small_message_requires_full_declared_buffer(self):
        row = self.decoded(values(value(16, bytes([7, 2]) + struct.pack("<I", 3) + b"abc")))[0]
        self.assertEqual(row["value"]["m_byteOrdering"], 7)
        self.assertTrue(row["value"]["m_isLocal"])
        self.assertEqual(row["value"]["m_buffer_base64"], "YWJj")
        # BinaryReader.ReadBytes can return short; this complete packet decoder
        # deliberately rejects it rather than accepting a truncated message.
        self.rejected(values(value(16, bytes([0, 0]) + struct.pack("<I", 3) + b"a")), "truncated_payload")
        self.rejected(values(value(16, bytes([0, 0]) + struct.pack("<I", 0x80000000))), "ReadBytes_length_is_negative_int32")

    def test_si_datetime_retains_data1_without_epoch_guess(self):
        row = self.decoded(values(value(27, struct.pack("<q", -9223372036854775808))))[0]
        self.assertEqual(row["value"]["Data1_i64_decimal"], "-9223372036854775808")
        self.assertFalse(row["value"]["calendar_decoded"])

    def test_trailing_bytes_and_truncated_extensions_refused(self):
        self.rejected(values(value(0)) + b"\0", "unconsumed_trailing_bytes")
        for payload in (values(value(32, b"\0")), values(value(34, b"\xff")), values(value(10, struct.pack("<I", 999)))):
            self.rejected(payload)

    def test_global_node_depth_string_and_input_budgets(self):
        nested = values(value(11, values(value(11, values(value(0))))))
        self.rejected(nested, "nested_value_depth_exceeds_budget", max_depth=1)
        # Both sibling nested lists share one node budget, preventing the
        # multiplicative per-list allowance of the early research prototype.
        siblings = values(value(11, values(value(0), value(0))), value(11, values(value(0), value(0))))
        self.rejected(siblings, "value_count_exceeds_shared_node_budget", max_values=5)
        self.rejected(values(value(14, struct.pack("<I", 3) + b"abc")), "string_exceeds_decoder_byte_budget", max_string_bytes=2)
        self.rejected(values(value(0)), "payload_exceeds_decoder_byte_budget", max_bytes=4)


if __name__ == "__main__":
    unittest.main()
