"""Synthetic only: prove calendar context stays partial and does not invoke a model on invalid data."""
import asyncio
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from football_assistant_agent.calendar_advice import prepare_calendar_advice
from football_assistant_agent.service import AgentService


def envelope():
    now = datetime.now(timezone.utc).isoformat()
    return {"status":"partial", "snapshot":{"schema":"fa-offseason/0.1", "status":"partial", "calendar":{
        "status":"partial", "observedAt":now, "unloaded":1, "unknown":2,
        "fixtures":[{"date":"2026-02-07", "opponentName":"Synthetic opponent", "venue":"unknown", "ignored":"must not reach model"}]}}}


def test_projection_is_partial_and_whitelisted():
    result = prepare_calendar_advice(envelope(), 42, "2026-02-01", "2026-02-10")
    assert result["selected_club_uid"] == 42 and result["status"] == "partial"
    assert result["unloaded"] == 1 and result["unknown"] == 2
    assert result["fixtures"] == [{"date":"2026-02-07", "opponent":"Synthetic opponent", "venue":"unknown"}]
    assert "incomplete" in result["limitation"]


def test_stale_or_out_of_range_never_calls_model():
    agent = AgentService(None, None)
    async def forbidden(*args, **kwargs):
        raise AssertionError("model must not be called")
    agent._chat = forbidden
    data = envelope()
    data["snapshot"]["calendar"]["observedAt"] = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    result = asyncio.run(agent.calendar_advice("question", None, data, 42, "2026-02-01", "2026-02-10"))
    assert result["status"] == "unavailable" and result["context"] is None
    data = envelope(); data["snapshot"]["calendar"]["fixtures"][0]["date"] = "2026-03-01"
    assert prepare_calendar_advice(data, 42, "2026-02-01", "2026-02-10") is None


def test_model_context_has_no_unrelated_snapshot_data():
    agent = AgentService(None, None)
    captured = {}
    async def fake_chat(message, conversation_id, context, **kwargs):
        captured.update(context)
        return {"reply":"Synthetic reply", "conversation_id":conversation_id, "source_status":context["source_status"]}
    agent._chat = fake_chat
    data = envelope(); data["snapshot"]["secret"] = "DO NOT SEND"
    result = asyncio.run(agent.calendar_advice("question", "c", data, 42, "2026-02-01", "2026-02-10"))
    assert result["status"] == "partial" and "未确认" in result["reply"]
    assert captured["calendar"]["selected_club_uid"] == 42
    assert "DO NOT SEND" not in str(captured) and "ignored" not in str(captured)


def test_authenticated_server_owns_candidate_handoff(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_data import offseason_snapshot
    from test_reader import AUTH, settings

    reads, contexts = [], []
    async def fake_read(path, club_uid, person_uid, start, end):
        reads.append((club_uid, person_uid, start, end))
        return envelope()
    async def fake_chat(message, conversation_id, context, **kwargs):
        contexts.append(context)
        return {"reply":"Synthetic", "conversation_id":conversation_id, "source_status":context["source_status"]}
    monkeypatch.setenv("FOOTBALL_ASSISTANT_OFFSEASON_EXE", str(tmp_path / "fake.exe"))
    monkeypatch.setattr(offseason_snapshot, "read_offseason", fake_read)
    app = create_app(settings(tmp_path), enable_agent=True)
    body = {"message":"question", "club_uid":42, "start":"2026-02-01", "end":"2026-02-10"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.agent._chat = fake_chat
        assert client.post("/v1/agent/calendar-advice", json=body).status_code == 401
        assert reads == []
        assert client.post("/v1/agent/calendar-advice", headers=AUTH, json={**body,"snapshot":envelope()}).status_code == 422
        assert reads == []
        response = client.post("/v1/agent/calendar-advice", headers=AUTH, json=body)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        assert reads == [(42, 0, "2026-02-01", "2026-02-10")]
        assert contexts[0]["calendar"]["selected_club_uid"] == 42
        assert contexts[0]["calendar"]["unloaded"] == 1
