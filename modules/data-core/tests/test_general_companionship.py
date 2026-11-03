"""Natural no-evidence conversation still uses the real prompt and failure boundaries.

Provider outputs are fixtures, not evidence of live model or game performance.
"""
import asyncio
import json
from dataclasses import replace

import pytest

from football_assistant_agent import service
from football_assistant_agent.storage import CompanionStore
from football_assistant_agent.system_rules import COMPANIONSHIP_INSTRUCTIONS, SYSTEM_RULES
from test_backend import settings
from test_companionship_isolation import captured_model
from test_offseason_advice_context import envelope


def configured(tmp_path, **kwargs):
    return settings(tmp_path, base_url='http://invalid.test/v1', model='fixture-model',
                    api_key='TEST-NOT-A-KEY', **kwargs)


@pytest.mark.parametrize('entry', ['chat', 'general_advice'])
def test_unknown_identity_reaches_natural_companionship_without_promoting_proof(tmp_path, captured_model, entry):
    original = b'USER OWNED PERSONA\r\nDo not replace.\r\n'
    persona = tmp_path / 'persona.md'
    persona.write_bytes(original)
    store = CompanionStore(None)
    agent = service.AgentService(configured(tmp_path), store)
    scope = {'save_id': 'fixture-save', 'character_id': 'official.eckera'}
    try:
        store.add_memory('TEST_MEMORY says verified club is History United', **scope)
        store.append_turn('conversation', 'club?', 'TEST_OLD_ASSISTANT claims verified Club 2', **scope)
        kwargs = {'character_context': scope}
        if entry == 'chat':
            kwargs['context'] = {'source_status': 'verified_business_snapshot',
                'producerVerified': True, 'facts': ['TEST_PAYLOAD_PROOF'],
                'current_manager': {'club_name': 'TEST_FAKE_BINDING'}}
        result = asyncio.run(getattr(agent, entry)('我现在执教哪支球队？也聊聊你的战术偏好', 'conversation', **kwargs))
        payload = json.loads(captured_model['message'])
        assert result['reply'] == '你好呀！今天想聊什么？'
        assert result['character_context'] == scope
        assert captured_model['prompt'] == SYSTEM_RULES + COMPANIONSHIP_INSTRUCTIONS
        assert '没有提供任何当前游戏证据' in captured_model['prompt']
        assert '表达个人偏好、开玩笑' in captured_model['prompt']
        assert '不要把缺数据变成整段拒绝' in captured_model['prompt']
        assert '执教身份未知时不猜队名' in captured_model['prompt']
        assert 'UI 采样建议入口' not in captured_model['prompt']
        assert set(payload) == {'user_message', 'untrusted_persona', 'untrusted_companionship'}
        assert 'TEST_MEMORY' in str(payload['untrusted_companionship'])
        assert 'TEST_OLD_ASSISTANT' in str(payload['untrusted_companionship'])
        for marker in ('TEST_PAYLOAD_PROOF', 'TEST_FAKE_BINDING'):
            assert marker not in str(captured_model)
        for marker in ('TEST_MEMORY', 'TEST_OLD_ASSISTANT', 'USER OWNED PERSONA'):
            assert marker not in captured_model['prompt']
        assert captured_model['message_history'] == []
        assert persona.read_bytes() == original
        if entry == 'general_advice':
            assert result['status'] == 'general_advice'
            assert result['source_status'] == result['source'] == 'general_knowledge'
            assert result['production_ready'] is False
            assert not {'facts', 'evidence', 'context', 'identity'} & result.keys()
        else:
            assert result['source_status'] == 'not_used'
    finally:
        agent.close()
        store.close()


