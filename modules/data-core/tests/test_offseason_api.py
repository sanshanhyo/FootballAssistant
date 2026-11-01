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


def test_offseason_forwards_explicit_selectors_to_configured_reader(tmp_path, monkeypatch):
    from football_assistant_data import offseason_snapshot

    calls = []
    async def fake_reader(path, club_uid, person_uid):
        calls.append((path, club_uid, person_uid))
        return {"status": "partial", "snapshot": {"schema": "fa-offseason/0.1", "tactic": {"status": "experimental", "phase": "unknown"}}}

    monkeypatch.setenv("FOOTBALL_ASSISTANT_OFFSEASON_EXE", str(tmp_path / "reader.exe"))
    monkeypatch.setattr(offseason_snapshot, "read_offseason", fake_reader)
    with TestClient(create_reader_app(settings(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.get("/v1/reader/offseason?club_uid=42&person_uid=7").status_code == 401
        assert calls == []
        response = client.get("/v1/reader/offseason?club_uid=42&person_uid=7", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["status"] == "partial"
        assert response.json()["snapshot"]["tactic"] == {"status": "experimental", "phase": "unknown"}
        assert calls == [(tmp_path / "reader.exe", 42, 7)]


def test_offseason_calendar_range_validation_and_forwarding(tmp_path, monkeypatch):
    from football_assistant_data import offseason_snapshot

    calls = []
    async def fake_reader(path, club_uid, person_uid, start, end):
        calls.append((club_uid, person_uid, start, end))
        return {"status": "partial", "snapshot": {"calendar": {"status": "partial", "unloaded": 1}}}

    monkeypatch.setenv("FOOTBALL_ASSISTANT_OFFSEASON_EXE", str(tmp_path / "reader.exe"))
    monkeypatch.setattr(offseason_snapshot, "read_offseason", fake_reader)
    with TestClient(create_reader_app(settings(tmp_path)), base_url="http://127.0.0.1") as client:
        path = "/v1/reader/offseason"
        for query in ("?start=2026-02-01", "?start=2026-02-01&end=2026-02-02", "?club_uid=42&start=2026-02-30&end=2026-03-01", "?club_uid=42&start=2026-02-01&end=2026-03-03", "?club_uid=42&start=2026-12-31&end=2027-01-01", "?club_uid=42&start=2026-03-01&end=2026-02-28"):
            assert client.get(path + query, headers=AUTH).status_code == 422
        assert calls == []
        query = "?club_uid=42&start=2026-02-01&end=2026-03-02"
        assert client.get(path + query).status_code == 401
        result = client.get(path + query, headers=AUTH).json()
        assert result["snapshot"]["calendar"] == {"status": "partial", "unloaded": 1}
        assert calls == [(42, 0, "2026-02-01", "2026-03-02")]
