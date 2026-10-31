"""Offline delayed-model fixtures; no real provider or game access."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import pytest
from football_assistant_agent import service
from football_assistant_agent.ui_advice import prepare_ui_advice
from test_display_profile import NOW
from test_next_match_projection import next_match_snapshot
from test_schedule_projection import schedule_snapshot
from test_tactics_projection import tactics_snapshot
from test_ui_advice import snapshot


def new_capture(data):
    value = deepcopy(data)
    event = 'TEST-new-capture'
    stamp = (NOW + timedelta(seconds=2)).isoformat()
    value['source_status'].update(event_id=event, last_message_event_id=event,
        last_captured_at=stamp, observed_at=stamp, last_seen_at=stamp)
    value['observation'].update(event_id=event, captured_at=stamp, observed_at=stamp)
    value['snapshot_event_id'] = event
    for fact in value['facts']:
        if 'source_event_id' in fact: fact['source_event_id'] = event
        if 'captured_at' in fact: fact['captured_at'] = stamp
    return value


def run_delayed(monkeypatch, before, after, capability='schedule_analysis'):
    clock = [NOW]
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=clock[0]))
    agent = service.AgentService(None, None)
    calls = []
    async def delayed_chat(*args, **kwargs):
        calls.append(1)
        await asyncio.sleep(0)  # Yield as a real provider does, then advance the fixture clock.
        clock[0] = NOW + timedelta(seconds=3)
        return {'reply': 'TEST MOCK ADVICE'}
    monkeypatch.setattr(agent, '_chat', delayed_chat)
    result = asyncio.run(agent.ui_advice('下场放不放？', None, capability, before, refresh=lambda: after))
    assert calls == [1]
    return result


@pytest.mark.parametrize('factory,capability', [(next_match_snapshot, 'schedule_analysis'),
    (schedule_snapshot, 'schedule_analysis'), (tactics_snapshot, 'tactical_analysis')])
def test_new_event_and_timestamp_do_not_discard_unchanged_projected_display(monkeypatch, factory, capability):
    before = factory(); after = new_capture(before)
    if factory is next_match_snapshot:
        initial = prepare_ui_advice(capability, before, now=NOW)
        refreshed = prepare_ui_advice(capability, after, now=NOW + timedelta(seconds=3))
        assert initial['evidence'] == refreshed['evidence']
        assert initial['capture_text_sha256'] == refreshed['capture_text_sha256']
        # Reproduces the old false-positive: provenance-bearing hash changes every capture.
        assert initial['schedule_projection']['projection_sha256'] != refreshed['schedule_projection']['projection_sha256']
    result = run_delayed(monkeypatch, before, after, capability)
    assert result['status'] == 'generated'
    assert 'TEST MOCK ADVICE' in result['reply']
    assert result['provenance']['event_id'] == 'TEST-new-capture'


def test_unrelated_raw_text_and_allowed_markup_do_not_change_outbound_next_match_facts(monkeypatch):
    before = next_match_snapshot(); after = new_capture(before)
    after['facts'][1]['value'] = '<color="#FFFFFF"><link="0"><style="Norml">测试对手</style></link></color>'
    extra = deepcopy(after['facts'][0]); extra.update(entity_id='focus/99', value='TEST unrelated animation label')
    after['facts'].append(extra); after['facts_total'] += 1
    result = run_delayed(monkeypatch, before, after)
    assert result['status'] == 'generated'


@pytest.mark.parametrize('change', ['opponent', 'date', 'competition', 'session', 'scope', 'stale', 'unavailable'])
def test_actual_display_change_or_invalid_fresh_scope_still_discards_reply(monkeypatch, change):
    before = next_match_snapshot(); after = new_capture(before)
    if change == 'opponent': after['facts'][1]['value'] = '另一测试对手'
    if change == 'date': after['facts'][0]['value'] = '下一场比赛（2026-7-19）'
    if change == 'competition': after['facts'][2]['value'] = '测试联赛'
    if change == 'session':
        after['source_status']['game']['session_id'] = 'TEST-new-session'
        after['observation']['game']['session_id'] = 'TEST-new-session'
        for fact in after['facts']:
            if 'game' in fact: fact['game']['session_id'] = 'TEST-new-session'
    if change == 'scope': after['facts'][-1]['value'] = after['facts'][-1]['value'].replace('panel0', 'panel1')
    if change == 'stale': after['source_status']['last_seen_at'] = (NOW - timedelta(seconds=30)).isoformat()
    if change == 'unavailable': after['source_status']['availability'] = 'unavailable'
    result = run_delayed(monkeypatch, before, after)
    assert result['status'] == 'blocked'
    assert result['reasons'] == ['ui_changed_or_expired_during_generation']
    assert 'TEST MOCK ADVICE' not in result['reply']


def test_unprojected_ui_keeps_full_raw_text_fence(monkeypatch):
    before = snapshot(); after = new_capture(before)
    after['facts'][0]['value'] += ' TEST changed'
    result = run_delayed(monkeypatch, before, after, 'player_info')
    assert result['status'] == 'blocked'
