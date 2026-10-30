import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("native_relay", Path(__file__).parents[1] / "scripts/sync_native_observer.py")
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class NativeRelayTests(unittest.TestCase):
    def fixture(self):
        session = "c08667c0-c124-458b-b04d-a065f31523d6"
        source = {"adapter_id": "registry-inspector", "session_id": session, "game_build": "fixture",
                  "bundle_version": "fixture", "metadata_sha256": "a" * 64,
                  "game_assembly_sha256": "b" * 64, "synthetic": False}
        host = {"session_id": session, "game_plugin_sha256": "c" * 64, "observer_sha256": relay.OBSERVER_SHA}
        snapshot = {"abi_version": 1, "installed": True, "capture_enabled": True, "install_state": 3,
                    "payload_data_read": False, "records": [], "install_report": None}
        snapshot.update({name: 0 for name in relay.COUNTERS})
        frame = {"session_id": session, "captured_at": "2026-10-30T07:40:00+00:00", "synthetic": False, "snapshot": snapshot}
        return frame, source, host

    def convert(self, frame, source, host):
        return relay.project(frame, source, host, relay.OBSERVER_SHA)

    def test_uint64_precision_and_pointer_redaction(self):
        frame, source, host = self.fixture()
        frame["snapshot"]["invocation_count"] = 18446744073709551615
        frame["snapshot"]["install_report"] = {"abi_version": 1, "target_address": "secret-pointer", "original_address": "secret-pointer"}
        body = self.convert(frame, source, host)
        self.assertEqual(body["invocation_count"], "18446744073709551615")
        self.assertNotIn("target_address", body["install_report"])
        self.assertNotIn("original_address", body["install_report"])

    def test_projection_retains_actual_count_and_latest_age(self):
        frame, source, host = self.fixture()
        frame["snapshot"]["records"] = [dict(call_sequence=n, native_thread_id=1, keys_count=0, payload_count=0,
                                                flags=3, age_seconds=20 - n) for n in range(20)]
        body = self.convert(frame, source, host)
        self.assertEqual(body["records_total"], "20")
        self.assertEqual(len(body["records"]), 16)
        self.assertEqual(body["records"][0]["call_sequence"], "4")
        self.assertEqual(body["latest_header_age_seconds"], 1)

    def test_unknown_header_is_not_zero(self):
        frame, source, host = self.fixture()
        frame["snapshot"]["records"] = [dict(call_sequence=1, native_thread_id=0, keys_count=None, payload_count=None, flags=32, age_seconds=None)]
        body = self.convert(frame, source, host)
        self.assertIsNone(body["records"][0]["native_thread_id"])
        self.assertIsNone(body["records"][0]["keys_count"])
        self.assertIsNone(body["latest_header_age_seconds"])

    def test_session_mismatch_refused(self):
        frame, source, host = self.fixture()
        host["session_id"] = "other"
        with self.assertRaises(ValueError):
            self.convert(frame, source, host)

    def test_observer_build_mismatch_refused(self):
        frame, source, host = self.fixture()
        host["observer_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.convert(frame, source, host)

    def test_bad_integer_or_flag_refused(self):
        for value in [True, -1, 18446744073709551616, 9007199254740992.0]:
            with self.assertRaises(ValueError):
                relay.u64(value)
        frame, source, host = self.fixture()
        frame["snapshot"]["records"] = [dict(call_sequence=1, native_thread_id=1, keys_count=0, payload_count=None, flags=0)]
        with self.assertRaises(ValueError):
            self.convert(frame, source, host)

    def test_empty_poll_has_no_new_callback_age_or_value_claim(self):
        body = self.convert(*self.fixture())
        self.assertEqual(body["records_total"], "0")
        self.assertIsNone(body["latest_header_age_seconds"])
        self.assertFalse(body["complete"])
        self.assertFalse(body["field_values_known"])

    def test_coreclr_timestamp_kept_verbatim(self):
        frame, source, host = self.fixture()
        frame["captured_at"] = "2026-10-30T07:40:00.1234567+00:00"
        body = self.convert(frame, source, host)
        self.assertEqual(body["captured_at"], frame["captured_at"])
        self.assertEqual(body["sample_id"], frame["captured_at"])


if __name__ == "__main__":
    unittest.main()
