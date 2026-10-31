"""Fixed-profile local capture control. No game writes, arbitrary paths or model calls."""
import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .display_profile import GAME_BUILD
from .schedule_projection import FOCUS_ROOT as SCHEDULE_ROOT
from .current_page_attributes_projection import FOCUS_ROOT as ATTRIBUTES_ROOT
from .tactics_projection import PANEL_ROOT

PROFILES = {'schedule': SCHEDULE_ROOT, 'current_page_attributes': ATTRIBUTES_ROOT, 'tactics': PANEL_ROOT}


def _time(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('invalid_time')
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_field')
        result[key] = value
    return result


@contextmanager
def _directory(path):
    # Walk every component using directory descriptors; never follow symlinks.
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.absolute().parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read(directory, name, *, optional=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        if optional:
            return None
        raise
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2048:
            raise ValueError('unsafe_control_file')
        data = stream.read(2049)
        if len(data) > 2048:
            raise ValueError('oversize_control_file')
        value = json.loads(data, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError('invalid_control_file')
        return value


class UiCaptureController:
    def __init__(self, root=None):
        # root is server-owned, never accepted by an HTTP request.
        self.root = root
        self.lock = threading.Lock()
        self.request = None

    def _host(self, diagnostics, snapshot, now):
        host = _read(diagnostics, 'host-session.json')
        source = snapshot.get('source_status') or {}
        game = source.get('game') or {}
        if not (source.get('source') == 'runtime' and source.get('synthetic') is False
                and source.get('connection_state') == 'connected'
                and source.get('source_freshness') == 'live'
                and source.get('adapter_id') == 'footballassistant.runtime-ui-tree'
                and (snapshot.get('observation') or {}).get('source', {}).get('platform') == 'macos-arm64'
                and game.get('product') == 'FM27'
                and source.get('data_freshness') == 'fresh'
                and game.get('build') == GAME_BUILD
                and isinstance(host.get('session_id'), str) and 0 < len(host['session_id']) <= 128
                and game.get('session_id') == host.get('session_id')
                and (snapshot.get('observation') or {}).get('game') == game
                and (snapshot.get('observation') or {}).get('synthetic') is False
                and isinstance(host.get('pid'), int) and not isinstance(host['pid'], bool) and host['pid'] > 0
                and re.fullmatch(r'[a-f0-9]{64}', host.get('managed_build_sha256', ''))):
            raise ValueError('host_session_unavailable')
        for key in ('last_captured_at', 'last_seen_at'):
            if not 0 <= (now - _time(source.get(key))).total_seconds() <= 15:
                raise ValueError('stale_session')
        return {key: host[key] for key in ('pid', 'session_id', 'managed_build_sha256')}

    @staticmethod
    def _result(status, request=None, reason=None):
        return dict(status=status, profile=request.get('profile') if request else None,
                    sequence=request.get('sequence') if request else None, reason=reason)

    def access(self, snapshot, profile=None, *, now=None):
        now = now or datetime.now(timezone.utc)
        if self.root is None:
            return self._result('not_configured', reason='bridge_control_not_configured')
        if profile is not None and profile not in PROFILES:
            return self._result('unavailable', reason='invalid_profile')
        try:
            with self.lock, _directory(self.root / 'diagnostics') as diagnostics, _directory(self.root / 'control') as control:
                import fcntl
                lockfd = os.open('.ui-capture.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=control)
                with os.fdopen(lockfd, 'rb') as lockfile:
                    info = os.fstat(lockfile.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('unsafe_lock')
                    fcntl.flock(lockfile, fcntl.LOCK_EX)
                    host = self._host(diagnostics, snapshot, now)
                    status = _read(diagnostics, 'ui-capture-status.json', optional=True)
                    previous = _read(control, 'ui-capture.json', optional=True)
                    if profile is not None:
                        sequence = 0
                        for item in (status, previous):
                            if item and all(item.get(k) == v for k, v in host.items()):
                                for key in ('sequence', 'accepted_sequence', 'applied_sequence'):
                                    value = item.get(key)
                                    if value is not None:
                                        if type(value) is not int or not 0 <= value < 2**63 - 1:
                                            raise ValueError('invalid_sequence')
                                        sequence = max(sequence, value)
                        request = dict(**host, sequence=sequence + 1, requested_at=now.isoformat(),
                                       focus_path=PROFILES[profile], widget_diagnostics=False)
                        payload = json.dumps(request, separators=(',', ':')).encode()
                        if len(payload) > 2048:
                            raise ValueError('request_too_large')
                        # Recheck host immediately before publishing the bound request.
                        if self._host(diagnostics, snapshot, now) != host:
                            raise ValueError('host_session_changed')
                        temporary = '.ui-capture-' + uuid.uuid4().hex
                        try:
                            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=control)
                            with os.fdopen(fd, 'wb') as stream:
                                stream.write(payload)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(temporary, 'ui-capture.json', src_dir_fd=control, dst_dir_fd=control)
                        finally:
                            try:
                                os.unlink(temporary, dir_fd=control)
                            except FileNotFoundError:
                                pass
                        self.request = dict(request, profile=profile)
                        return self._result('pending', self.request)
                    request = self.request
                    if request is None:
                        return self._result('unavailable', reason='no_profile_requested')
                    if any(request.get(k) != v for k, v in host.items()):
                        self.request = None
                        return self._result('unavailable', reason='host_session_changed')
                    if not status or any(status.get(k) != v for k, v in host.items()):
                        expired = (now - _time(request['requested_at'])).total_seconds() > 30
                        return self._result('unavailable' if expired else 'pending', request,
                                            'application_timeout' if expired else None)
                    if type(status.get('accepted_sequence')) is int and status['accepted_sequence'] > request['sequence']:
                        return self._result('unavailable', request, 'request_superseded')
                    if status.get('applied_sequence') != request['sequence'] or status.get('focus_path') != request['focus_path']:
                        expired = (now - _time(request['requested_at'])).total_seconds() > 30
                        return self._result('unavailable' if expired else 'pending', request,
                                            'application_timeout' if expired else None)
                    if not 0 <= (now - _time(status.get('applied_at'))).total_seconds() <= 15:
                        raise ValueError('stale_application')
                    from football_assistant_agent.ui_advice import prepare_ui_advice
                    prepared = prepare_ui_advice('player_info', snapshot, now=now, _preview_ui_changes=True)
                    preview = prepared['ui_change_preview']
                    provenance = prepared.get('provenance') or {}
                    # A fresh validated projection is required in addition to the DLL acknowledgement.
                    ready = (status.get('focus_resolved') is True and preview.get('status') == 'ready'
                             and provenance.get('path_scope') == 'focus_relative'
                             and provenance.get('focus_root_path') == request['focus_path']
                             and _time(status['applied_at']) >= _time(request['requested_at'])
                             and preview.get('kind') == request['profile']
                             and preview.get('session_id') == host['session_id']
                             and _time(preview['captured_at']) > _time(request['requested_at']))
                    return self._result('ready' if ready else 'applied', request,
                                        None if ready else 'page_not_verified')
        except FileNotFoundError:
            return self._result('not_configured', reason='bridge_control_not_configured')
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return self._result('unavailable', reason='control_or_session_unavailable')