def test_general_advice_keeps_selected_character_memory_and_routing_scope(tmp_path, captured_model):
    store = CompanionStore(tmp_path / 'scope.sqlite')
    agent = service.AgentService(configured(tmp_path), store)
    selected = {'save_id': 'session:unknown', 'character_id': 'example.custom', 'persona': 'CUSTOM_STYLE'}
    scope = {key: selected[key] for key in ('save_id', 'character_id')}
    transient = agent.store_for_context(scope)
    try:
        transient.add_memory('SELECTED_MEMORY', **scope)
        transient.add_memory('OTHER_CHARACTER_MEMORY', save_id=scope['save_id'], character_id='example.other')
        store.add_memory('PERSISTENT_ARCHIVE_MEMORY')
        result = asyncio.run(agent.general_advice('读取不到也陪我聊聊', 'shared-id', character_context=selected))
        assert result['character_context'] == scope
        payload = json.loads(captured_model['message'])
        assert payload['untrusted_persona'] == selected['persona']
        assert 'SELECTED_MEMORY' in captured_model['message']
        assert 'OTHER_CHARACTER_MEMORY' not in captured_model['message']
        assert 'PERSISTENT_ARCHIVE_MEMORY' not in captured_model['message']
        assert len(transient.recent_messages('shared-id', **scope)) == 2
        assert store.counts()['messages'] == 0
    finally:
        agent.close()
        store.close()


def test_partial_unknown_identity_uses_validated_projection_not_fixed_refusal(tmp_path, captured_model):
    store = CompanionStore(None)
    agent = service.AgentService(configured(tmp_path), store)
    data = envelope()
    data['snapshot']['requestProof'] = 'TEST_UNTRUSTED_PAYLOAD_PROOF'
    scope = {'save_id': 'session:partial', 'character_id': 'official.eckera'}
    try:
        result = asyncio.run(agent.offseason_advice('我现在执教哪支球队？', 'conversation', data,
                                                    character_context=scope))
        assert result['status'] == 'partial'
        assert result['source_status'] == 'partial_native_candidates'
        assert result['character_context'] == scope
        assert result['reply'] == '你好呀！今天想聊什么？'
        assert result['context']['facts']['current_manager'] is None
        assert result['context']['facts']['selected_club_is_current'] is None
        assert result['context']['limitations']
        payload = json.loads(captured_model['message'])
        native = payload['untrusted_native_partial_data']
        assert set(native) == {'source_status', 'facts', 'limitations'}
        assert native['facts']['current_manager'] is None
        assert native['facts']['manager_club_candidates'][0]['clubName'] == 'Synthetic club'
        assert 'TEST_UNTRUSTED_PAYLOAD_PROOF' not in str(captured_model)
        assert data['snapshot']['process']['sessionId'] not in str(captured_model)
        assert 'DO NOT SEND' not in str(captured_model)
        assert '先自然回应用户' in captured_model['prompt']
        assert '不能把其他候选说成已验证事实' in captured_model['prompt']
        assert '执教身份未知时不猜队名' in captured_model['prompt']
    finally:
        agent.close()
        store.close()


@pytest.mark.parametrize('failure', ['missing_model', 'budget', 'provider'])
def test_general_advice_never_conceals_model_or_budget_failure(tmp_path, captured_model, monkeypatch, failure):
    config = configured(tmp_path)
    if failure == 'missing_model':
        config = settings(tmp_path)
    elif failure == 'budget':
        config = replace(config, model_request_limit=1)
    else:
        class FailingAgent:
            def __init__(self, *args, **kwargs): pass
            async def run(self, *args, **kwargs):
                raise RuntimeError('PRIVATE_PROVIDER_BODY_AND_SECRET')
        monkeypatch.setattr(service, 'Agent', FailingAgent)
    store = CompanionStore(None)
    if failure == 'budget':
        assert store.reserve_model_request(config.model_budget_id, config.model_request_limit)
    agent = service.AgentService(config, store)
    expected = {'missing_model': service.ModelNotConfigured, 'budget': service.ModelBudgetExceeded,
                'provider': service.ModelUnavailable}[failure]
    try:
        with pytest.raises(expected) as caught:
            asyncio.run(agent.general_advice('随便聊聊', None))
        assert 'PRIVATE_PROVIDER_BODY_AND_SECRET' not in str(caught.value)
        assert agent.counts()['messages'] == 0
    finally:
        agent.close()
        store.close()
