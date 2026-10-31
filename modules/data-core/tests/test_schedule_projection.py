"""Invented fixtures only: no user's captured schedule or raw samples."""
from copy import deepcopy
import json

import pytest

from football_assistant_agent.ui_advice import prepare_ui_advice
from football_assistant_data.schedule_projection import FOCUS_ROOT, TITLE_PATH, ROW_PREFIX, COLUMNS
from test_ui_advice import snapshot
from test_display_profile import NOW


def schedule_snapshot(count=10):
    data = snapshot()
    template = deepcopy(data['facts'][0])
    values = {TITLE_PATH: '赛程安排', 'focus/99': 'TEST UNRELATED PRIVATE UI'}
    for i in range(count):
        row = {'date_display': f'28-7-{i+9}', 'opponent_display': f'<link="{i+1}"><style="Norml">TEST Opponent {i}</style></link>',
               'home_away_display': '主' if i % 2 == 0 else '客',
               'competition_display': '<color=#AABBCC>TEST Cup</color>'}
        values.update({ROW_PREFIX + str(i) + COLUMNS[key]: value for key, value in row.items()})
    data['facts'] = [{**deepcopy(template), 'entity_id': path, 'value': value} for path, value in values.items()]
    data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
        field='capture_metrics', value=json.dumps(dict(path_scope='focus_relative',
        identity_scope='capture_local_ui_path', focus_requested=True, focus_resolved=True, focus_root_path=FOCUS_ROOT))))
    recount(data)
    return data


def recount(data):
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])


def projection(data=None):
    return prepare_ui_advice('schedule_analysis', data or schedule_snapshot(), now=NOW)['schedule_projection']


def edit(data, path, value):
    next(f for f in data['facts'] if f['entity_id'] == path)['value'] = value


def test_ten_rows_four_columns_with_strict_provenance_and_unknown_century():
    result = projection()
    assert result['status'] == 'experimental_ui_schedule'
    assert result['production_ready'] is False and result['business_identity_known'] is False
    assert [row['row_index'] for row in result['rows']] == list(range(10))
    first = result['rows'][0]
    assert first['opponent_display'] == 'TEST Opponent 0'
    assert first['competition_display'] == 'TEST Cup'
    assert first['date_display'] == '28-7-9'
    assert first['date_components'] == dict(year_two_digits=28, month=7, day=9)
    assert first['date_iso'] is None and first['kickoff'] is None
    for key, suffix in COLUMNS.items():
        provenance = first['field_provenance'][key]
        assert provenance['ui_path'] == ROW_PREFIX + '0' + suffix
        assert provenance['focus_root_path'] == FOCUS_ROOT
        assert provenance['event_id'] == 'TEST-event-A'
        assert provenance['capture_text_sha256']
    assert 'TEST UNRELATED' not in str(result)
    assert prepare_ui_advice('player_info', schedule_snapshot(), now=NOW)['schedule_projection'] is None


@pytest.mark.parametrize('value', ['28-2-30', '27-2-29', '2028-7-9', '28-13-1', '28-7-09', '9-7-28'])
def test_malformed_dates_clear_all_rows(value):
    data = schedule_snapshot()
    edit(data, ROW_PREFIX + '0' + COLUMNS['date_display'], value)
    result = projection(data)
    assert result['status'] == 'unavailable' and result['rows'] == []


@pytest.mark.parametrize('key,value', [('opponent_display', '<script>TEST</script>'),
    ('competition_display', '<link="1">TEST</style>'), ('home_away_display', 'H'),
    ('home_away_display', '主场')])
def test_unknown_markup_and_locale_fail_closed(key, value):
    data = schedule_snapshot()
    edit(data, ROW_PREFIX + '0' + COLUMNS[key], value)
    assert projection(data)['rows'] == []


def test_missing_column_omits_only_that_row_never_fills_adjacent():
    data = schedule_snapshot()
    data['facts'] = [f for f in data['facts'] if f['entity_id'] != ROW_PREFIX + '0' + COLUMNS['opponent_display']]
    recount(data)
    assert [row['row_index'] for row in projection(data)['rows']] == list(range(1, 10))


