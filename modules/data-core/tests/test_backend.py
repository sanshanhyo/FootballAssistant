"""Integration checks use a labelled local provider fixture, never a fake success mode in production."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data.config import ROOT, Settings


TOKEN = "test-only-access-token"
AUTH = {"Authorization":"Bearer "+TOKEN}


def settings(tmp_path, **kwargs):
    return Settings(data_dir=tmp_path,runtime_file=tmp_path/"runtime.json",token=TOKEN,**kwargs)


def client_for(config):
    return TestClient(create_app(config),base_url="http://127.0.0.1")


def test_auth_size_strict_observations_and_missing_model(tmp_path):
    config = settings(tmp_path,max_request_bytes=4096)
    with client_for(config) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/status").status_code == 401
        assert client.get("/v1/status",headers={"Authorization":"Bearer wrong"}).status_code == 401
        assert client.get("/v1/status",headers={b"authorization":b"Bearer \xff"}).status_code == 401
        assert client.get("/v1/status",headers=AUTH).json()["source_status"]["availability"] == "not_connected"
        result = client.post("/v1/chat",headers=AUTH,json={"message":"你好"})
        assert result.status_code == 503
        assert result.json()["detail"]["code"] == "model_not_configured"
        fixture = json.loads((ROOT/"contracts/examples/runtime-observation.json").read_text(encoding="utf-8"))
        result = client.post("/v1/observations",headers=AUTH,json=fixture)
        assert result.status_code == 200 and result.json()["source_status"]["availability"] == "synthetic"
        assert client.post("/v1/observations",headers=AUTH,json=fixture).json()["duplicate"] is True
        invalid = deepcopy(fixture)
        invalid["command"] = "modify_game"
        assert client.post("/v1/observations",headers=AUTH,json=invalid).status_code == 422
        invalid = deepcopy(fixture)
        invalid["event_id"] = "not-a-uuid"
        assert client.post("/v1/observations",headers=AUTH,json=invalid).status_code == 422
        assert client.post("/v1/chat",headers=AUTH,content=b"x"*4097).status_code == 413
        runtime = json.loads(config.runtime_file.read_text())
        assert runtime["token"] == TOKEN and runtime["pid"] > 0
        if __import__('os').name != 'nt':
            assert config.runtime_file.stat().st_mode & 0o777 == 0o600
    assert not config.runtime_file.exists()


def test_explicit_memory_survives_restart_and_deletes(tmp_path):
    config = settings(tmp_path)
    with client_for(config) as client:
        memory = client.post("/v1/memories",headers=AUTH,json={"content":"我喜欢高位逼抢。"}).json()
        assert memory["source"] == "user_explicit"
    with client_for(config) as client:
        assert client.get("/v1/memories",headers=AUTH).json()["memories"][0]["content"] == "我喜欢高位逼抢。"
        assert client.get("/v1/status",headers=AUTH).json()["memory"]["memories"] == 1
        assert client.delete("/v1/memories/"+memory["id"],headers=AUTH).status_code == 200
        assert client.get("/v1/memories",headers=AUTH).json()["memories"] == []


def test_real_sdk_wiring_and_history_with_local_provider_fixture(tmp_path):
    captured = []
    class FixtureProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append(body)
            response = {"id":"fixture-completion","created":0,"object":"chat.completion","model":"fixture-model","choices":[{"index":0,"message":{"role":"assistant","content":"测试服务回复，仅验证接口。"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}
            payload = json.dumps(response,ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self,*args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1",0),FixtureProvider)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    config = settings(tmp_path,base_url=f"http://127.0.0.1:{server.server_port}/v1",model="fixture-model",api_key="test-only-key",model_timeout=5)
    try:
        with client_for(config) as client:
            first = client.post("/v1/chat",headers=AUTH,json={"message":"第一轮接口测试"})
            assert first.status_code == 200, first.text
            conversation = first.json()["conversation_id"]
        with client_for(config) as client:
            second = client.post("/v1/chat",headers=AUTH,json={"message":"第二轮接口测试","conversation_id":conversation})
            assert second.status_code == 200, second.text
            assert client.get("/v1/status",headers=AUTH).json()["memory"]["messages"] == 4
        messages = captured[-1]["messages"]
        assert all(message["role"] != "assistant" for message in messages)
        payload = json.loads(next(message["content"] for message in messages if message["role"] == "user"))
        history = payload["untrusted_companionship"]["historical_conversation"]
        assert history == [
            {"role": "user", "content": "第一轮接口测试"},
            {"role": "assistant", "content": "测试服务回复，仅验证接口。"},
        ]
    finally:
        server.shutdown()
        server.server_close()


def test_model_connection_failure_is_explicit_and_not_saved(tmp_path):
    # Port is allocated then closed, so no provider fixture can claim a model answer.
    import socket
    with socket.socket() as listener:
        listener.bind(("127.0.0.1",0))
        port = listener.getsockname()[1]
    config = settings(tmp_path,base_url=f"http://127.0.0.1:{port}/v1",model="unavailable-model",api_key="test-only-key",model_timeout=0.2)
    with client_for(config) as client:
        result = client.post("/v1/chat",headers=AUTH,json={"message":"失败测试"})
        assert result.status_code == 502
        assert result.json()["detail"]["code"] == "model_unavailable"
        assert "test-only-key" not in result.text
        status = client.get("/v1/status",headers=AUTH).json()
        assert status["modelStatus"] == "error"
        assert status["memory"]["messages"] == 0


def test_fact_snapshot_schema_and_nonfinite_values(tmp_path):
    config = settings(tmp_path)
    with client_for(config) as client:
        fixture = json.loads((ROOT/"contracts/examples/synthetic-fact-snapshot.json").read_text(encoding="utf-8"))
        result = client.post("/v1/observations",headers=AUTH,json=fixture)
        assert result.status_code == 200
        assert result.json()["source_status"]["facts_count"] == 1
        assert result.json()["source_status"]["availability"] == "synthetic"
        invalid = deepcopy(fixture)
        invalid["schema_version"] = []
        assert client.post("/v1/observations",headers=AUTH,json=invalid).status_code == 422
        invalid = deepcopy(fixture)
        invalid["payload"]["facts"][0]["value"] = float("nan")
        assert client.post("/v1/observations",headers={**AUTH,"Content-Type":"application/json"},content=json.dumps(invalid)).status_code == 422
        invalid = deepcopy(fixture)
        invalid["source"]["kind"] = "save"
        assert client.post("/v1/observations",headers=AUTH,json=invalid).status_code == 422


def test_request_budget_survives_store_restart(tmp_path):
    from football_assistant_agent.storage import CompanionStore
    path = tmp_path/"budget.sqlite"
    store = CompanionStore(path)
    assert store.reserve_model_request("test-budget",2) is True
    assert store.reserve_model_request("test-budget",2) is True
    assert store.reserve_model_request("test-budget",2) is False
    store.close()
    store = CompanionStore(path)
    assert store.reserve_model_request("test-budget",2) is False
    store.close()


def test_field_provenance_must_match_envelope(tmp_path):
    config = settings(tmp_path)
    fixture = json.loads((ROOT/"contracts/examples/synthetic-fact-snapshot.json").read_text(encoding="utf-8"))
    fixture["schema_version"] = "0.3.0"
    fixture["source"].update(kind="save",freshness="snapshot",save_metadata={"snapshot_ref":"synthetic-copy","sha256":"a"*64,"file_modified_at":None,"parse_profile":"synthetic-test"})
    fixture["payload"]["facts"][0]["provenance"] = {"source":"save","adapter_id":fixture["source"]["adapter_id"],"experimental":True,"validation_method":"structural_only","evidence_ref":"synthetic-test","snapshot_sha256":"a"*64,"scope":"synthetic_label","ui_evidence_sample_sha256":None}
    with client_for(config) as client:
        assert client.post("/v1/observations",headers=AUTH,json=fixture).status_code == 200
        for field,wrong in [("source","runtime"),("adapter_id","different"),("snapshot_sha256","b"*64)]:
            invalid = deepcopy(fixture)
            invalid["payload"]["facts"][0]["provenance"][field] = wrong
            assert client.post("/v1/observations",headers=AUTH,json=invalid).status_code == 422


def test_exact_ui_verification_requires_matching_evidence_digest(tmp_path):
    config = settings(tmp_path)
    fixture = json.loads((ROOT/"contracts/examples/synthetic-fact-snapshot.json").read_text(encoding="utf-8"))
    fixture["schema_version"] = "0.3.0"
    fixture["source"].update(kind="save",freshness="snapshot",save_metadata={"snapshot_ref":"synthetic-copy","sha256":"a"*64,"file_modified_at":None,"parse_profile":"synthetic-test"})
    provenance = {"source":"save","adapter_id":fixture["source"]["adapter_id"],"experimental":True,"validation_method":"ui_crosscheck_exact_snapshot","evidence_ref":"synthetic-test","snapshot_sha256":"a"*64,"ui_evidence_sample_sha256":"b"*64,"scope":"synthetic_label"}
    fixture["payload"]["facts"][0]["provenance"] = provenance
    with client_for(config) as client:
        assert client.post("/v1/observations",headers=AUTH,json=fixture).status_code == 422
        provenance["validation_method"] = "format_checked_initial_sample_ui_crosschecked"
        assert client.post("/v1/observations",headers=AUTH,json=fixture).status_code == 200
