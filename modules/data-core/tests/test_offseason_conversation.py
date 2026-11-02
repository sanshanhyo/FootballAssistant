"""Regression for the reported keeper question; synthetic only, no native reads."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from football_assistant_agent.service import AgentService
from football_assistant_data.offseason_conversation import OffseasonConversation
from test_offseason_advice_context import envelope


def test_keeper_question_followup_confirmation_names_and_bounded_attributes():
    async def scenario():
        data = envelope()
        data['snapshot']['managerCandidates']['candidates'][0]['clubName'] = '示例队'
        players = [{'uid': uid, 'name': name, 'clubUid': 34, 'teamUid': 55, 'linkStatus': 'exact_types'} for uid, name in [(1, '甲球员'), (2, '乙球员'), (3, '丙球员')]]
        calls = []
        async def read(club, person):
            calls.append((club, person)); value = deepcopy(data)
            if club:
                value['snapshot']['team'] = {'status': 'experimental_candidates_incomplete', 'observedAt': value['snapshot']['capturedAt'], 'players': players}
            if person:
                value['snapshot']['player'] = {'observedAt': value['snapshot']['capturedAt'], 'value': {'status': 'experimental', 'uid': person, 'displayName': players[person-1]['name'], 'affiliation': {'clubUid': 34, 'teamUid': 55}, 'details': {'reflexesRaw': 71, 'handlingRaw': 58}}}
            return value
        agent = AgentService(None, None)
        contexts = []
        async def chat(message, conversation, context, **kwargs):
            contexts.append((message, context)); return {'reply': '只比较本次原始观测', 'conversation_id': conversation}
        agent._chat = chat
        reader = OffseasonConversation()
        def body(message, conversation=None):
            return SimpleNamespace(message=message, conversation_id=conversation, character_context=None)
        try:
            first = await reader.reply(body('让我们队伍谁当门将最合适'), read, agent)
            cid = first['conversation_id']
            assert '示例队' in first['reply'] and '哪支球队' in first['reply']
            follow = await reader.reply(body('你看一下吧', cid), read, agent)
            assert '先确认' in follow['reply'] and not contexts
            confirmed = await reader.reply(body('是的', cid), read, agent)
            assert '甲球员' in confirmed['reply'] and '没有球员位置' in confirmed['reply']
            result = await reader.reply(body('甲球员和乙球员是实际门将，比较他们', cid), read, agent)
            assert result['status'] == 'partial'
            facts = contexts[-1][1]['facts']
            assert len(facts['player_candidates']) == 2
            assert facts['player_candidates'][0]['attributes_raw']['reflexesRaw'] == 71
            assert sum(club == 34 and person == 0 for club, person in calls) == 1
            assert [(c,p) for c,p in calls if p] == [(34,1), (34,2)]
            assert '谁当门将最合适' in contexts[-1][0]
            people_before = sum(bool(p) for _, p in calls)
            await reader.reply(body('你看一下吧', cid), read, agent)
            assert sum(bool(p) for _, p in calls) == people_before
            before = len(calls)
            excess = await reader.reply(body('比较甲球员乙球员丙球员', cid), read, agent)
            assert '至多两位' in excess['reply'] and len(calls) == before + 1
            fresh = await reader.reply(body('谁当门将最合适', 'new-conversation'), read, agent)
            assert '哪支球队' in fresh['reply']
            other = body('谁当门将最合适', cid)
            other.character_context = SimpleNamespace(model_dump=lambda **kw: {'save_id': 'session:other', 'character_id': 'custom.other'})
            assert '哪支球队' in (await reader.reply(other, read, agent))['reply']
            data['snapshot']['process'] = envelope()['snapshot']['process']
            assert '哪支球队' in (await reader.reply(body('谁当门将最合适', cid), read, agent))['reply']
        finally:
            agent.close()
    asyncio.run(scenario())
