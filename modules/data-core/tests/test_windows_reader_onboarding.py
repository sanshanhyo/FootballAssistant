"""Offline producer/API protocol fixtures; never inspect a game or real process."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from football_assistant_data import offseason_snapshot as reader
from football_assistant_data.app import create_app
from football_assistant_data.reader import create_reader_app
from test_reader import settings, AUTH

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)


def payload(state='fresh_partial', now=NOW):
    started = (now - timedelta(hours=1)).isoformat()
    process = {'pid': 123, 'startedAt': started, 'sessionId': hashlib.sha256(f'123:{started}'.encode()).hexdigest(), 'identityKind': 'process_start', 'saveIdentity': 'unknown'}
    binary = {'module': 'game_plugin.dll', 'sha256': reader.EXPECTED_BINARY, 'matched': True}
    if state in {'fm_not_running', 'multiple_process', 'process_access_denied', 'read_failed'}:
        process = binary = None
    elif state == 'no_session':
        binary = None
    elif state == 'unsupported_binary':
        binary = {**binary, 'sha256': 'a' * 64, 'matched': False}
    result = {'schema': 'fa-offseason/0.1', 'producer': dict(reader.PRODUCER), 'synthetic': False,
              'status': 'partial' if state == 'fresh_partial' else 'unavailable', 'state': state, 'reason': state,
              'capturedAt': now.isoformat(), 'process': process, 'binary': binary}
    if state == 'fresh_partial':
        result['date'] = {'status': 'experimental', 'date': '2026-11-02', 'observedAt': now.isoformat()}
    return result


@pytest.mark.parametrize('state', sorted(reader.STATES))
def test_current_producer_preserves_each_real_state_without_promoting_partial_facts(state):
    result = reader.validate_snapshot(payload(state), require_current_producer=True, now=NOW)
    assert result['producerVerified'] is True
    assert result['reason'] == ('experimental_candidates' if state == 'fresh_partial' else state)
    if state == 'fresh_partial':
        assert result['status'] == 'partial'
        assert result['snapshot']['process']['saveIdentity'] == 'unknown'
    else:
        assert result['snapshot'] is None
        assert result['diagnostics']['state'] == state


def test_legacy_fixture_compatibility_is_explicitly_not_onboarding_verified():
    old = {'schema': 'fa-offseason/0.1', 'status': 'partial', 'capturedAt': NOW.isoformat(), 'date': {'status': 'experimental'}}
    assert reader.validate_snapshot(old, now=NOW)['producerVerified'] is False
    assert reader.validate_snapshot(old, require_current_producer=True, now=NOW)['reason'] == 'unsupported_producer'
    old.update(status='unavailable', reason='no_current_data')
    assert reader.validate_snapshot(old, now=NOW)['reason'] == 'no_current_data'


@pytest.mark.parametrize('mutation', [
    lambda p: p['producer'].update(version='0.0.9'),
    lambda p: p['producer'].update(protocol=1),
    lambda p: p.update(synthetic=True),
    lambda p: p.update(status='offline_self_test', state='offline_self_test', synthetic=True, process=None, binary=None),
    lambda p: p.update(capturedAt=(NOW - timedelta(seconds=31)).isoformat()),
    lambda p: p.update(capturedAt=(NOW + timedelta(seconds=6)).isoformat()),
    lambda p: p.update(capturedAt='2026-11-02T06:00:00'),
    lambda p: p['process'].update(pid=True),
    lambda p: p['process'].update(sessionId='0' * 64),
    lambda p: p['process'].update(startedAt=(NOW + timedelta(days=1)).isoformat()),
    lambda p: p['process'].update(saveIdentity='verified'),
    lambda p: p['binary'].update(sha256='0' * 64),
    lambda p: p['binary'].update(module='GameAssembly.dll'),
    lambda p: p.update(process=None),
    lambda p: p.update(binary=None),
    lambda p: p.pop('date'),
])
def test_invalid_identity_synthetic_stale_and_empty_claims_never_become_live(mutation):
    value = payload(); mutation(value)
    result = reader.validate_snapshot(value, require_current_producer=True, now=NOW)
    assert result['status'] == 'unavailable' and result['snapshot'] is None
    assert result.get('producerVerified') is not True


def test_passive_status_never_runs_and_explicit_verify_is_authenticated_and_current(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'; executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(executable))
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    calls = []
    async def fake(path, club, person, **kwargs):
        calls.append((path, club, person, kwargs))
        return reader.validate_snapshot(payload(), require_current_producer=True, now=NOW)
    monkeypatch.setattr(reader, 'read_offseason', fake)
    with TestClient(create_reader_app(settings(tmp_path)), base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/onboarding-status?verify=true').status_code == 401
        value = client.get('/v1/reader/onboarding-status', headers=AUTH).json()
        assert value['state'] == 'configured' and value['verified'] is False and value['read'] is None
        assert calls == []
        verified = client.get('/v1/reader/onboarding-status?verify=true', headers=AUTH).json()
        assert calls == [(executable, 0, 0, {'require_current_producer': True})]
        assert verified['state'] == 'fresh_partial' and verified['backendHealthy'] is True
        assert verified['read']['producer'] == reader.PRODUCER
        assert 'date' not in verified['read']  # Status endpoint reports metadata, not football records.


@pytest.mark.parametrize('case,expected', [('no_consent', 'consent_required'), ('not_configured', 'producer_not_configured'), ('missing', 'resource_missing')])
def test_config_gaps_are_distinct_and_never_launch(tmp_path, monkeypatch, case, expected):
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'missing.exe'))
    if case == 'no_consent': monkeypatch.delenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT')
    if case == 'not_configured': monkeypatch.delenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE')
    async def forbidden(*args, **kwargs): pytest.fail('configuration inspection launched producer')
    monkeypatch.setattr(reader, 'read_offseason', forbidden)
    value = asyncio.run(reader.onboarding_status(verify=True))
    assert value['state'] == expected and value['read'] is None and value['backendHealthy'] is True


def test_revoked_consent_blocks_all_live_routes_even_with_mocked_reader(tmp_path, monkeypatch):
    monkeypatch.delenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', raising=False)
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'reader.exe'))
    async def forbidden(*args, **kwargs): pytest.fail('reader called without consent')
    monkeypatch.setattr(reader, 'read_offseason', forbidden)
    with TestClient(create_app(settings(tmp_path)), base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/offseason', headers=AUTH).json()['reason'] == 'consent_required'
        for endpoint, body in [('/v1/agent/calendar-advice', {'message': 'calendar', 'club_uid': 1, 'start': '2026-11-01', 'end': '2026-11-02'}), ('/v1/agent/auto-calendar-advice', {'message': 'calendar'})]:
            response = client.post(endpoint, headers=AUTH, json=body)
            assert response.status_code == 200 and response.json()['reason'] == 'consent_required'


class FakeProcess:
    def __init__(self, raw):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(raw); self.stdout.feed_eof()
        self.returncode = None; self.killed = False
    async def wait(self):
        if self.returncode is None: self.returncode = 0
        return self.returncode
    def kill(self): self.killed = True; self.returncode = -9


def test_one_shot_subprocess_uses_fixed_args_preserves_reason_and_rejects_selftest(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'; executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    value = payload('fm_not_running', datetime.now(timezone.utc)); calls = []
    async def spawn(*args, **kwargs):
        calls.append(args)
        return FakeProcess(json.dumps(value).encode())
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    assert asyncio.run(reader.read_offseason(executable, 0, 0, require_current_producer=True))['reason'] == 'fm_not_running'
    assert calls == [(str(executable), '0', '0')]
    value.update(status='offline_self_test', state='offline_self_test', synthetic=True)
    assert asyncio.run(reader.read_offseason(executable, 0, 0))['reason'] == 'synthetic_producer_output'
    monkeypatch.delenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT')
    assert asyncio.run(reader.read_offseason(executable, 0, 0))['reason'] == 'consent_required'
    assert len(calls) == 2


def test_all_routes_share_nonqueued_producer_gate_and_release_after_completion(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'; executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    async def run():
        ready = asyncio.Event(); release = asyncio.Event()
        async def spawn(*args, **kwargs):
            ready.set(); await release.wait()
            return FakeProcess(json.dumps(payload('no_data', datetime.now(timezone.utc))).encode())
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        first = asyncio.create_task(reader.read_offseason(executable, 0, 0))
        await ready.wait()
        assert (await reader.read_offseason(executable, 42, 0, '2026-11-01', '2026-11-02'))['reason'] == 'producer_busy'
        release.set()
        assert (await first)['reason'] == 'no_data'
        assert (await reader.read_offseason(executable, 0, 0))['reason'] == 'no_data'
    asyncio.run(run())


def test_timeout_kills_child_and_releases_gate(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'; executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    processes = []
    async def spawn(*args, **kwargs):
        child = FakeProcess(b'{}'); processes.append(child); return child
    async def timeout(coro, timeout):
        coro.close(); raise asyncio.TimeoutError()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(asyncio, 'wait_for', timeout)
    assert asyncio.run(reader.read_offseason(executable, 0, 0))['reason'] == 'producer_timeout'
    assert processes[0].killed
    assert reader._PRODUCER_GATE.acquire(blocking=False)
    reader._PRODUCER_GATE.release()


def test_cli_offline_entry_precedes_all_game_access_and_unknown_binary_blocks_lookups():
    root = Path(__file__).resolve().parents[2]
    source = (root / 'game-bridge/offseason-reader-cli/Program.cs').read_text()
    assert source.index('args[0] == "--self-test"') < source.index('Process.GetProcessesByName')
    assert source.index('args[0] == "--version"') < source.index('Process.GetProcessesByName')
    assert source.index('if (!matched) return Emit("unsupported_binary")') < source.index('WorldDateLookup.Read(pid)')
    assert 'return Emit("offline_self_test", synthetic: true)' in source
    assert 'WriteProcessMemory' not in source and 'BepInEx' not in source


def test_auto_calendar_rejects_process_session_change_even_when_candidate_identity_matches(tmp_path, monkeypatch):
    from football_assistant_data import calendar_selection
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'reader.exe'))
    selected = {'club_uid': 42, 'manager_uid': 7, 'club_name': 'fixture', 'selection': 'fixture', 'start': '2026-11-01', 'end': '2026-11-02'}
    monkeypatch.setattr(calendar_selection, 'choose_calendar_scope', lambda *args: selected)
    calls = []
    async def read(*args, **kwargs):
        value = payload(now=datetime.now(timezone.utc) + timedelta(seconds=len(calls)))
        calls.append(value)
        return {'status': 'partial', 'producerVerified': True, 'snapshot': value}
    monkeypatch.setattr(reader, 'read_offseason', read)
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        async def forbidden(*args, **kwargs): pytest.fail('model generation on changed process session')
        monkeypatch.setattr(app.state.agent, 'calendar_advice', forbidden)
        response = client.post('/v1/agent/auto-calendar-advice', headers=AUTH, json={'message': 'fixture calendar'})
        assert response.json()['reason'] == 'session_changed'
        assert len(calls) == 2


def test_oversized_output_is_killed_not_parsed_and_gate_is_released(tmp_path, monkeypatch):
    executable = tmp_path / 'reader.exe'; executable.touch()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    processes = []
    async def spawn(*args, **kwargs):
        process = FakeProcess(b'x' * (reader._MAX_BYTES + 1)); processes.append(process); return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    assert asyncio.run(reader.read_offseason(executable, 0, 0))['reason'] == 'producer_invalid_output'
    assert processes[0].killed
    assert reader._PRODUCER_GATE.acquire(blocking=False)
    reader._PRODUCER_GATE.release()
