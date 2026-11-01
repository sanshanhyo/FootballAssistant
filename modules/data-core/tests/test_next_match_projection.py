"""Invented UI fixtures; no game or provider traffic."""
import asyncio
from copy import deepcopy
import json
import pytest
from football_assistant_agent.ui_advice import prepare_ui_advice, prepare_ui_change_preview
from football_assistant_data.next_match_projection import (
    FOCUS_ROOT, TITLE_PATH, OPPONENT_PATH, COMPETITION_PATH, DISPLAY_FIELDS, LIMITATIONS)
from test_ui_advice import snapshot
from test_tactics_projection import recount
from test_display_profile import NOW


def next_match_snapshot():
    data = snapshot()
    template = data['facts'][0]
    values = {TITLE_PATH: '下一场比赛（2026-7-18）', OPPONENT_PATH: '测试对手', COMPETITION_PATH: '友谊赛'}
    data['facts'] = [{**deepcopy(template), 'entity_id': path, 'value': text} for path, text in values.items()]
    data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
        field='capture_metrics', value=json.dumps(dict(path_scope='focus_relative', focus_requested=True,
            focus_resolved=True, focus_root_path=FOCUS_ROOT))))
    recount(data)
    return data


def project(data=None):
    return prepare_ui_advice('schedule_analysis', data or next_match_snapshot(), now=NOW)['schedule_projection']


def test_three_fields_are_viewed_club_card_not_owned_team_or_complete_schedule():
    result = project()
    assert result['status'] == 'experimental_ui_next_match' and result['kind'] == 'next_match'
    assert result['date_display'] == '2026-7-18'
    assert result['opponent_display'] == '测试对手' and result['competition_display'] == '友谊赛'
    assert result['schedule_complete'] is False and result['production_ready'] is False
    assert all(result[k] is None for k in ('identity', 'managed_team', 'home_away_display', 'kickoff_time', 'fixture_id'))
    assert 'rows' not in result
    assert result['raw_texts']['date_display'] == '下一场比赛（2026-7-18）'
    assert result['field_provenance']['date_display']['ui_path'] == TITLE_PATH


@pytest.mark.parametrize('title', ['下一场比赛（2026-2-30）', '下一场比赛（2026-13-1）', '下一场比赛（2026-07-18）',
    '下一场比赛(2026-7-18)', '上一场比赛（2026-7-18）', '下一场比赛（26-7-18）', '下一场比赛（2026-7-18）尾巴'])
def test_full_title_exact_date_and_calendar_validation(title):
    data = next_match_snapshot(); data['facts'][0]['value'] = title
    assert project(data)['status'] == 'unavailable'


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'stale', 'session', 'scope', 'synthetic', 'build', 'platform', 'zwj'])
def test_strict_existing_ui_gate_and_profile_fail_closed(change):
    data = next_match_snapshot()
    if change == 'duplicate': data['facts'].append(deepcopy(data['facts'][0])); recount(data)
    if change == 'missing': data['facts'].pop(1); recount(data)
    if change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    if change == 'session': data['observation']['game']['session_id'] = 'OTHER'
    if change == 'scope': data['facts'][-1]['value'] = data['facts'][-1]['value'].replace(FOCUS_ROOT, 'panel0/0/6')
    if change == 'synthetic': data['observation']['synthetic'] = True
    if change == 'build': data['source_status']['game']['build'] = 'OTHER'
    if change == 'platform': data['observation']['source']['platform'] = 'OTHER'
    if change == 'zwj': data['facts'][1]['value'] += '\u200d'
    result = project(data)
    assert result is None or result['status'] == 'unavailable'


def test_only_zero_width_space_removed_and_raw_retained():
    data = next_match_snapshot()
    data['facts'][1]['value'] = '测试\u200b对手'
    result = project(data)
    assert result['opponent_display'] == '测试对手'
    assert result['raw_texts']['opponent_display'] == '测试\u200b对手'


def test_outbound_only_three_display_values_and_static_caveats(monkeypatch):
    from football_assistant_agent import service
    prepared = prepare_ui_advice('schedule_analysis', next_match_snapshot(), now=NOW)
    prepared['provenance']['session_id'] = 'PRIVATE_SENTINEL'
    prepared['schedule_projection']['future_metadata'] = 'PRIVATE_SENTINEL'
    prepared['schedule_projection']['limitations'] = ['PRIVATE_SENTINEL']
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda *args: prepared)
    captured = {}
    async def chat(message, conversation_id, context, **kwargs):
        captured.update(context)
        return {'reply': 'TEST 条件建议'}
    agent = service.AgentService(None, None)
    monkeypatch.setattr(agent, '_chat', chat)
    result = asyncio.run(agent.ui_advice('下场放不放', None, 'schedule_analysis', next_match_snapshot()))
    assert result['status'] == 'generated'
    assert set(captured['ui_evidence']) == {'next_match_projection', 'limitations'}
    assert set(captured['ui_evidence']['next_match_projection']) == set(DISPLAY_FIELDS)
    assert captured['ui_evidence']['limitations'] == LIMITATIONS
    for text in ('PRIVATE_SENTINEL', 'TEST-session', 'focus/', 'captured_at', 'sha256', 'raw_texts'):
        assert text not in json.dumps(captured)


