"""Synthetic API boundary checks; no game or local producer is executed."""
from fastapi.testclient import TestClient
from football_assistant_data.reader import create_reader_app
from test_reader import AUTH, settings


def test_offseason_requires_auth_and_missing_producer_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("FOOTBALL_ASSISTANT_OFFSEASON_EXE", raising=False)
    with TestClient(create_reader_app(settings(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.get("/v1/reader/offseason").status_code == 401
        assert client.get("/v1/reader/offseason", headers=AUTH).json()["reason"] == "producer_not_configured"
        assert client.get("/v1/reader/offseason?club_uid=-1", headers=AUTH).status_code == 422
        assert client.get("/v1/reader/offseason?person_uid=2147483648", headers=AUTH).status_code == 422
        assert client.post("/v1/reader/offseason", headers=AUTH).status_code == 405
