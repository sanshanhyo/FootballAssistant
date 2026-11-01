"""Synthetic display fixtures only; no provider requests or game events."""
from copy import deepcopy
import json

import pytest

from football_assistant_agent.ui_advice import prepare_ui_advice, prepare_ui_change_preview
from football_assistant_data import ui_change_preview
from test_display_profile import NOW
from test_ui_advice import snapshot
from test_schedule_projection import schedule_snapshot, ROW_PREFIX, COLUMNS
from test_tactics_projection import tactics_snapshot, TITLE_PATH
from test_current_page_attributes_projection import attributes_snapshot, row_path

READY_KEYS = {'status', 'kind', 'source', 'synthetic', 'partial', 'production_ready',
              'session_id', 'event_id', 'captured_at', 'display_sha256', 'scope_sha256'}
UNAVAILABLE = dict(status='unavailable', source='ui', synthetic=False, partial=True, production_ready=False)


def preview(data):
    return prepare_ui_change_preview(data, now=NOW)


def edit(data, path, value):
    next(fact for fact in data['facts'] if fact['entity_id'] == path)['value'] = value


def recount(data):
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])


@pytest.mark.parametrize('factory,kind', [(schedule_snapshot, 'schedule'), (tactics_snapshot, 'tactics'),
                                        (attributes_snapshot, 'current_page_attributes')])
def test_exact_fingerprint_only_whitelist_for_each_verified_profile(factory, kind):
    result = preview(factory())
    assert set(result) == READY_KEYS and result['kind'] == kind
    assert result['status'] == 'ready'
    assert result['session_id'] == 'TEST-session' and result['event_id'] == 'TEST-event-A'
    assert result['source'] == 'ui' and result['synthetic'] is False
    assert result['production_ready'] is False and result['partial'] is True
    assert all(len(result[field]) == 64 and set(result[field]) <= set('0123456789abcdef')
               for field in ('display_sha256', 'scope_sha256'))
    encoded = json.dumps(result)
    for forbidden in ('TEST UNRELATED', 'ui_path', 'field_provenance', 'raw_text', 'panel0', 'focus/',
                      'opponent_display', 'formation_display', 'label_display', 'identity'):
        assert forbidden not in encoded


@pytest.mark.parametrize('factory,path,value', [
    (schedule_snapshot, ROW_PREFIX + '0' + COLUMNS['opponent_display'], 'TEST changed opponent'),
    (tactics_snapshot, TITLE_PATH, '积极进取4-4-2 - 控制球权'),
    (attributes_snapshot, row_path(), '7'),
])
def test_display_changes_change_only_display_digest(factory, path, value):
    data = factory(); before = preview(data)
    edit(data, path, value)
    after = preview(data)
    assert after['display_sha256'] != before['display_sha256']
    assert after['scope_sha256'] == before['scope_sha256']


@pytest.mark.parametrize('factory', [schedule_snapshot, tactics_snapshot, attributes_snapshot])
def test_new_event_and_unrelated_raw_ui_do_not_create_display_change(factory):
    data = factory(); before = preview(data)
    data['source_status']['event_id'] = data['snapshot_event_id'] = data['observation']['event_id'] = 'TEST-event-B'
    for fact in data['facts']:
        if 'source_event_id' in fact: fact['source_event_id'] = 'TEST-event-B'
        if 'TEST UNRELATED' in str(fact.get('value')): fact['value'] = 'TEST PRIVATE DIFFERENT NAVIGATION'
    after = preview(data)
    assert after['event_id'] == 'TEST-event-B'
    assert after['display_sha256'] == before['display_sha256']
    assert after['scope_sha256'] == before['scope_sha256']
    assert 'NAVIGATION' not in json.dumps(after)


def test_schedule_display_row_order_is_not_a_game_event():
    data = schedule_snapshot(); before = preview(data)
    for fact in data['facts']:
        for old, new in [('0', '1'), ('1', '0')]:
            prefix = ROW_PREFIX + old + '/'
            if fact['entity_id'].startswith(prefix):
                fact['entity_id'] = ROW_PREFIX + new + '/' + fact['entity_id'][len(prefix):]
                break
    assert preview(data)['display_sha256'] == before['display_sha256']


def test_new_session_is_exposed_for_client_reset_not_folded_into_content_identity():
    data = tactics_snapshot(); before = preview(data)
    data['source_status']['game']['session_id'] = 'TEST-session-B'
    data['observation']['game']['session_id'] = 'TEST-session-B'
    for fact in data['facts']:
        if 'game' in fact: fact['game']['session_id'] = 'TEST-session-B'
    after = preview(data)
    assert after['session_id'] == 'TEST-session-B'
    assert after['display_sha256'] == before['display_sha256']
    assert after['scope_sha256'] == before['scope_sha256']


