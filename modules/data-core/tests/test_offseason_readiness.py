"""Offline verified native fixtures through real API routes; no game or provider."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from football_assistant_data.app import create_app
from football_assistant_data import offseason_snapshot as reader
from football_assistant_data.offseason_readiness import OffseasonReadiness
from test_native_identity_projection import native_envelope
from test_reader import AUTH, settings
from test_windows_reader_onboarding import payload


@pytest.fixture
def configured(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'
    executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(executable))
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    return executable


def stub(monkeypatch, value):
    calls = []
    async def read(executable, club, person, *args, **kwargs):
        calls.append((club, person, args, kwargs))
        return reader.validate_snapshot(deepcopy(value["snapshot"]), require_current_producer=True) if value.get("status") == "partial" else deepcopy(value)
    monkeypatch.setattr(reader, 'read_offseason', read)
    return calls


def readiness(client):
    return client.get('/v1/reader/business/status', headers=AUTH).json()['offseason_readiness']


@pytest.mark.parametrize('enable_agent', [False, True])
def test_verified_onboarding_is_visible_without_another_read_or_business_promotion(tmp_path, monkeypatch, configured, enable_agent):
    value = native_envelope()
    calls = stub(monkeypatch, value)
    app = create_app(settings(tmp_path), enable_agent=enable_agent)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert readiness(client)['state'] == 'not_read'
        assert client.get('/v1/reader/onboarding-status?verify=true').status_code == 401
        assert calls == []
        verified = client.get('/v1/reader/onboarding-status?verify=true', headers=AUTH).json()
        assert verified['verified'] is True and verified['state'] == 'fresh_partial'
        partial = readiness(client)
        assert partial['schema'] == 'fa-offseason-readiness/1'
        assert partial['status'] == 'partial' and partial['producer_verified'] is True
        assert partial['scope'] == 'partial_native_query' and partial['production_ready'] is False
        assert partial['freshness'] == 'fresh' and partial['expires_at'] > partial['observed_at']
        assert partial['session_id'] == value['snapshot']['process']['sessionId']
        assert set(partial['observed_fields']) == {'game_date', 'current_manager', 'manager_club_candidates'}
        assert partial['capabilities']['player_info'] == {'ready': True, 'partial': True}
        assert all(not cap['ready'] for name, cap in partial['capabilities'].items() if name != 'player_info')
        for route in ('/v1/status', '/v1/reader/status'):
            status = client.get(route, headers=AUTH).json()
            assert status['source_status']['availability'] == 'partial'
            assert status['source_status']['connection_state'] == 'connected'
            assert status['source_status']['production_ready'] is False
            assert status['offseason_readiness'] == partial
        business = client.get('/v1/reader/business/status', headers=AUTH).json()
        assert business['production_ready'] is False and business['status'] == 'unavailable'
        assert all(not cap['ready'] for cap in business['capabilities'].values())
        assert app.state.business_snapshots.read()['snapshot'] is None
        assert app.state.observations.reader_snapshot()['facts'] == []
        assert client.get('/v1/reader/onboarding-status', headers=AUTH).json()['read'] is None
        assert len(calls) == 1
        encoded = json.dumps(partial)
        for forbidden in ('Synthetic manager', 'Synthetic club', 'Player 101', 'DO NOT SEND', 'gamePluginSha256', 'startedAt', 'reflexesRaw'):
            assert forbidden not in encoded
        assert not hasattr(app.state.offseason_readiness, '_snapshot')


def test_date_and_ambiguous_manager_candidates_do_not_unlock_player_info(tmp_path, monkeypatch, configured):
    value = native_envelope()
    value['snapshot'].pop('manager')
    calls = stub(monkeypatch, value)
    with TestClient(create_app(settings(tmp_path), enable_agent=False), base_url='http://127.0.0.1') as client:
        client.get('/v1/reader/onboarding-status?verify=true', headers=AUTH)
        partial = readiness(client)
        assert partial['status'] == 'partial'
        assert set(partial['observed_fields']) == {'game_date', 'manager_club_candidates'}
        assert all(not item['ready'] for item in partial['capabilities'].values())
        assert len(calls) == 1


def test_selectors_only_unlock_observed_team_player_and_tactic(tmp_path, monkeypatch, configured):
    value = native_envelope()
    value['snapshot'].pop('manager')
    calls = stub(monkeypatch, value)
    with TestClient(create_app(settings(tmp_path), enable_agent=False), base_url='http://127.0.0.1') as client:
        client.get('/v1/reader/offseason?club_uid=34&person_uid=101', headers=AUTH)
        partial = readiness(client)
        assert {'team_candidates', 'player_candidate', 'tactic_candidate'} <= set(partial['observed_fields'])
        assert partial['capabilities']['player_info']['ready'] is True
        assert partial['capabilities']['tactical_analysis']['ready'] is True
        assert partial['capabilities']['schedule_analysis']['ready'] is False
        assert partial['capabilities']['transfer_analysis']['ready'] is False
        # A later narrower read replaces, never unions in older selected facts.
        client.get('/v1/reader/offseason', headers=AUTH)
        assert all(not item['ready'] for item in readiness(client)['capabilities'].values())
        assert len(calls) == 2


def test_schedule_requires_fresh_valid_nonempty_explicit_range(tmp_path, monkeypatch, configured):
    value = native_envelope()
    value['snapshot']['calendar'] = {'status': 'partial', 'observedAt': value['snapshot']['capturedAt'],
        'fixtures': [{'date': '2026-02-08', 'opponentName': 'Fixture opponent', 'venue': 'unknown'}], 'unloaded': 2, 'unknown': 0}
    calls = stub(monkeypatch, value)
    with TestClient(create_app(settings(tmp_path), enable_agent=False), base_url='http://127.0.0.1') as client:
        client.get('/v1/reader/offseason?club_uid=34', headers=AUTH)
        assert readiness(client)['capabilities']['schedule_analysis']['ready'] is False
        path = '/v1/reader/offseason?club_uid=34&start=2026-02-01&end=2026-02-28'
        client.get(path, headers=AUTH)
        assert readiness(client)['capabilities']['schedule_analysis']['ready'] is True
        value['snapshot']['calendar']['fixtures'] = []
        client.get(path, headers=AUTH)
        assert readiness(client)['capabilities']['schedule_analysis']['ready'] is False
        assert len(calls) == 3


@pytest.mark.parametrize('reason', ['fm_not_running', 'no_data', 'unsupported_binary', 'read_failed'])
def test_latest_unavailable_read_clears_partial_and_all_capabilities(tmp_path, monkeypatch, configured, reason):
    value = native_envelope()
    stub(monkeypatch, value)
    with TestClient(create_app(settings(tmp_path), enable_agent=False), base_url='http://127.0.0.1') as client:
        client.get('/v1/reader/offseason?club_uid=34&person_uid=101', headers=AUTH)
        assert readiness(client)['status'] == 'partial'
        value.clear()
        value.update(reader.validate_snapshot(payload(reason, datetime.now(timezone.utc)), require_current_producer=True))
        client.get('/v1/reader/offseason', headers=AUTH)
        missing = readiness(client)
        assert missing['state'] == reason and missing['status'] == 'unavailable'
        assert missing['session_id'] is None and missing['observed_fields'] == []
        assert all(not cap['ready'] for cap in missing['capabilities'].values())
        assert client.get('/v1/status', headers=AUTH).json()['source_status']['availability'] == 'not_connected'


def test_consent_revocation_and_configuration_changes_never_resurrect_cached_state(tmp_path, monkeypatch, configured):
    calls = stub(monkeypatch, native_envelope())
    with TestClient(create_app(settings(tmp_path), enable_agent=False), base_url='http://127.0.0.1') as client:
        client.get('/v1/reader/offseason', headers=AUTH)
        assert readiness(client)['status'] == 'partial'
        monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '0')
        assert readiness(client)['state'] == 'consent_required'
        monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
        assert readiness(client)['status'] == 'unavailable'
        client.get('/v1/reader/offseason', headers=AUTH)
        monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'other.exe'))
        assert readiness(client)['state'] == 'configuration_changed'
        assert len(calls) == 2


def test_expiry_honors_oldest_used_field_and_monotonic_time(tmp_path, monkeypatch, configured):
    value = native_envelope()
    value['snapshot'].pop('manager')
    now = datetime.now(timezone.utc)
    value['snapshot']['team']['observedAt'] = (now - timedelta(seconds=29)).isoformat()
    tick = [0.0]
    current = [now]
    cache = OffseasonReadiness(clock=lambda: current[0], monotonic=lambda: tick[0])
    cache.complete(cache.begin(), value, configured, 34, 0)
    first = cache.status()
    assert first['capabilities']['player_info']['ready'] is True
    assert datetime.fromisoformat(first['expires_at']) <= now + timedelta(seconds=1)
    # Clock moving backward cannot preserve old readiness.
    current[0] -= timedelta(hours=1)
    tick[0] = 2.0
    assert cache.status()['state'] == 'stale'
    assert cache.status()['observed_fields'] == []


def test_invalid_identity_stale_input_and_late_completion_cannot_reenable(tmp_path, monkeypatch, configured):
    cache = OffseasonReadiness()
    valid = native_envelope()
    old = cache.begin()
    latest = cache.begin()
    cache.complete(latest, {'status': 'unavailable', 'reason': 'producer_busy'}, configured)
    cache.complete(old, valid, configured)
    assert cache.status()['state'] == 'producer_busy'
    for mutation in (lambda x: x['snapshot']['process'].update(sessionId='0' * 64),
                     lambda x: x['snapshot'].update(capturedAt=(datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()),
                     lambda x: x.update(producerVerified=False)):
        value = deepcopy(valid)
        mutation(value)
        cache.complete(cache.begin(), value, configured)
        assert cache.status()['status'] == 'unavailable'
        assert all(not cap['ready'] for cap in cache.status()['capabilities'].values())


def test_changed_process_replaces_fields_without_reusing_old_selection(tmp_path, monkeypatch, configured):
    cache = OffseasonReadiness()
    initial = native_envelope()
    cache.complete(cache.begin(), initial, configured, 34, 101)
    later = reader.validate_snapshot(payload(now=datetime.now(timezone.utc)), require_current_producer=True)
    cache.complete(cache.begin(), later, configured)
    status = cache.status()
    assert status['session_id'] != initial['snapshot']['process']['sessionId']
    assert status['observed_fields'] == ['game_date']
    assert all(not cap['ready'] for cap in status['capabilities'].values())


@pytest.mark.parametrize('route,extra', [('/v1/chat', {}), ('/v1/agent/business-advice', {'capability': 'player_info'})])
def test_chat_and_business_existing_reads_update_status_and_response(tmp_path, monkeypatch, configured, route, extra):
    calls = stub(monkeypatch, native_envelope())
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        async def reply(message, conversation, context, **kwargs):
            return {'reply': 'fixture answer', 'conversation_id': conversation}
        monkeypatch.setattr(app.state.agent, '_chat', reply)
        result = client.post(route, headers=AUTH, json={'message': '今天几号', **extra}).json()
        assert result['offseason_readiness']['status'] == 'partial'
        assert result['offseason_readiness'] == readiness(client)
        assert result['offseason_readiness']['production_ready'] is False
        assert len(calls) == 1
        assert app.state.business_snapshots.read()['snapshot'] is None


def test_reader_only_verification_never_imports_agent_or_provider(tmp_path, configured):
    fixture = tmp_path / 'input.json'
    fixture.write_text(json.dumps(native_envelope()))
    program = '''
import importlib.abc, json, sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in ('football_assistant_agent', 'pydantic_ai', 'openai'):
   raise AssertionError('reader status imported an agent/provider')
sys.meta_path.insert(0, Block())
from pathlib import Path
from football_assistant_data.reader import create_reader_app
from football_assistant_data import offseason_snapshot
from football_assistant_data.config import Settings
from fastapi.testclient import TestClient
folder = Path(sys.argv[1]); value = json.loads((folder/'input.json').read_text())
async def read(*args, **kwargs): return offseason_snapshot.validate_snapshot(value["snapshot"], require_current_producer=True)
offseason_snapshot.read_offseason = read
with TestClient(create_reader_app(Settings(data_dir=folder/'reader', runtime_file=folder/'reader/runtime.json', token='test')),base_url='http://127.0.0.1') as client:
 headers={'Authorization':'Bearer test'}
 assert client.get('/v1/reader/onboarding-status?verify=true',headers=headers).json()['verified'] is True
 assert client.get('/v1/status',headers=headers).json()['offseason_readiness']['status'] == 'partial'
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'reader/companion.sqlite').exists()
