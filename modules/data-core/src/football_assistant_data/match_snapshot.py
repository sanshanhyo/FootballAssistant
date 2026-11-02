"""Bounded local match transport. Identity checks are not game-fact attestation."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

MAX_BYTES = 2 * 1024 * 1024
GAME_HASH = 'bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f'
PRODUCER = {'id': 'footballassistant.match-reader', 'version': '0.1.0', 'protocol': 'fa-match-snapshot/0.1'}


def current_process_matches(identity: dict) -> bool:
    """Query process name/start/liveness only; never open game memory or signal it."""
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    api.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    api.GetProcessTimes.restype = w.BOOL
    api.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    api.QueryFullProcessImageNameW.restype = w.BOOL
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.WaitForSingleObject.restype = w.DWORD
    handle = api.OpenProcess(0x00101000, False, identity['pid'])  # SYNCHRONIZE + QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        if api.WaitForSingleObject(handle, 0) != 258:  # WAIT_TIMEOUT: still running
            return False
        times = [w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return False
        file_time = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        name = ctypes.create_unicode_buffer(32768)
        size = w.DWORD(len(name))
        return (str(file_time) == identity['startedAtFileTime'] and
                bool(api.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size))) and
                name.value.replace('\\', '/').rsplit('/', 1)[-1].lower() == 'fm.exe')
    finally:
        api.CloseHandle(handle)


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def _identity(data, verify_process):
    if data.get('producer') != PRODUCER or data.get('synthetic') is not False:
        raise ValueError('producer')
    if not re.fullmatch(r'[a-f0-9]{32}', data.get('instanceId', '')):
        raise ValueError('instance')
    process = data['process']
    pid = process['pid']
    ticks = process['startedAtFileTime']
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or not re.fullmatch(r'[0-9]{1,19}', ticks):
        raise ValueError('process')
    if process.get('identityKind') != 'process_start' or process.get('saveIdentity') != 'unknown':
        raise ValueError('scope')
    if process['sessionId'] != hashlib.sha256(f'{pid}:{ticks}'.encode()).hexdigest():
        raise ValueError('session')
    started = _time(process['startedAt'])
    # Python has microsecond precision; FILETIME has 100 ns precision.
    expected = (int(ticks) - 116444736000000000) // 10
    actual = int(started.timestamp()) * 1000000 + started.microsecond
    if expected != actual or not verify_process(process):
        raise ValueError('process no longer current')
    return started


def _read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('oversized')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('object required')
    return data


def read_match_snapshot(path: Path, *, now: datetime | None = None, max_age: float = 15,
                        verify_process=None) -> dict:
    """No legacy identity fallback; old-session files never become current facts."""
    clock = now or datetime.now(timezone.utc)
    verify = verify_process or current_process_matches
    health = None
    try:
        status = _read(path.with_name('status.json'))
        started = _identity(status, verify)
        age = (clock - _time(status['observedAt'])).total_seconds()
        if (status.get('schema') == 'fa-match-status/0.1' and -5 <= age <= max_age
                and _time(status['observedAt']) >= started
                and status.get('state') in {'loading', 'hook_installed', 'hook_timeout', 'stopped'}
                and status.get('matchState') in {'waiting', 'live', 'ended', 'stopped'}):
            health = {key: status.get(key) for key in ('state', 'matchState', 'observedAt', 'process', 'producer', 'instanceId')}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, AttributeError, OverflowError):
        pass

    def unavailable(reason):
        return {'status': 'unavailable', 'reason': reason, 'snapshot': None, 'producerVerified': False, 'readerStatus': health}

    try:
        data = _read(path)
        if data.get('schema_version') != 'fa-match-snapshot/0.1' or data.get('source') != 'native_match_hook':
            return unavailable('invalid_snapshot_schema')
        started = _identity(data, verify)
        if not health or health['instanceId'] != data['instanceId'] or health['process'] != data['process']:
            return unavailable('reader_status_not_current')
        if data.get('status') != 'live':
            return unavailable('no_live_match')
        if health['state'] != 'hook_installed' or data.get('binary') != {'module': 'game_plugin.dll', 'sha256': GAME_HASH, 'matched': True}:
            return unavailable('unsupported_producer_binary')
        captured = _time(data['captured_at'])
        age = (clock - captured).total_seconds()
        if age < -5 or age > max_age or captured < started:
            return unavailable('stale')
        if not re.fullmatch(r'[a-f0-9]{32}', data.get('match_id', '')):
            return unavailable('invalid_match_identity')
        return {'status': 'experimental', 'reason': 'game_facts_not_verified', 'producerVerified': True,
                'snapshot': data, 'readerStatus': health}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, AttributeError, OverflowError):
        return unavailable('invalid_or_missing_snapshot')
