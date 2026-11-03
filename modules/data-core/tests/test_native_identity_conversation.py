"""Synthetic conversation handoff of researched native fields, not game acceptance."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from football_assistant_agent.service import AgentService
from football_assistant_data.offseason_conversation import OffseasonConversation
from test_native_identity_projection import native_envelope, positions


def run_scenario(change=None, *, fail_first=False):
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
            if fail_first and len(contexts) == 1:
                from football_assistant_agent.service import ModelUnavailable
                raise ModelUnavailable('模型服务没有返回可用的文本响应。', reason='invalid_response', subtype='token_limit')
            return {'reply': '本次两个候选只按已读原始属性比较。', 'conversation_id': conversation}
        agent._chat = chat
        reader = OffseasonConversation()
        try:
            if fail_first:
                import pytest
                from football_assistant_agent.service import ModelUnavailable
                with pytest.raises(ModelUnavailable):
                    await reader.reply(body('你推荐我们选择哪个门将呢'), read, agent)
                result = None
            else:
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
            assert result['source_status'] == 'general_knowledge'
            assert not contexts[-1].get('facts') and calls == [(0, 0), (34, 0), (34, 101)]
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


def test_lost_native_binding_returns_to_confirmation_without_old_people():
    async def scenario():
        reader, result, calls, contexts, data, read, body, agent = await run_scenario()()
        try:
            prior_reads, prior_contexts = len(calls), len(contexts)
            data['snapshot']['manager'] = {'status': 'unavailable', 'reason': 'no_current_manager_selection'}
            result = await reader.reply(body('你推荐我们选择哪个门将呢'), read, agent)
            assert '哪支球队' in result['reply']
            assert len(calls) == prior_reads + 1 and len(contexts) == prior_contexts
            state = next(iter(reader.sessions.values()))
            assert state['club'] == 0 and not state['people'] and not state['last_selected']
        finally:
            agent.close()
    asyncio.run(scenario())


def test_current_team_question_uses_only_validated_identity_and_casual_chat_skips_reads():
    async def scenario():
        data = native_envelope()
        calls, contexts = [], []
        async def read(club, person):
            calls.append((club, person)); return deepcopy(data)
        reader = OffseasonConversation()
        agent = AgentService(None, None)
        async def chat(message, conversation, context, **kwargs):
            contexts.append(context)
            return {'reply': '当前经理的俱乐部关联已经读到。', 'conversation_id': conversation}
        agent._chat = chat
        def body(message):
            return SimpleNamespace(message=message, conversation_id='identity', character_context=None)
        try:
            answer = await reader.reply(body('我们现在执教哪支球队？'), read, agent)
            assert answer['status'] == 'partial'
            assert contexts[-1]['facts']['current_manager']['club_uid'] == 34
            assert calls == [(0, 0)]  # Not a request for the entire roster/keeper comparison.
            assert await reader.reply(body('你开心吗？'), read, agent) is None
            assert calls == [(0, 0)]
        finally:
            agent.close()
    asyncio.run(scenario())


def test_sequential_detail_reads_reuse_latest_matching_team_without_extending_freshness(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from football_assistant_agent import offseason_advice, service
    from football_assistant_data import offseason_conversation
    clock = [datetime.now(timezone.utc)]
    original = offseason_advice.prepare_offseason_advice
    def prepare(value, **kwargs):
        return original(value, now=clock[0], **kwargs)
    monkeypatch.setattr(service, 'prepare_offseason_advice', prepare)
    monkeypatch.setattr(offseason_conversation, 'prepare_offseason_advice', prepare)
    async def scenario():
        data = native_envelope()
        calls = []
        def stamp(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('capturedAt', 'observedAt'):
                        value[key] = clock[0].isoformat()
                    else:
                        stamp(item)
            elif isinstance(value, list):
                for item in value: stamp(item)
        async def read(club, person):
            calls.append((club, person)); clock[0] += timedelta(seconds=12)
            value = deepcopy(data); stamp(value)
            if person:
                row = next(r for r in value['snapshot']['team']['players'] if r['uid'] == person)
                value['snapshot']['player']['value'].update(uid=person, displayName=row['name'], positions=row['positions'])
            return value
        agent = AgentService(None, None)
        async def chat(message, conversation, context, **kwargs):
            assert len(context['facts']['player_candidates']) == 2
            clock[0] += timedelta(seconds=10)
            return {'reply': '按这次两人的已读属性比较。', 'conversation_id': conversation}
        agent._chat = chat
        reader = OffseasonConversation()
        body = SimpleNamespace(message='你推荐谁给我们门将', conversation_id='slow-scans', character_context=None)
        try:
            result = await reader.reply(body, read, agent)
            assert result['context']['freshness'] == 'observed_for_request'
            assert '按这次两人的已读属性比较' in result['reply']
            assert calls == [(0, 0), (34, 0), (34, 101), (34, 102)]
            assert (clock[0] - datetime.fromisoformat(result['context']['observed_at'])).total_seconds() == 10
        finally:
            agent.close()
    asyncio.run(scenario())


def test_explicit_topic_exit_beats_football_keywords_and_clears_followup_target():
    async def scenario():
        reader, result, calls, contexts, data, read, body, agent = await run_scenario()()
        try:
            count = len(calls)
            assert await reader.reply(body('我们不聊足球了，给我讲个笑话'), read, agent) is None
            assert len(calls) == count
            state = next(iter(reader.sessions.values()))
            assert state['question'] == '' and state['last_selected'] == []
            assert await reader.reply(body('你看一下吧'), read, agent) is None
            assert len(calls) == count
        finally:
            agent.close()
    asyncio.run(scenario())


def test_failed_roster_handoff_reports_only_bounded_reason_and_stage():
    def change(value, club, person, calls):
        if club and not person:
            value.clear()
            value.update(status='unavailable', reason='producer_timeout', producer_diagnostics={
                'schema': 'fa-reader-diagnostics/1', 'stage': 'team', 'elapsed_ms': 20001,
                'private_path': 'SECRET_DO_NOT_RETURN'})
    async def scenario():
        reader, result, calls, contexts, *_rest, agent = await run_scenario(change)()
        try:
            assert result['source_status'] == 'general_knowledge'
            assert result['reader_handoff'] == {'reason': 'team_identity_or_freshness',
                'reader_reason': 'producer_timeout', 'stage': 'team', 'elapsed_ms': 20001}
            assert 'SECRET_DO_NOT_RETURN' not in str(result)
            assert not contexts[-1].get('facts')
        finally:
            agent.close()
    asyncio.run(scenario())


def test_provider_failure_preserves_same_conversation_keeper_followup():
    """Synthetic first-turn provider failure, not live model/game acceptance."""
    async def scenario():
        reader, _, calls, contexts, _, read, body, agent = await run_scenario(fail_first=True)()
        seen = []
        try:
            assert not reader.lock.locked()
            async def succeeding(message, conversation, context, **kwargs):
                seen.append((message, context))
                return {'reply': '只按刚读到的两位门将属性比较。', 'conversation_id': conversation}
            agent._chat = succeeding
            result = await reader.reply(body('你看一下吧'), read, agent)
            assert result['status'] == 'partial'
            assert '你推荐我们选择哪个门将呢' in seen[-1][0]
            assert '本轮用户补充：你看一下吧' in seen[-1][0]
            assert len(seen[-1][1]['facts']['player_candidates']) == 2
            assert not reader.lock.locked()
            assert sum(person != 0 for _, person in calls) == 2
        finally:
            agent.close()
    asyncio.run(scenario())


def test_expired_cached_roster_is_refreshed_before_keeper_followup():
    """Cache age is not proof of capture freshness after a slow model/read."""
    async def scenario():
        reader, _, calls, _, _, read, body, agent = await run_scenario(fail_first=True)()
        try:
            state = next(iter(reader.sessions.values()))
            state['team'] = deepcopy(state['team'])
            state['team']['snapshot']['capturedAt'] = '2000-01-01T00:00:00Z'
            # Local cache insertion was recent, but its underlying observation is not.
            before = len(calls)
            result = await reader.reply(body('你看一下吧'), read, agent)
            assert calls[before:before + 2] == [(0, 0), (34, 0)]
            assert result['status'] == 'partial'
            assert len(result['context']['facts']['player_candidates']) == 2
        finally:
            agent.close()
    asyncio.run(scenario())


def test_failed_initial_revalidation_keeps_only_question_for_general_followup():
    async def scenario():
        reader, _, _, _, _, _, body, agent = await run_scenario(fail_first=True)()
        captured = []
        async def unavailable(*args):
            return {'reason': 'producer_timeout', 'snapshot': None}
        async def chat(message, conversation, context, **kwargs):
            captured.append((message, context))
            return {'reply': '先说选门将的思路。', 'conversation_id': conversation}
        agent._chat = chat
        try:
            result = await reader.reply(body('你看一下吧'), unavailable, agent)
            assert result['status'] == 'general_advice'
            assert result['reader_handoff']['reason'] == 'initial_identity_or_freshness'
            assert '你推荐我们选择哪个门将呢' in captured[-1][0]
            assert not captured[-1][1].get('facts')
            assert not reader.sessions  # No stale identity/roster is retained.
        finally:
            agent.close()
    asyncio.run(scenario())
