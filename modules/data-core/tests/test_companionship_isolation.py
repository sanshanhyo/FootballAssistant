"""Model-input regression fixtures only; no external provider or real game data."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from football_assistant_agent import service
from football_assistant_agent.storage import CompanionStore
from football_assistant_data.app import create_app
from test_backend import settings, AUTH


@pytest.fixture
def captured_model(monkeypatch):
    captured = {}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Agent:
        def __init__(self, model, system_prompt, **kwargs): captured['prompt'] = system_prompt
        async def run(self, message, **kwargs):
            captured.update(kwargs, message=message)
            return SimpleNamespace(output='你好呀！今天想聊什么？')
    monkeypatch.setattr(service, 'AsyncOpenAI', Client)
    monkeypatch.setattr(service, 'OpenAICompatibleProvider', lambda *a, **k: object())
    monkeypatch.setattr(service, 'OpenAIChatModel', lambda *a, **k: object())
    monkeypatch.setattr(service, 'Agent', Agent)
    return captured


@pytest.mark.parametrize('source_status', ['live', 'stale', 'source_mismatch', 'verified_business_snapshot'])
def test_greeting_never_uses_legacy_snapshot(tmp_path, captured_model, source_status):
    config = settings(tmp_path, base_url='http://invalid.test/v1', model='fixture-model', api_key='TEST-NOT-A-KEY')
    store = CompanionStore(tmp_path / 'test-companionship.sqlite')
    try:
        agent = service.AgentService(config, store)
        scope = {"save_id": "fixture-save", "character_id": "official.eckera"}
        memory = store.add_memory('请叫我阿明，我喜欢简洁温和的交流。', **scope)
        game_memory = store.add_memory('TEST-旧伤病断言：前锋受伤，恢复时间六周。', **scope)
        store.append_turn('TEST-conversation', '上一轮聊什么？', 'TEST-旧助手断言：预算九百万。', **scope)
        context = {'source_status': source_status, 'facts': ['TEST-captured-budget', 'TEST-captured-injury'],
                   'diagnostics': 'TEST-private-path', 'session_id': 'TEST-mismatched-session'}
        result = asyncio.run(agent.chat('你好', 'TEST-conversation', context, character_context=scope))
        assert result['source_status'] == 'not_used'
        serialized = json.dumps(captured_model, ensure_ascii=False)
        for marker in ('TEST-captured-budget', 'TEST-captured-injury', 'TEST-private-path', 'TEST-mismatched-session'):
            assert marker not in serialized
        assert captured_model['message_history'] == []
        assert '你是埃克拉（Eckera）' in json.loads(captured_model['message'])['untrusted_persona']
        assert '你是埃克拉（Eckera）' not in captured_model['prompt']
        assert '小北' not in captured_model['prompt']
        assert '阿明' not in captured_model['prompt']
        assert 'TEST-旧' not in captured_model['prompt']
        assert '不能从历史对话或记忆' in captured_model['prompt']
        payload = json.loads(captured_model['message'])
        assert payload['user_message'] == '你好'
        untrusted = payload['untrusted_companionship']
        assert untrusted['explicit_memories'] == [memory, game_memory]
        assert 'TEST-旧助手断言' in untrusted['historical_conversation'][-1]['content']
        # Filtering model input never deletes the user's real memory/history.
        assert store.memories(**scope) == [memory, game_memory]
        assert store.memories() == []  # Unassigned archive is never injected into a new session.
        assert store.counts() == {'messages': 4, 'memories': 2}
    finally:
        agent.close()
        store.close()


def test_chat_route_does_not_read_observation_context(tmp_path, captured_model, monkeypatch):
    app = create_app(settings(tmp_path, base_url='http://invalid.test/v1', model='fixture-model', api_key='TEST-NOT-A-KEY'))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        monkeypatch.setattr(app.state.observations, 'context', lambda: pytest.fail('ordinary chat must not read observations'))
        response = client.post('/v1/chat', headers=AUTH, json={'message': '你好'})
        assert response.status_code == 200, response.text
        assert response.json()['source_status'] == 'not_used'
        assert json.loads(captured_model['message'])['user_message'] == '你好'
