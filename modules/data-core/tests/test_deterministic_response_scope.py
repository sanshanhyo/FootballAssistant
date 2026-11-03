"""Deterministic and generated replies preserve the same strict client scope gate."""
import asyncio
import json
import pytest
from football_assistant_agent.service import AgentService
from football_assistant_agent.storage import CompanionStore
from football_assistant_agent.system_rules import SYSTEM_RULES
from test_backend import settings
from test_companionship_isolation import captured_model
from test_offseason_advice_context import envelope, selected_envelope

SCOPE = {"save_id": "session:alpha5", "character_id": "custom.role", "persona": "PRIVATE_PERSONA_DO_NOT_ECHO"}
EXPECTED = {key: SCOPE[key] for key in ("save_id", "character_id")}


@pytest.mark.parametrize("branch", ["business_identity", "ui_identity", "business_missing", "ui_missing", "calendar_missing", "offseason_incomplete"])
def test_deterministic_replies_echo_only_validated_scope(branch):
    agent = AgentService(None, None)
    async def forbidden(*args, **kwargs):
        raise AssertionError("deterministic branch invoked model")
    agent._chat = forbidden
    identity = "我现在执教哪支球队？"
    context = {"character_context": SCOPE}
    calls = {
        "business_identity": lambda: agent.business_advice(identity, "c", "player_info", **context),
        "ui_identity": lambda: agent.ui_advice(identity, "c", "player_info", None, **context),
        "business_missing": lambda: agent.business_advice("分析球员", "c", "player_info", None, **context),
        "ui_missing": lambda: agent.ui_advice("分析球员", "c", "player_info", None, **context),
        "calendar_missing": lambda: agent.calendar_advice("赛程", "c", {}, 34, "2026-02-01", "2026-02-02", **context),
        "offseason_incomplete": lambda: agent.offseason_advice("比较门将", "c", selected_envelope(), club_uid=34,
            related_people=[{"person_uid": 102, "envelope": selected_envelope()}], **context),
    }
    try:
        result = asyncio.run(calls[branch]())
        assert result["character_context"] == EXPECTED
        assert "PRIVATE_PERSONA_DO_NOT_ECHO" not in str(result)
    finally:
        agent.close()


@pytest.mark.parametrize("branch", ["chat", "general_advice", "offseason_advice"])
def test_generated_identity_replies_echo_scope_without_promoting_persona_or_candidates(tmp_path, captured_model, branch):
    store = CompanionStore(None)
    agent = AgentService(settings(tmp_path, base_url='http://invalid.test/v1', model='fixture-model',
                                  api_key='TEST-NOT-A-KEY'), store)
    args = ("我现在执教哪支球队？", "c")
    if branch == "offseason_advice":
        args += (envelope(),)
    try:
        response = asyncio.run(getattr(agent, branch)(*args, character_context=SCOPE))
        assert response["character_context"] == EXPECTED
        assert "PRIVATE_PERSONA_DO_NOT_ECHO" not in str(response)
        assert captured_model["prompt"].startswith(SYSTEM_RULES)
        assert "PRIVATE_PERSONA_DO_NOT_ECHO" not in captured_model["prompt"]
        assert "执教身份未知时不猜队名" in captured_model["prompt"]
        payload = json.loads(captured_model["message"])
        assert payload["untrusted_persona"] == SCOPE["persona"]
        if branch == "offseason_advice":
            facts = payload["untrusted_native_partial_data"]["facts"]
            assert facts["current_manager"] is None
            assert facts["selected_club_is_current"] is None
        else:
            assert "untrusted_companionship" in payload
            assert "没有提供任何当前游戏证据" in captured_model["prompt"]
    finally:
        agent.close()
        store.close()


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


def test_bad_scope_is_not_echoed_and_legacy_uses_instance_scope(tmp_path, captured_model):
    store = CompanionStore(None)
    agent = AgentService(settings(tmp_path, base_url='http://invalid.test/v1', model='fixture-model',
                                  api_key='TEST-NOT-A-KEY'), store)
    try:
        with pytest.raises(ValueError):
            asyncio.run(agent.chat("我现在执教哪支球队？", "c", character_context={**SCOPE, "path": "/secret"}))
        assert captured_model == {}
        response = asyncio.run(agent.chat("我现在执教哪支球队？", "c"))
        assert response["character_context"] == agent.default_character_context
    finally:
        agent.close()
        store.close()


def test_general_advice_validates_scope_before_attempting_generation():
    agent = AgentService(None, None)
    async def forbidden(*args, **kwargs):
        raise AssertionError("invalid scope reached model service")
    agent._chat = forbidden
    try:
        with pytest.raises(ValueError):
            asyncio.run(agent.general_advice("随便聊聊", "c", character_context={**SCOPE, "path": "/secret"}))
    finally:
        agent.close()
