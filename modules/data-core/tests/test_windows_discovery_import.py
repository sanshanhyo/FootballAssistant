"""Synthetic manual-import API tests. No FM/process/native/network calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings
from test_windows_discovery_projection import fixture

BASE = "/v1/reader/windows-discovery"
AUTH = {"Authorization": "Bearer synthetic-test-token"}


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(Settings(data_dir=root, runtime_file=root / "runtime.json", token="synthetic-test-token",
                                       max_request_bytes=4096), enable_agent=False)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.__enter__()
        source, capture = fixture()
        self.payload = {"capture": capture, "expected_source": source}
    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()
    def post(self, value=None):
        return self.client.post(BASE + "/import", headers=AUTH, json=self.payload if value is None else value)
    def snapshot(self):
        return self.client.get(BASE, headers=AUTH).json()
    def test_success_provenance_isolation_and_delete(self):
        before = {p:self.client.get(p, headers=AUTH).json() for p in
                  ("/v1/reader/snapshot", "/v1/reader/business/snapshot", "/v1/reader/profile")}
        result = self.post()
        self.assertEqual(result.status_code, 200, result.text)
        value = result.json()
        self.assertEqual(value["status"], "manual_import_snapshot")
        self.assertIsNotNone(value["imported_at"])
        projection = value["projection"]
        self.assertEqual(projection["fields"], {"displayed_position":"TEST-POSITION"})
        self.assertFalse(projection["page_identity_verified"])
        self.assertFalse(projection["business_identity_known"])
        self.assertEqual(projection["source_freshness"], "unknown")
        self.assertIsNone(projection["captured_at"])
        self.assertIn("value_path", projection["field_provenance"]["displayed_position"])
        self.assertEqual(self.snapshot(), value)
        for path, baseline in before.items(): self.assertEqual(self.client.get(path, headers=AUTH).json(), baseline)
        self.assertEqual(self.client.delete(BASE, headers=AUTH).json()["status"], "unavailable")
        self.assertIsNone(self.snapshot()["projection"])
    def test_unauthorized_cannot_import_read_or_clear_even_oversized(self):
        self.assertEqual(self.post().status_code, 200)
        prior = self.snapshot()
        for method, path in (("get", BASE), ("delete", BASE), ("post", BASE+"/import")):
            self.assertEqual(getattr(self.client,method)(path).status_code, 401)
        self.assertEqual(self.client.post(BASE+"/import", content=b'x'*40000).status_code, 401)
        self.assertEqual(self.snapshot(), prior)
    def test_invalid_import_clears_and_no_stale_fallback(self):
        for mutation in ("source", "scope", "failed", "unknown", "null_context", "missing", "identity"):
            self.assertEqual(self.post().status_code, 200)
            payload = copy.deepcopy(self.payload)
            if mutation == "source": payload["expected_source"]["pid"] += 1
            if mutation == "scope": payload["capture"]["result"]["FocusPath"] = "0/7"
            if mutation == "failed": payload["capture"]["result"]["Status"] = "failed"
            if mutation == "unknown": payload["filepath"] = "not-read"
            if mutation == "null_context": payload["operator_context"] = None
            if mutation == "missing": payload["capture"]["result"]["Observations"].pop(1)
            if mutation == "identity": payload["capture"]["page_identity_verified"] = True
            self.assertEqual(self.post(payload).status_code, 422, mutation)
            self.assertEqual(self.snapshot()["status"], "unavailable")
    def test_duplicate_invalid_json_and_actual_byte_limit_clear(self):
        raw = json.dumps(self.payload)
        bad = (raw[:-1]+',"capture":{}}', raw.replace('"PanelIndex": 0','"PanelIndex": 0, "PanelIndex": 0'),
               '{', '{"x":NaN}', '['*2000+']'*2000)
        for body in bad:
            self.post()
            self.assertEqual(self.client.post(BASE+"/import",headers=AUTH,content=body).status_code,422)
            self.assertIsNone(self.snapshot()["projection"])
        self.post()
        self.assertEqual(self.client.post(BASE+"/import",headers=AUTH,content=b' '*32769).status_code,413)
        self.assertIsNone(self.snapshot()["projection"])
        # Normal route keeps its old global cap; manual route cap is independently 32768.
        self.assertEqual(self.client.post('/v1/observations',headers=AUTH,content=b' '*4097).status_code,413)
        self.assertEqual(self.client.post(BASE+'/import',headers=AUTH,content=raw+' '*(32768-len(raw))).status_code,200)
    def test_clear_fences_an_inflight_older_upload(self):
        import asyncio
        import httpx
        async def exercise():
            ready, release = asyncio.Event(), asyncio.Event()
            raw = json.dumps(self.payload).encode()
            async def chunks():
                yield raw[:100]
                ready.set()
                await release.wait()
                yield raw[100:]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1") as client:
                pending = asyncio.create_task(client.post(BASE+'/import',headers=AUTH,content=chunks()))
                await ready.wait()
                cleared = await client.delete(BASE,headers=AUTH)
                self.assertEqual(cleared.status_code,200)
                release.set()
                self.assertEqual((await pending).status_code,409)
                self.assertIsNone((await client.get(BASE,headers=AUTH)).json()['projection'])
        asyncio.run(exercise())

    def test_snapshot_does_not_survive_process_app_restart(self):
        self.assertEqual(self.post().status_code,200)
        root = Path(self.temp.name) / 'second'
        other = create_app(Settings(data_dir=root,runtime_file=root/'runtime.json',token='synthetic-test-token'),enable_agent=False)
        with TestClient(other,base_url='http://127.0.0.1') as client:
            self.assertIsNone(client.get(BASE,headers=AUTH).json()['projection'])

    def test_manual_operator_context_never_identity(self):
        self.payload['operator_context'] = 'SYNTHETIC OPERATOR CONTEXT'
        result = self.post().json()['projection']['operator_context']
        self.assertFalse(result['bridge_verified']); self.assertFalse(result['used_for_identity'])

if __name__ == '__main__': unittest.main()
