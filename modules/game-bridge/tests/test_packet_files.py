import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


scripts = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location("decode_native_packet", scripts / "decode_native_packet.py")
packets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packets)


class PacketFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.manifest_path = self.directory / "packet.json"
        self.source = {"session_id": "c08667c0-c124-458b-b04d-a065f31523d6", "synthetic": False,
                       "game_build": "unit-test-fixture", "metadata_sha256": packets.METADATA_SHA,
                       "game_assembly_sha256": packets.GAME_ASSEMBLY_SHA}
        keys = struct.pack("<QQ", 0, 18446744073709551615)
        payload = struct.pack("<I", 1) + bytes([0, 10]) + struct.pack("<II", 1, 80) + bytes([0, 1]) + struct.pack("<i", -42)
        (self.directory / "keys.bin").write_bytes(keys)
        (self.directory / "payload.bin").write_bytes(payload)
        self.manifest = {"schema_version": 1, "synthetic": False, "complete_copy": True,
                         "packet_id": "a77edb8f-2dcf-4561-8c36-e1e2a9e49d61", "session_id": self.source["session_id"],
                         "source": self.source, "game_plugin_sha256": packets.GAME_PLUGIN_SHA,
                         "managed_build_sha256": "a" * 64, "observer_sha256": "b" * 64,
                         "keys_count": "2", "payload_bytes": str(len(payload)), "keys_file": "keys.bin", "payload_file": "payload.bin",
                         "keys_sha256": hashlib.sha256(keys).hexdigest(), "payload_sha256": hashlib.sha256(payload).hexdigest()}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def registry(self):
        return {"source": self.source.copy(), "registry_enumerations": [{"registry_id": "PropertyIdentifierSet", "enumeration_id": "fixture",
                "dictionary_version": 1, "expected_count": 1, "complete": True, "status": "complete", "entries": [{"id": 80, "name": "FixtureProperty"}]}]}

    def test_copy_hash_size_provenance_and_property_name_join(self):
        result = packets.decode_packet(self.manifest_path, self.registry())
        self.assertEqual(result["keys"], ["0", "18446744073709551615"])
        self.assertFalse(result["key_to_value_mapping_known"])
        prop = result["values"][0]["value"]["properties"][0]
        self.assertEqual(prop["property_name"], "FixtureProperty")
        self.assertEqual(prop["value"]["value"], -42)

    def test_same_count_allows_only_proven_position_mapping(self):
        keys = struct.pack("<Q", 18446744073709551615)
        (self.directory / "keys.bin").write_bytes(keys)
        self.manifest.update(keys_count="1", keys_sha256=hashlib.sha256(keys).hexdigest()); self.save()
        result = packets.decode_packet(self.manifest_path)
        self.assertTrue(result["key_to_value_mapping_known"])
        self.assertEqual(result["key_to_value_mapping_basis"], "managed_consumer_verified")
        self.assertEqual(result["channel_values"][0]["key"], "18446744073709551615")
        self.assertIsNone(result["channel_values"][0]["property_name"])
        self.assertFalse(result["channel_values"][0]["entity_identity_known"])

    def test_modified_bytes_fail_hash_before_decode(self):
        path = self.directory / "payload.bin"
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        with self.assertRaises(ValueError):
            packets.decode_packet(self.manifest_path)

    def test_incomplete_or_unknown_provenance_refused(self):
        for key, value in [("complete_copy", False), ("synthetic", True), ("game_plugin_sha256", "0" * 64)]:
            old = self.manifest[key]; self.manifest[key] = value; self.save()
            with self.assertRaises(ValueError):
                packets.decode_packet(self.manifest_path)
            self.manifest[key] = old

    def test_missing_full_bytes_or_over_budget_refused(self):
        for key, value in [("keys_count", "3"), ("payload_bytes", "65537"), ("keys_count", "4097"), ("keys_count", 2)]:
            old = self.manifest[key]; self.manifest[key] = value; self.save()
            with self.assertRaises(ValueError):
                packets.decode_packet(self.manifest_path)
            self.manifest[key] = old

    def test_path_escape_or_symlink_refused(self):
        self.manifest["payload_file"] = "../payload.bin"; self.save()
        with self.assertRaises(ValueError):
            packets.decode_packet(self.manifest_path)
        (self.directory / "link.bin").symlink_to(self.directory / "payload.bin")
        self.manifest["payload_file"] = "link.bin"; self.save()
        with self.assertRaises(ValueError):
            packets.decode_packet(self.manifest_path)

    def test_different_registry_session_or_false_completion_refused(self):
        registry = self.registry(); registry["source"]["session_id"] = "other"
        with self.assertRaises(ValueError):
            packets.decode_packet(self.manifest_path, registry)
        registry = self.registry(); registry["registry_enumerations"][0]["expected_count"] = 2
        with self.assertRaises(ValueError):
            packets.decode_packet(self.manifest_path, registry)


if __name__ == "__main__":
    unittest.main()
