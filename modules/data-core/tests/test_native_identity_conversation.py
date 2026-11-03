"""Synthetic conversation handoff of researched native fields, not game acceptance."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from football_assistant_agent.service import AgentService
from football_assistant_data.offseason_conversation import OffseasonConversation
from test_native_identity_projection import native_envelope, positions


def run_scenario(change=None):
    async def scenario():
        data = native_envelope()
        rows = data['snapshot']['team']['players']
        rows[0]['positions'] = positions(15)
        rows[1]['positions'] = positions(20)
        calls, contexts = [], []
        async def read(club, person):
            calls.append((club, person))
            value = deepcopy(data)
            if person:
                row = next(r for r in value['snapshot']['team']['players'] if r['uid'] == person)
                value['snapshot']['player']['value'].update(uid=person, displayName=row['name'], positions=row['positions'], affiliation={'clubUid': club, 'teamUid': row['teamUid']})
            if change:
                change(value, club, person, calls)
            return value
        scope = {'save_id': 'session:synthetic-alpha8', 'character_id': 'official.eckera'}
        def body(message):
            return SimpleNamespace(message=message, conversation_id='native-conversation', character_context=SimpleNamespace(model_dump=lambda **kw: scope))
        agent = AgentService(None, None)
        async def chat(message, conversation, context, **kwargs):
            contexts.append(context)
            return {'reply': '本次两个候选只按已读原始属性比较。', 'conversation_id': conversation}
        agent._chat = chat
        reader = OffseasonConversation()
        try:
            result = await reader.reply(body('你推荐我们选择哪个门将呢'), read, agent)
            return reader, result, calls, contexts, data, read, body, agent
        except BaseException:
            agent.close()
            raise
    return scenario


def test_native_keeper_question_and_followup_avoid_uid_confirmation_and_fanout():
    async def scenario():
        reader, result, calls, contexts, data, read, body, agent = await run_scenario()()
        try:
            assert result['character_context']['character_id'] == 'official.eckera'
            assert '哪支球队' not in result['reply'] and '其中 2 人的位置熟练度' in result['reply']
            assert calls == [(0, 0), (34, 0), (34, 101), (34, 102)]
            people = contexts[-1]['facts']['player_candidates']
            assert [p['positions']['is_goalkeeper'] for p in people] == [True, True]
            assert people[0]['positions']['goalkeeper_familiarity'] == 15
            assert not people[0]['positions']['natural_position_codes']
            await reader.reply(body('你看一下吧'), read, agent)
            assert calls[-1] == (0, 0) and len(calls) == 5
            data['snapshot']['manager']['uid'] = 13
            changed = await reader.reply(body('你看一下吧'), read, agent)
            assert calls[-2:] == [(0, 0), (34, 0)]
            assert not next(iter(reader.sessions.values()))['people']
            await reader.reply(body('谁当门将最合适'), read, agent)
            assert calls[-3:] == [(0, 0), (34, 101), (34, 102)]
        finally:
            agent.close()
    asyncio.run(scenario())


def test_mid_read_manager_change_stops_comparison():
    def change(value, club, person, calls):
        if person:
            value['snapshot']['manager']['uid'] = 99
    async def scenario():
        reader, result, calls, contexts, *_rest, agent = await run_scenario(change)()
        try:
            assert '已停止比较' in result['reply']
            assert not contexts and calls == [(0, 0), (34, 0), (34, 101)]
        finally:
            agent.close()
    asyncio.run(scenario())


def test_more_than_two_native_keepers_discloses_all_and_requests_names():
    def change(value, club, person, calls):
        if club:
            third = deepcopy(value['snapshot']['team']['players'][0])
            third.update(uid=103, name='Third keeper', positions=positions())
            value['snapshot']['team']['players'].append(third)
    async def scenario():
        reader, result, calls, contexts, *_rest, agent = await run_scenario(change)()
        try:
            assert 'Third keeper' in result['reply'] and '至多两位' in result['reply']
            assert not contexts and calls == [(0, 0), (34, 0)]
        finally:
            agent.close()
    asyncio.run(scenario())


def test_missing_position_does_not_make_other_player_a_non_keeper():
    def change(value, club, person, calls):
        value['snapshot']['team']['players'][1].pop('positions', None)
    async def scenario():
        reader, result, calls, contexts, *_rest, agent = await run_scenario(change)()
        try:
            assert '不会把缺失位置当作非门将' in result['reply']
            assert not contexts and calls == [(0, 0), (34, 0)]
        finally:
            agent.close()
    asyncio.run(scenario())


def test_native_keeper_http_chat_and_advice_keep_character_scope(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_data import offseason_snapshot
    from test_reader import AUTH, settings
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'fixture.exe'))
    calls = []
    async def read(executable, club, person, **kwargs):
        calls.append((club, person))
        value = native_envelope()
        # A single fixed process is essential across independent synthetic reads.
        value['snapshot']['process'] = deepcopy(base['snapshot']['process'])
        if person:
            row = next(r for r in value['snapshot']['team']['players'] if r['uid'] == person)
            value['snapshot']['player']['value'].update(uid=person, displayName=row['name'], positions=row['positions'])
        return value
    base = native_envelope()
    monkeypatch.setattr(offseason_snapshot, 'read_offseason', read)
    scope = {'save_id': 'session:native-http', 'character_id': 'official.eckera', 'persona': 'PRIVATE_DO_NOT_ECHO'}
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        async def chat(message, conversation, context, **kwargs):
            assert len(context['facts']['player_candidates']) == 2
            assert context['facts']['selected_club_is_current'] is True
            return {'reply': '仅比较这次已读到的两位门将。', 'conversation_id': conversation}
        monkeypatch.setattr(app.state.agent, '_chat', chat)
        for route, extra in [('/v1/chat', {}), ('/v1/agent/business-advice', {'capability': 'tactical_analysis'})]:
            response = client.post(route, headers=AUTH, json={'message': '你推荐谁给我们门将', 'conversation_id': route.replace('/', '-'), 'character_context': scope, **extra})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['reply'].strip() and result['status'] == 'partial'
            assert result['character_context'] == {k: scope[k] for k in ('save_id', 'character_id')}
            assert 'PRIVATE_DO_NOT_ECHO' not in str(result)
        assert calls == [(0, 0), (34, 0), (34, 101), (34, 102)] * 2
        assert app.state.business_snapshots.read()['snapshot'] is None
