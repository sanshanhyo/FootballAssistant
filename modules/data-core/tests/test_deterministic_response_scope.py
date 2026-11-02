"""Every deterministic reply must survive the same strict client scope gate as model replies."""
import asyncio
import pytest
from football_assistant_agent.service import AgentService
from test_offseason_advice_context import envelope, selected_envelope

SCOPE = {"save_id": "session:alpha5", "character_id": "custom.role", "persona": "PRIVATE_PERSONA_DO_NOT_ECHO"}
EXPECTED = {key: SCOPE[key] for key in ("save_id", "character_id")}


@pytest.mark.parametrize("branch", ["chat_identity", "business_identity", "ui_identity", "business_missing", "ui_missing", "calendar_missing", "offseason_identity", "offseason_incomplete"])
def test_deterministic_replies_echo_only_validated_scope(branch):
    agent = AgentService(None, None)
    async def forbidden(*args, **kwargs):
        raise AssertionError("deterministic branch invoked model")
    agent._chat = forbidden
    identity = "我现在执教哪支球队？"
    context = {"character_context": SCOPE}
    calls = {
        "chat_identity": lambda: agent.chat(identity, "c", **context),
        "business_identity": lambda: agent.business_advice(identity, "c", "player_info", **context),
        "ui_identity": lambda: agent.ui_advice(identity, "c", "player_info", None, **context),
        "business_missing": lambda: agent.business_advice("分析球员", "c", "player_info", None, **context),
        "ui_missing": lambda: agent.ui_advice("分析球员", "c", "player_info", None, **context),
        "calendar_missing": lambda: agent.calendar_advice("赛程", "c", {}, 34, "2026-02-01", "2026-02-02", **context),
        "offseason_identity": lambda: agent.offseason_advice(identity, "c", envelope(), **context),
        "offseason_incomplete": lambda: agent.offseason_advice("比较门将", "c", selected_envelope(), club_uid=34,
            related_people=[{"person_uid": 102, "envelope": selected_envelope()}], **context),
    }
    try:
        result = asyncio.run(calls[branch]())
        assert result["character_context"] == EXPECTED
        assert "PRIVATE_PERSONA_DO_NOT_ECHO" not in str(result)
    finally:
        agent.close()


def test_expired_generated_response_still_echoes_scope(monkeypatch):
    from football_assistant_agent import service
    original = service.prepare_offseason_advice
    expired = False
    def prepare(*args, **kwargs):
        return None if expired else original(*args, **kwargs)
    monkeypatch.setattr(service, "prepare_offseason_advice", prepare)
    agent = AgentService(None, None)
    async def fake_chat(*args, **kwargs):
        nonlocal expired
        expired = True
        return {"reply": "not displayed"}
    agent._chat = fake_chat
    try:
        result = asyncio.run(agent.offseason_advice("今天", "c", envelope(), character_context=SCOPE))
        assert result["context"]["freshness"] == "expired_during_generation"
        assert result["character_context"] == EXPECTED
        assert "PRIVATE_PERSONA_DO_NOT_ECHO" not in str(result)
    finally:
        agent.close()


def test_bad_scope_is_not_echoed_and_legacy_uses_instance_scope():
    agent = AgentService(None, None)
    try:
        with pytest.raises(ValueError):
            asyncio.run(agent.chat("我现在执教哪支球队？", "c", character_context={**SCOPE, "path": "/secret"}))
        response = asyncio.run(agent.chat("我现在执教哪支球队？", "c"))
        assert response["character_context"] == agent.default_character_context
    finally:
        agent.close()