@pytest.mark.parametrize('change', ['synthetic', 'stale', 'future', 'mismatch', 'incomplete', 'duplicate', 'build', 'unknown'])
def test_invalid_capture_or_no_profile_has_no_identifiers_or_digests(change):
    data = tactics_snapshot()
    if change == 'synthetic': data['observation']['synthetic'] = True
    elif change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    elif change == 'future': data['source_status']['last_seen_at'] = '2099-01-01T00:00:00Z'
    elif change == 'mismatch': data['facts'][0]['source_event_id'] = 'TEST-other'
    elif change == 'incomplete': data['has_more'] = True
    elif change == 'duplicate': data['facts'].append(deepcopy(data['facts'][0])); recount(data)
    elif change == 'build':
        data['source_status']['game']['build'] = data['observation']['game']['build'] = 'TEST-other'
        for fact in data['facts']:
            if 'game' in fact: fact['game']['build'] = 'TEST-other'
    elif change == 'unknown': data = snapshot()
    assert preview(data) == UNAVAILABLE


def test_ambiguous_profile_matches_fail_closed(monkeypatch):
    monkeypatch.setattr(ui_change_preview, 'project_validated_schedule', lambda *a, **k: {
        'status': 'experimental_ui_schedule', 'profile_id': 'TEST', 'rows': []})
    assert preview(tactics_snapshot()) == UNAVAILABLE


def test_fingerprint_ignores_poisoned_projection_metadata(monkeypatch):
    real = ui_change_preview.project_validated_tactics
    before = preview(tactics_snapshot())
    def poisoned(*args, **kwargs):
        result = real(*args, **kwargs)
        for field in ('raw_texts', 'field_provenance', 'projection_sha256', 'limitations', 'future_metadata'):
            result[field] = 'TEST PRIVATE POISON'
        return result
    monkeypatch.setattr(ui_change_preview, 'project_validated_tactics', poisoned)
    after = preview(tactics_snapshot())
    assert after == before and 'POISON' not in json.dumps(after)


def test_full_capture_used_even_when_model_evidence_prefix_omits_projection():
    data = attributes_snapshot()
    template = deepcopy(data['facts'][0])
    data['facts'] = [{**deepcopy(template), 'entity_id': f'focus/99/{i}', 'value': 'x' * 900}
                     for i in range(25)] + data['facts']
    recount(data)
    assert prepare_ui_advice('player_info', data, now=NOW)['evidence_truncated'] is True
    assert preview(data)['kind'] == 'current_page_attributes'


@pytest.mark.parametrize('capability', ['player_info', 'schedule_analysis', 'tactical_analysis', 'transfer_analysis'])
def test_default_advice_payload_has_no_change_preview(capability):
    result = prepare_ui_advice(capability, tactics_snapshot(), now=NOW)
    assert 'ui_change_preview' not in result
    assert 'display_sha256' not in json.dumps(result)


def test_authenticated_model_free_endpoint_reads_one_snapshot(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_agent import ui_advice
    from test_reader import settings, AUTH
    monkeypatch.setattr(ui_advice, 'prepare_ui_change_preview', lambda data: prepare_ui_change_preview(data, now=NOW))
    app = create_app(settings(tmp_path), enable_agent=False)
    calls = []
    def read(*args): calls.append(args); return tactics_snapshot()
    with TestClient(app, base_url='http://127.0.0.1') as client:
        monkeypatch.setattr(app.state.observations, 'reader_snapshot', read)
        assert client.get('/v1/reader/ui-change-preview').status_code == 401
        assert calls == []
        result = client.get('/v1/reader/ui-change-preview', headers=AUTH)
        assert result.status_code == 200 and result.json()['kind'] == 'tactics'
        assert len(calls) == 1 and set(result.json()) == READY_KEYS
        assert client.post('/v1/reader/ui-change-preview', headers=AUTH, json={}).status_code == 405


def test_attribute_identity_or_individual_advice_opt_in_never_becomes_notice_source(monkeypatch):
    real = ui_change_preview.project_validated_current_page_attributes
    for extra in ({'identity': 'TEST-player'}, {'individual_advice_allowed': True}):
        def altered(*args, **kwargs):
            return {**real(*args, **kwargs), **extra}
        monkeypatch.setattr(ui_change_preview, 'project_validated_current_page_attributes', altered)
        assert preview(attributes_snapshot()) == UNAVAILABLE