@pytest.mark.parametrize('change', ['duplicate', 'title', 'build', 'root', 'platform', 'mixed', 'event', 'stale', 'later'])
def test_profile_and_envelope_rejections(change):
    data = schedule_snapshot()
    if change == 'duplicate': data['facts'].append(deepcopy(data['facts'][0])); recount(data)
    elif change == 'title': edit(data, TITLE_PATH, 'Schedule')
    elif change == 'build':
        data['source_status']['game']['build'] = 'TEST other'
        data['observation']['game']['build'] = 'TEST other'
        for fact in data['facts']:
            if 'game' in fact: fact['game']['build'] = 'TEST other'
    elif change == 'root': data['facts'][-1]['value'] = data['facts'][-1]['value'].replace(FOCUS_ROOT, 'panel0/1')
    elif change == 'platform':
        data['observation']['source']['platform'] = 'TEST other'
        for fact in data['facts']:
            if 'source' in fact: fact['source']['platform'] = 'TEST other'
    elif change == 'mixed': data['facts'][1]['entity_id'] = 'panel0/99'
    elif change == 'event': data['facts'][0]['source_event_id'] = 'TEST other'
    elif change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    elif change == 'later': data['later_source_status'] = {**data['source_status'], 'event_id': 'TEST other'}
    result = prepare_ui_advice('schedule_analysis', data, now=NOW)
    assert result['schedule_projection'] is None or result['schedule_projection']['rows'] == []


def test_projection_fingerprint_changes_on_build_or_text_not_capture_time():
    data = schedule_snapshot()
    original = projection(data)['projection_sha256']
    edit(data, ROW_PREFIX + '0' + COLUMNS['opponent_display'], 'TEST changed')
    assert projection(data)['projection_sha256'] != original


def test_service_narrows_schedule_model_payload_and_clears_projection_on_refresh(monkeypatch):
    import asyncio
    from football_assistant_agent import service
    real_prepare = prepare_ui_advice
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: real_prepare(c, s, now=NOW))
    captured = {}
    async def chat(message, conversation_id, context, **kwargs):
        captured['context'] = context
        return {'reply': 'TEST conditional advice'}
    agent = service.AgentService(None, None)
    monkeypatch.setattr(agent, '_chat', chat)
    data = schedule_snapshot()
    response = asyncio.run(agent.ui_advice('TEST', None, 'schedule_analysis', data, refresh=lambda: data))
    assert response['status'] == 'generated'
    assert 'TEST UNRELATED' not in str(captured['context'])
    assert 'TEST Opponent 0' in str(captured['context'])
    assert 'evidence' not in captured['context']['ui_evidence']
    changed = deepcopy(data)
    edit(changed, ROW_PREFIX + '0' + COLUMNS['opponent_display'], 'TEST changed')
    response = asyncio.run(agent.ui_advice('TEST', None, 'schedule_analysis', data, refresh=lambda: changed))
    assert response['status'] == 'blocked' and response['schedule_projection'] is None
    assert response['evidence'] == []


def test_schedule_profile_failure_never_calls_model_or_reads_configuration():
    import asyncio
    from football_assistant_agent.service import AgentService
    class Never:
        def __getattr__(self, name):
            pytest.fail('unexpected configuration/provider access: ' + name)
    # Fresh snapshot supplied via patched clock below; absent profile must block for free.
    import unittest.mock
    with unittest.mock.patch('football_assistant_agent.service.prepare_ui_advice',
            side_effect=lambda c, s: prepare_ui_advice(c, s, now=NOW)):
        response = asyncio.run(AgentService(Never(), Never()).ui_advice(
            'TEST schedule', None, 'schedule_analysis', snapshot()))
    assert response['status'] == 'blocked'
    assert response['reasons'] == ['schedule_profile_unavailable']
    assert response['schedule_projection'] is None and response['evidence'] == []


def test_read_only_schedule_preview_is_authenticated_and_model_free(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_agent import ui_advice
    from test_reader import settings, AUTH
    monkeypatch.setattr(ui_advice, 'prepare_ui_advice',
                        lambda c, s: prepare_ui_advice(c, s, now=NOW))
    app = create_app(settings(tmp_path), enable_agent=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/schedule').status_code == 401
        assert client.get('/v1/reader/schedule', headers=AUTH).json()['status'] == 'unavailable'
        monkeypatch.setattr(app.state.observations, 'reader_snapshot', lambda *args: schedule_snapshot())
        result = client.get('/v1/reader/schedule', headers=AUTH).json()
        assert result['status'] == 'experimental_ui_schedule'
        assert len(result['schedule_projection']['rows']) == 10
        assert result['production_ready'] is False
        assert 'TEST UNRELATED' not in str(result)