def test_refresh_discards_generated_reply_on_changed_card_and_missing_profile_calls_no_model(monkeypatch):
    from football_assistant_agent import service
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    agent = service.AgentService(None, None)
    calls = []
    async def chat(*args, **kwargs):
        calls.append(1)
        return {'reply': 'TEST GENERATED'}
    monkeypatch.setattr(agent, '_chat', chat)
    data = next_match_snapshot(); changed = deepcopy(data); changed['facts'][1]['value'] = '另一测试对手'
    response = asyncio.run(agent.ui_advice('下场放不放', None, 'schedule_analysis', data, refresh=lambda: changed))
    assert response['status'] == 'blocked' and response['schedule_projection'] is None
    assert 'TEST GENERATED' not in str(response)
    response = asyncio.run(agent.ui_advice('下场放不放', None, 'schedule_analysis', snapshot()))
    assert response['status'] == 'blocked' and len(calls) == 1


def test_preview_auth_and_explicit_kind(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_agent import ui_advice
    from test_reader import settings, AUTH
    monkeypatch.setattr(ui_advice, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    app = create_app(settings(tmp_path), enable_agent=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/schedule').status_code == 401
        monkeypatch.setattr(app.state.observations, 'reader_snapshot', lambda *args: next_match_snapshot())
        result = client.get('/v1/reader/schedule', headers=AUTH).json()
        assert result['kind'] == 'next_match' and result['schedule_complete'] is False
        assert result['status'] == 'experimental_ui_next_match'


def test_detector_kind_distinct_and_value_free():
    result = prepare_ui_change_preview(next_match_snapshot(), now=NOW)
    assert result['status'] == 'ready' and result['kind'] == 'next_match'
    assert '测试对手' not in json.dumps(result, ensure_ascii=False)
    assert 'focus/' not in json.dumps(result)


def test_missing_label_like_text_does_not_become_an_opponent():
    data = next_match_snapshot(); data['facts'][1]['value'] = '---'
    assert project(data)['status'] == 'unavailable'


def test_fixed_control_profile_can_confirm_new_card_scope(tmp_path):
    from football_assistant_data.ui_capture_control import UiCaptureController
    from test_display_profile import STAMP
    from datetime import timedelta
    from capture_control_fixture import memory_control
    controller, host = memory_control()
    root = controller.root
    response = controller.access(next_match_snapshot(), 'next_match', now=NOW - timedelta(seconds=1))
    assert response['status'] == 'pending'
    request = json.loads((root / 'control/ui-capture.json').read_text())
    assert request['focus_path'] == FOCUS_ROOT
    (root / 'diagnostics/ui-capture-status.json').write_text(json.dumps(dict(**host,
        applied_sequence=response['sequence'], focus_path=FOCUS_ROOT, focus_resolved=True, applied_at=NOW.isoformat())))
    fresh = json.loads(json.dumps(next_match_snapshot()).replace(STAMP, NOW.isoformat()))
    assert controller.access(fresh, now=NOW)['status'] == 'ready'


CARD_WRAPPER = '<color="#FFFFFF"><link="0"><style="Norml">{}</style></link></color>'


def test_exact_observed_card_wrapper_keeps_display_only_and_raw_local(monkeypatch):
    from football_assistant_agent import service
    data = next_match_snapshot()
    data['facts'][0]['value'] = '下一场\u200b比赛（2026-7-18）'
    for index in (1, 2):
        data['facts'][index]['value'] = CARD_WRAPPER.format(data['facts'][index]['value'] + '\u200b')
    result = project(data)
    assert result['status'] == 'experimental_ui_next_match'
    assert result['opponent_display'] == '测试对手' and result['competition_display'] == '友谊赛'
    assert result['date_display'] == '2026-7-18'
    assert result['raw_texts']['opponent_display'] == data['facts'][1]['value']
    assert result['identity'] is None and result['managed_team'] is None and result['fixture_id'] is None
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    captured = {}
    async def chat(message, conversation_id, context, **kwargs):
        captured.update(context)
        return {'reply': 'TEST 条件建议'}
    agent = service.AgentService(None, None); monkeypatch.setattr(agent, '_chat', chat)
    response = asyncio.run(agent.ui_advice('下场放不放', None, 'schedule_analysis', data))
    assert response['status'] == 'generated'
    assert captured['ui_evidence']['next_match_projection'] == {
        'date_display': '2026-7-18', 'opponent_display': '测试对手', 'competition_display': '友谊赛'}
    assert '<' not in json.dumps(captured) and 'link=' not in json.dumps(captured)


@pytest.mark.parametrize('markup', [
    '<link="0"><style="Norml">测试</style></link>',
    CARD_WRAPPER.format('测试').replace('Norml', 'Normal'),
    CARD_WRAPPER.format('测试').replace('link="0"', 'link="1"'),
    CARD_WRAPPER.format('测试').replace('#FFFFFF', '#ffffff'),
    CARD_WRAPPER.format('测试').replace('color="#FFFFFF"', 'color="#FFFFFF" extra="x"'),
    CARD_WRAPPER.format('测试').replace('</style>', ''),
    CARD_WRAPPER.format('测试').replace('</style></link>', '</link></style>'),
    CARD_WRAPPER.format('<b>测试</b>'),
    CARD_WRAPPER.format('测试') + '<script>ignored</script>',
    'prefix' + CARD_WRAPPER.format('测试'),
    CARD_WRAPPER.format('测试') + 'suffix',
    CARD_WRAPPER.format(''),
    CARD_WRAPPER.format('测试\u200d'),
])
def test_unknown_malformed_or_expanded_markup_fails_closed(markup):
    data = next_match_snapshot(); data['facts'][1]['value'] = markup
    assert project(data)['status'] == 'unavailable'


def test_title_does_not_gain_markup_support():
    data = next_match_snapshot(); data['facts'][0]['value'] = CARD_WRAPPER.format(data['facts'][0]['value'])
    assert project(data)['status'] == 'unavailable'
