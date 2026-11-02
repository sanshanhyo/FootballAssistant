import hashlib
import json
from datetime import datetime, timedelta, timezone

from football_assistant_data.match_snapshot import read_match_snapshot, PRODUCER, GAME_HASH


def fixture(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ticks = str(int(now.timestamp()) * 10000000 + 116444736000000000)
    process = {'pid': 42, 'startedAt': now.isoformat(), 'startedAtFileTime': ticks,
               'sessionId': hashlib.sha256(f'42:{ticks}'.encode()).hexdigest(),
               'identityKind': 'process_start', 'saveIdentity': 'unknown'}
    common = {'producer': PRODUCER, 'process': process, 'instanceId': 'b'*32, 'synthetic': False}
    data = {**common, 'schema_version': 'fa-match-snapshot/0.1', 'source': 'native_match_hook',
            'status': 'live', 'captured_at': now.isoformat(), 'match_id': 'a'*32,
            'binary': {'module': 'game_plugin.dll', 'sha256': GAME_HASH, 'matched': True}}
    health = {**common, 'schema': 'fa-match-status/0.1', 'state': 'hook_installed',
              'matchState': 'live', 'observedAt': now.isoformat()}
    path = tmp_path / 'match.json'
    def write():
        path.write_text(json.dumps(data))
        path.with_name('status.json').write_text(json.dumps(health))
    write()
    return path, now, data, health, write


def test_match_freshness_and_lifecycle(tmp_path):
    path, now, data, health, write = fixture(tmp_path)
    read = lambda **kw: read_match_snapshot(path, now=now, verify_process=lambda p: True, **kw)
    assert read()['producerVerified'] is True
    assert read()['reason'] == 'game_facts_not_verified'
    data['captured_at'] = (now - timedelta(seconds=16)).isoformat(); write()
    assert read()['reason'] == 'stale'  # fresh heartbeat never freshens old tick
    data['status'] = 'ended'; write()
    assert read()['reason'] == 'no_live_match'
    assert read()['readerStatus']['state'] == 'hook_installed'
    data['status'] = 'live'; data['synthetic'] = True; write()
    assert read()['status'] == 'unavailable'


def test_process_reuse_stopped_missing_identity_and_instance_rejected(tmp_path):
    path, now, data, health, write = fixture(tmp_path)
    def read():
        return read_match_snapshot(path, now=now, verify_process=lambda p: True)
    assert read_match_snapshot(path, now=now, verify_process=lambda p: False)['snapshot'] is None
    health['instanceId'] = 'c'*32; write()
    assert read()['reason'] == 'reader_status_not_current'
    health['instanceId'] = data['instanceId']; health['state'] = 'stopped'; write()
    assert read()['snapshot'] is None
    health['state'] = 'hook_installed'; del data['producer']; write()
    assert read()['snapshot'] is None


def test_heartbeat_and_identity_validation_fail_closed(tmp_path):
    path, now, data, health, write = fixture(tmp_path)
    for change in [lambda: health.update(observedAt='2020-01-01T00:00:00Z'),
                   lambda: data['process'].update(pid=True),
                   lambda: data.update(binary={'matched': True})]:
        change(); write()
        assert read_match_snapshot(path, now=now, verify_process=lambda p: True)['snapshot'] is None


def test_native_probe_off_windows_is_not_fixture_verification(tmp_path):
    import os
    path, now, *_ = fixture(tmp_path)
    if os.name != 'nt':
        assert read_match_snapshot(path, now=now)['producerVerified'] is False
