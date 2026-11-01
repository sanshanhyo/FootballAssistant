"""Synthetic candidate selection: no game or model required."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from football_assistant_data.calendar_selection import choose_calendar_scope

NOW = datetime(2026, 2, 7, tzinfo=timezone.utc)

def sample():
    return {"status":"partial", "snapshot":{"schema":"fa-offseason/0.1", "status":"partial", "capturedAt":NOW.isoformat(),
        "date":{"status":"experimental", "date":"2026-02-07", "observedAt":NOW.isoformat()},
        "managerCandidates":{"status":"experimental_candidates_incomplete", "unknown":0, "candidates":[{"uid":7,"clubUid":42,"clubName":"示例球队"}]}}}


def test_named_or_unique_candidate_is_never_active_manager_claim():
    scope = choose_calendar_scope(sample(), "示例球队接下来有哪些比赛", now=NOW)
    assert scope == {"club_uid":42,"manager_uid":7,"club_name":"示例球队","start":"2026-02-07","end":"2026-03-08","selection":"named_candidate"}
    assert choose_calendar_scope(sample(), "我的球队接下来有哪些比赛", now=NOW)["selection"] == "unique_candidate_not_active_confirmed"
    assert choose_calendar_scope(sample(), "其他球队接下来有哪些比赛", now=NOW) is None


def test_ambiguous_unknown_and_stale_fail_closed():
    data = sample(); data["snapshot"]["managerCandidates"]["unknown"] = 1
    assert choose_calendar_scope(data, "示例球队接下来有哪些比赛", now=NOW) is None
    data = sample(); data["snapshot"]["managerCandidates"]["candidates"].append({"uid":8,"clubUid":43,"clubName":"另一队"})
    assert choose_calendar_scope(data, "我的球队接下来有哪些比赛", now=NOW) is None
    data["snapshot"]["managerCandidates"]["candidates"][1]["clubName"] = "示例球队"
    assert choose_calendar_scope(data, "示例球队接下来有哪些比赛", now=NOW) is None
    data = sample(); data["snapshot"]["date"]["observedAt"] = (NOW-timedelta(minutes=1)).isoformat()
    assert choose_calendar_scope(data, "示例球队接下来有哪些比赛", now=NOW) is None


def test_range_truncates_at_year_end():
    data = sample(); data["snapshot"]["date"]["date"] = "2026-12-29"
    scope = choose_calendar_scope(data, "示例球队接下来有哪些比赛", now=NOW)
    assert scope["end"] == "2026-12-31"


def test_server_resolves_twice_and_rejects_changed_manager(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_data import offseason_snapshot
    from test_reader import AUTH, settings

    calls, advice = [], []
    changed = False
    async def fake_read(path, club_uid, person_uid, start=None, end=None):
        calls.append((club_uid, person_uid, start, end))
        value = sample()
        if changed and club_uid:
            value["snapshot"]["managerCandidates"]["candidates"][0]["uid"] = 8
        value["snapshot"]["capturedAt"] = datetime.now(timezone.utc).isoformat()
        value["snapshot"]["date"]["observedAt"] = value["snapshot"]["capturedAt"]
        return value
    async def fake_advice(message, conversation_id, data, club_uid, start, end):
        advice.append((club_uid, start, end))
        return {"status":"partial", "reply":"候选", "context":{"status":"partial"}}
    monkeypatch.setenv("FOOTBALL_ASSISTANT_OFFSEASON_EXE", str(tmp_path / "fake.exe"))
    monkeypatch.setattr(offseason_snapshot, "read_offseason", fake_read)
    app = create_app(settings(tmp_path), enable_agent=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.agent.calendar_advice = fake_advice
        body = {"message":"示例球队接下来有哪些比赛"}
        assert client.post("/v1/agent/auto-calendar-advice", json=body).status_code == 401
        assert not calls
        assert client.post("/v1/agent/auto-calendar-advice", headers=AUTH, json={**body,"club_uid":42}).status_code == 422
        assert not calls
        response = client.post("/v1/agent/auto-calendar-advice", headers=AUTH, json=body)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        assert len(calls) == 2 and calls[0][:2] == (0, 0) and calls[1][0] == 42
        assert advice == [(42, "2026-02-07", "2026-03-08")]
        assert response.json()["selection"]["selection"] == "named_candidate"
        changed = True
        response = client.post("/v1/agent/auto-calendar-advice", headers=AUTH, json=body)
        assert response.json()["status"] == "unavailable" and len(advice) == 1
