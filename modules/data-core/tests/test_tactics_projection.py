"""Invented fixtures only; no real captures and no provider traffic."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from football_assistant_agent.ui_advice import prepare_ui_advice
from football_assistant_data.tactics_projection import (
    PANEL_ROOT, TITLE_PATH, STYLE_PATH, MENTALITY_PATH, LABEL_PATH,
)
from test_ui_advice import snapshot
from test_display_profile import NOW

DISPLAY_FIELDS = {'formation_display', 'style_display', 'mentality_display'}


def recount(data):
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])


def tactics_snapshot():
    data = snapshot()
    template = deepcopy(data['facts'][0])
    values = {TITLE_PATH: '积极进取4-3-3 后腰 拉边 - 控制球权',
              STYLE_PATH: '控制球权', MENTALITY_PATH: '积极进取', LABEL_PATH: '队形',
              'panel0/99': 'TEST UNRELATED PRIVATE UI'}
    data['facts'] = [{**deepcopy(template), 'entity_id': path, 'value': value}
                     for path, value in values.items()]
    recount(data)
    return data


def edit(data, path, value):
    next(f for f in data['facts'] if f['entity_id'] == path)['value'] = value


def projection(data=None):
    return prepare_ui_advice('tactical_analysis', data or tactics_snapshot(), now=NOW)['tactics_projection']


def test_three_display_fields_are_partial_ui_not_native_entities():
    result = projection()
    assert result['status'] == 'experimental_ui_tactics'
    assert result['formation_display'] == '4-3-3 后腰 拉边'
    assert result['style_display'] == '控制球权'
    assert result['mentality_display'] == '积极进取'
    assert result['production_ready'] is False
    assert result['business_identity_known'] is False
    assert all(result[field] is None for field in ('lineup', 'roles', 'instructions'))
    assert result['projection_sha256']
    for field in DISPLAY_FIELDS:
        ref = result['field_provenance'][field]
        assert ref['source'] == 'ui'
        assert ref['path_scope'] == 'panel_absolute'
        assert ref['event_id'] == 'TEST-event-A'
        assert ref['capture_text_sha256']
    assert result['field_provenance']['formation_display']['ui_path'] == TITLE_PATH
    assert result['field_provenance']['style_display']['ui_path'] == STYLE_PATH
    assert result['field_provenance']['mentality_display']['ui_path'] == MENTALITY_PATH
    assert 'TEST UNRELATED' not in str(result)
    assert prepare_ui_advice('player_info', tactics_snapshot(), now=NOW)['tactics_projection'] is None


def test_only_observed_zero_width_space_is_removed_and_raw_stays_local():
    data = tactics_snapshot()
    raw_title = '积\u200b极进取4-3-3 后腰 拉边 - 控制球权\u200b'
    edit(data, TITLE_PATH, raw_title)
    edit(data, MENTALITY_PATH, '积\u200b极进取')
    prepared = prepare_ui_advice('tactical_analysis', data, now=NOW)
    assert prepared['tactics_projection']['formation_display'] == '4-3-3 后腰 拉边'
    assert any(item['text'] == raw_title for item in prepared['evidence'])
    assert prepared['tactics_projection']['raw_texts']['title'] == raw_title


@pytest.mark.parametrize('formation', ['4-4-2', '3-3-4', '5-5', '2-2-2-2-2', '4-2-3-1 后腰'])
def test_reasonable_outfield_formations_preserve_exact_descriptor(formation):
    data = tactics_snapshot()
    edit(data, TITLE_PATH, '积极进取' + formation + ' - 控制球权')
    assert projection(data)['formation_display'] == formation


@pytest.mark.parametrize('title', [
    '积极进取 4-3-3 后腰 拉边 - 控制球权',
    '积极进取4-3-3 后腰 拉边-控制球权',
    '积极进取4-3-3 后腰  - 控制球权',
    '积极进取4-3-3 - 后腰 - 控制球权',
    '积极进取4-3-3 - - 控制球权',
    '积极进取4-3-3 2 - 控制球权',
    '平衡4-3-3 后腰 拉边 - 控制球权',
    '积极进取4-3-3 后腰 拉边 - TEST OTHER',
    '积极进取4-3-4 - 控制球权', '积极进取4-3-2 - 控制球权',
    '积极进取10 - 控制球权', '积极进取0-5-5 - 控制球权',
    '积极进取1-1-1-1-1-5 - 控制球权', '积极进取４-３-３ - 控制球权',
    '积极进取4–3–3 - 控制球权', '积极进取4-3-3\u200d - 控制球权',
    '积极进取4-3-3\nTEST - 控制球权',
    '<style="Norml">积极进取4-3-3 - 控制球权</style>',
])
def test_malformed_or_unmatched_titles_fail_closed(title):
    data = tactics_snapshot(); edit(data, TITLE_PATH, title)
    result = projection(data)
    assert result['status'] == 'unavailable'
    assert all(result.get(field) is None for field in DISPLAY_FIELDS)


@pytest.mark.parametrize('change', ['duplicate', 'label', 'missing', 'build', 'platform', 'scope',
    'event', 'stale', 'later', 'synthetic', 'session', 'incomplete'])
def test_profile_and_fresh_session_gate_rejects_invalid_capture(change):
    data = tactics_snapshot()
    if change == 'duplicate': data['facts'].append(deepcopy(data['facts'][0])); recount(data)
    elif change == 'label': edit(data, LABEL_PATH, 'Formation')
    elif change == 'missing': data['facts'] = data['facts'][1:]; recount(data)
    elif change == 'build':
        data['source_status']['game']['build'] = 'TEST-other'
        data['observation']['game']['build'] = 'TEST-other'
        for fact in data['facts']: fact['game']['build'] = 'TEST-other'
    elif change == 'platform':
        data['observation']['source']['platform'] = 'TEST-other'
        for fact in data['facts']: fact['source']['platform'] = 'TEST-other'
    elif change == 'scope':
        data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
            field='capture_metrics', value=json.dumps(dict(path_scope='focus_relative',
                focus_requested=True, focus_resolved=True, focus_root_path=PANEL_ROOT))))
        recount(data)
    elif change == 'event': data['facts'][0]['source_event_id'] = 'TEST-other'
    elif change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    elif change == 'later': data['later_source_status'] = {**data['source_status'], 'event_id': 'TEST-other'}
    elif change == 'synthetic': data['observation']['synthetic'] = True
    elif change == 'session': data['observation']['game']['session_id'] = 'TEST-other'
    elif change == 'incomplete': data['has_more'] = True
    result = projection(data)
    assert result is None or result['status'] == 'unavailable'


def test_projection_digest_detects_text_changes():
    data = tactics_snapshot(); original = projection(data)['projection_sha256']
    edit(data, TITLE_PATH, '积极进取4-4-2 - 控制球权')
    assert projection(data)['projection_sha256'] != original


def test_unmatched_tactics_profile_is_free_and_never_reads_model_config(monkeypatch):
    from football_assistant_agent import service
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    class Never:
        def __getattr__(self, name): pytest.fail('unexpected provider/config access: ' + name)
    response = asyncio.run(service.AgentService(Never(), Never()).ui_advice(
        'TEST', None, 'tactical_analysis', snapshot()))
    assert response['status'] == 'blocked'
    assert response['evidence'] == [] and response['tactics_projection'] is None
    assert response['reasons'] == ['tactics_profile_unavailable']


def test_outbound_whitelist_excludes_all_provenance_and_future_metadata(monkeypatch):
    from football_assistant_agent import service
    data = tactics_snapshot()
    prepared = prepare_ui_advice('tactical_analysis', data, now=NOW)
    sentinel = 'TEST FORBIDDEN PRIVATE METADATA'
    prepared['provenance']['session_id'] = sentinel
    prepared['limitations'] = [sentinel]
    for key in ('field_provenance', 'future_metadata', 'raw_texts', 'profile_id'):
        prepared['tactics_projection'][key] = sentinel
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda *args: prepared)
    captured = {}
    async def chat(message, conversation_id, context, **kwargs):
        captured.update(context=context)
        return {'reply': 'TEST conditional advice'}
    agent = service.AgentService(None, None); monkeypatch.setattr(agent, '_chat', chat)
    response = asyncio.run(agent.ui_advice('TEST', None, 'tactical_analysis', data))
    context = captured['context']
    assert set(context) == {'source_status', 'ui_evidence'}
    assert set(context['ui_evidence']) == {'tactics_projection', 'limitations'}
    assert set(context['ui_evidence']['tactics_projection']) == DISPLAY_FIELDS
    assert all(type(value) is str for value in context['ui_evidence']['tactics_projection'].values())
    encoded = json.dumps(context)
    for forbidden in (sentinel, 'TEST-session', 'TEST-event-A', PANEL_ROOT, 'TEST UNRELATED',
                      'captured_at', 'session_id', 'ui_path', 'sha256', 'adapter', 'raw_texts'):
        assert forbidden not in encoded
    assert response['tactics_projection']['field_provenance'] == sentinel


def test_refresh_changed_or_expired_clears_projected_fields(monkeypatch):
    from football_assistant_agent import service
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    async def chat(*args, **kwargs): return {'reply': 'TEST advice'}
    agent = service.AgentService(None, None); monkeypatch.setattr(agent, '_chat', chat)
    data = tactics_snapshot()
    response = asyncio.run(agent.ui_advice('TEST', None, 'tactical_analysis', data, refresh=lambda: data))
    assert response['status'] == 'generated'
    changed_text = deepcopy(data)
    edit(changed_text, TITLE_PATH, '积极进取4-4-2 - 控制球权')
    expired = deepcopy(data)
    expired['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    for changed in (changed_text, expired):
        response = asyncio.run(agent.ui_advice('TEST', None, 'tactical_analysis', data, refresh=lambda: changed))
        assert response['status'] == 'blocked'
        assert response['tactics_projection'] is None and response['evidence'] == []


def test_reader_tactics_preview_is_authenticated_model_free(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_agent import ui_advice
    from test_reader import settings, AUTH
    monkeypatch.setattr(ui_advice, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    app = create_app(settings(tmp_path), enable_agent=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/tactics').status_code == 401
        assert client.get('/v1/reader/tactics', headers=AUTH).json()['status'] == 'unavailable'
        monkeypatch.setattr(app.state.observations, 'reader_snapshot', lambda *args: tactics_snapshot())
        result = client.get('/v1/reader/tactics', headers=AUTH).json()
        assert result['status'] == 'experimental_ui_tactics'
        assert result['tactics_projection']['formation_display'] == '4-3-3 后腰 拉边'
        assert result['production_ready'] is False
        assert 'TEST UNRELATED' not in str(result)


def test_provider_header_is_random_not_conversation_or_game_identity(monkeypatch):
    from football_assistant_agent import service
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    calls = []
    class Store:
        def reserve_model_request(self, *args): return True
    class Client:
        def __init__(self, **kwargs): calls.append(kwargs['default_headers'])
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Agent:
        def __init__(self, *args, **kwargs): pass
        async def run(self, message, **kwargs):
            assert 'TEST-session' not in message and 'TEST-conversation-private' not in message
            assert 'field_provenance' not in message
            return SimpleNamespace(output='TEST advice')
    monkeypatch.setattr(service, 'AsyncOpenAI', Client)
    monkeypatch.setattr(service, 'OpenAICompatibleProvider', lambda *a, **k: object())
    monkeypatch.setattr(service, 'OpenAIChatModel', lambda *a, **k: object())
    monkeypatch.setattr(service, 'Agent', Agent)
    config = SimpleNamespace(model_configured=True, model_budget_id='TEST', model_request_limit=2,
        api_key='TEST', base_url='http://invalid.test', model_timeout=1, model='TEST',
        max_output_tokens=10, model_extra_body={})
    agent = service.AgentService(config, Store())
    for _ in range(2):
        result = asyncio.run(agent.ui_advice('TEST', 'TEST-conversation-private',
                                             'tactical_analysis', tactics_snapshot()))
        assert result['status'] == 'generated'
    identifiers = [call['x-opencode-session'] for call in calls]
    assert identifiers[0] != identifiers[1]
    assert all(UUID(value).version == 4 for value in identifiers)


@pytest.mark.parametrize('path,value', [
    (STYLE_PATH, '控制球权\u200c'), (MENTALITY_PATH, '积极进取\ufeff'),
    (LABEL_PATH, '队形\u2060'), (STYLE_PATH, '<style="Norml">控制球权</style>'),
    (MENTALITY_PATH, '积极进取 '), (LABEL_PATH, ' 队形'),
])
def test_other_invisibles_markup_and_whitespace_are_not_silently_normalized(path, value):
    data = tactics_snapshot(); edit(data, path, value)
    result = projection(data)
    assert result is None or result['status'] == 'unavailable'
