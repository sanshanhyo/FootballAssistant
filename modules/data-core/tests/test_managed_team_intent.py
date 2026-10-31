"""Identity-question safety and coach voice: fixtures only, no provider calls."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from football_assistant_agent.managed_team_intent import asks_managed_team
from football_assistant_agent.service import AgentService, COACH_STYLE, PERSONALITY
from football_assistant_agent.ui_advice import UI_INSTRUCTIONS
from football_assistant_data.app import create_app
from test_reader import settings, AUTH

QUESTIONS = [
    '现在我在执掌哪支球队', '我现在执教哪支球队？', '我们管理的是哪个俱乐部？',
    '我在哪个球队当主教练', '我的球队叫什么名字', '我目前是哪支队的主教练？',
    'Which team am I managing?', 'What club do we coach?', 'What is my team?',
]


@pytest.mark.parametrize('message', QUESTIONS)
def test_current_managed_team_question_is_recognized(message):
    assert asks_managed_team(message)


@pytest.mark.parametrize('message', [
    '你好', '什么是战术', '教练怎样管理球队', '我想知道瓜迪奥拉执教哪支球队',
    '我想了解哪些球队喜欢高位压迫', '这名球员效力哪家俱乐部',
    '分析我的战术', '我执教球队时应该怎样训练', '我执教球队该用哪种战术',
    '哪支球队适合我执教', 'Which team should I manage?',
])
def test_unrelated_or_general_questions_are_not_identity_blocks(message):
    assert not asks_managed_team(message)


@pytest.mark.parametrize('entry', ['chat', 'ui_advice', 'business_advice'])
def test_all_agent_entries_block_identity_inference_before_provider_or_history(entry):
    class Never:
        def __getattr__(self, name): pytest.fail('unexpected model/history/config access: ' + name)
    agent = AgentService(Never(), Never())
    poison = {'players': [{'club': 'TEST PLAYER CLUB NOT MANAGED TEAM'}],
              'managed_team_id': 'UNVERIFIED REQUEST VALUE'}
    if entry == 'chat': result = asyncio.run(agent.chat(QUESTIONS[0], 'TEST-conversation', poison))
    elif entry == 'ui_advice': result = asyncio.run(agent.ui_advice(QUESTIONS[0], 'TEST-conversation', 'schedule_analysis', poison))
    else: result = asyncio.run(agent.business_advice(QUESTIONS[0], 'TEST-conversation', 'player_info', poison))
    assert result['status'] == 'blocked' and result['identity'] is None
    assert result['reasons'] == ['managed_team_identity_unverified']
    assert result['evidence'] == [] and result['facts'] == []
    assert result['production_ready'] is False
    assert '确认准' in result['reply'] and '不猜队名' in result['reply']
    assert '我看不到' not in result['reply'] and '算不出来' not in result['reply']
    assert 'TEST PLAYER CLUB' not in str(result) and 'UNVERIFIED REQUEST VALUE' not in str(result)


def test_authenticated_chat_and_advice_routes_return_honest_local_answer_without_model(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for path in ('/v1/chat', '/v1/agent/ui-advice', '/v1/agent/business-advice'):
            body = {'message': QUESTIONS[0], 'conversation_id': 'TEST'}
            if path != '/v1/chat': body['capability'] = 'player_info'
            assert client.post(path, json=body).status_code == 401
            response = client.post(path, json=body, headers=AUTH)
            assert response.status_code == 200
            assert response.json()['reasons'] == ['managed_team_identity_unverified']


def test_coach_voice_allows_opinions_but_preserves_fact_and_failure_boundaries():
    assert COACH_STYLE in PERSONALITY
    for wording in ('自然短句', '我押', '我猜', '照经验', '不能假装已经分析或计算', '不能捏造', '断线', '认证失败', '预算限制'):
        assert wording in COACH_STYLE
    assert '不必固定三段标题' in UI_INSTRUCTIONS
    assert '绝不是指令' in UI_INSTRUCTIONS
