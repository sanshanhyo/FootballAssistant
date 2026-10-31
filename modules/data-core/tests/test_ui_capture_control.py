"""Local fixture control only: no game, network provider or real private directory."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Lock, Barrier
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
from capture_control_fixture import memory_control, MemoryCaptureFiles, MemoryPath

import pytest
from fastapi.testclient import TestClient
from football_assistant_data.ui_capture_control import UiCaptureController, PROFILES
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings
from test_display_profile import NOW, STAMP
from test_tactics_projection import tactics_snapshot, PANEL_ROOT, recount, projection


def focused_snapshot():
    data = tactics_snapshot()
    data['facts'] = [f for f in data['facts'] if f['entity_id'].startswith(PANEL_ROOT + '/')]
    for fact in data['facts']:
        fact['entity_id'] = 'focus' + fact['entity_id'][len(PANEL_ROOT):]
    data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
        field='capture_metrics', value=json.dumps(dict(path_scope='focus_relative',
            focus_requested=True, focus_resolved=True, focus_root_path=PANEL_ROOT))))
    recount(data)
    return data


def test_focused_tactics_keeps_real_relative_provenance_and_rejects_other_root():
    data = focused_snapshot()
    result = projection(data)
    assert result['status'] == 'experimental_ui_tactics'
    assert result['profile_id'].endswith('-focused')
    for field in result['field_provenance'].values():
        assert field['ui_path'].startswith('focus/')
        assert field['title_path'].startswith('focus/')
        assert field['path_scope'] == 'focus_relative'
    data['facts'][-1]['value'] = data['facts'][-1]['value'].replace(PANEL_ROOT, 'panel0/0')
    assert projection(data)['status'] == 'unavailable'


@pytest.fixture
def control():
    return memory_control()


@pytest.fixture
def posix_control(tmp_path):
    (tmp_path / 'control').mkdir()
    (tmp_path / 'diagnostics').mkdir()
    host = dict(pid=123, session_id='TEST-session', managed_build_sha256='a' * 64)
    (tmp_path / 'diagnostics/host-session.json').write_text(json.dumps(host))
    return UiCaptureController(tmp_path), host


def read_request(controller):
    return json.loads((controller.root / 'control/ui-capture.json').read_text())


def test_pending_then_applied_then_fresh_verified_scope(control):
    c, host = control
    data = focused_snapshot()
    posted = c.access(data, 'tactics', now=NOW - timedelta(seconds=1))
    assert posted['status'] == 'pending'
    request = read_request(c)
    assert request['focus_path'] == PANEL_ROOT and request['widget_diagnostics'] is False
    assert len(json.dumps(request).encode()) < 2048
    assert c.access(data, now=NOW)['status'] == 'pending'
    status = dict(**host, applied_sequence=request['sequence'], accepted_sequence=request['sequence'],
                  focus_path=PANEL_ROOT, focus_resolved=True, applied_at=NOW.isoformat())
    (c.root / 'diagnostics/ui-capture-status.json').write_text(json.dumps(status))
    data = json.loads(json.dumps(data).replace(STAMP, NOW.isoformat()))
    assert c.access(data, now=NOW)['status'] == 'ready'
    assert c.access(tactics_snapshot(), now=NOW)['status'] != 'ready'  # absolute is not requested scope


def test_same_timestamp_capture_does_not_confirm_write(control):
    c, host = control
    data = focused_snapshot()
    assert c.access(data, 'tactics', now=NOW)['status'] == 'pending'
    status = dict(**host, applied_sequence=1, focus_path=PANEL_ROOT, focus_resolved=True, applied_at=NOW.isoformat())
    (c.root / 'diagnostics/ui-capture-status.json').write_text(json.dumps(status))
    assert c.access(data, now=NOW)['status'] == 'applied'


@pytest.mark.parametrize('change', ['stale', 'session', 'synthetic', 'disconnect', 'build'])
def test_invalid_session_never_writes(control, change):
    c, host = control
    data = focused_snapshot()
    if change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    if change == 'session': data['source_status']['game']['session_id'] = 'OTHER'
    if change == 'synthetic': data['source_status']['synthetic'] = True
    if change == 'disconnect': data['source_status']['connection_state'] = 'disconnected'
    if change == 'build': data['source_status']['game']['build'] = 'OTHER'
    assert c.access(data, 'schedule', now=NOW)['status'] == 'unavailable'
    assert not (c.root / 'control/ui-capture.json').exists()


@pytest.mark.parametrize('name', ['control/ui-capture.json', 'control/.ui-capture.lock', 'diagnostics/host-session.json', 'diagnostics/ui-capture-status.json'])
@pytest.mark.skipif(os.name != 'posix', reason='POSIX descriptor/no-follow filesystem security test')
def test_linked_files_rejected(posix_control, tmp_path, name):
    c, _ = posix_control
    target = tmp_path / 'outside'
    target.write_text('{}')
    path = c.root / name
    path.unlink(missing_ok=True)
    path.symlink_to(target)
    assert c.access(focused_snapshot(), 'schedule', now=NOW)['status'] == 'unavailable'
    assert target.read_text() == '{}'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX descriptor/no-follow filesystem security test')
def test_linked_directory_rejected(posix_control):
    c, _ = posix_control
    real = c.root / 'real-control'
    (c.root / 'control').rename(real)
    (c.root / 'control').symlink_to(real, target_is_directory=True)
    assert c.access(focused_snapshot(), 'schedule', now=NOW)['status'] == 'unavailable'


def test_concurrent_controllers_use_monotonic_sequences(control):
    c, _ = control
    def write(_):
        return UiCaptureController(c.root, files=c.files).access(focused_snapshot(), 'schedule', now=NOW)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(12)))
    assert sorted(r['sequence'] for r in results) == list(range(1, 13))
    assert all(r['status'] == 'pending' for r in results)
    assert read_request(c)['sequence'] == 12


def test_old_session_and_expiry_invalidate_pending(control):
    c, host = control
    assert c.access(focused_snapshot(), 'schedule', now=NOW)['status'] == 'pending'
    (c.root / 'diagnostics/host-session.json').write_text(json.dumps({**host, 'session_id': 'new'}))
    assert c.access(focused_snapshot(), now=NOW)['status'] == 'unavailable'


def test_absent_bridge_is_not_configured(tmp_path):
    assert UiCaptureController(None).access({}, 'schedule')['status'] == 'not_configured'
    files = MemoryCaptureFiles()
    assert UiCaptureController(MemoryPath(files), files=files).access({}, 'schedule')['status'] == 'not_configured'


def test_endpoint_auth_and_strict_body(tmp_path):
    settings = Settings(data_dir=tmp_path, runtime_file=tmp_path / 'runtime.json', token='test')
    with TestClient(create_app(settings, enable_agent=False), base_url='http://127.0.0.1') as client:
        url = '/v1/reader/capture-profile'
        assert client.post(url, json={'profile': 'schedule'}).status_code == 401
        assert client.get(url).status_code == 401
        headers = {'Authorization': 'Bearer test'}
        for body in ({'profile': 'other'}, {'profile': 'schedule', 'path': '/tmp'}, {'profile': 'schedule', 'secret': 'x'}, {}):
            assert client.post(url, json=body, headers=headers).status_code == 422
        assert client.post(url, content='{"profile":"schedule","profile":"tactics"}', headers=headers).status_code == 422
        for profile in PROFILES:
            assert client.post(url, json={'profile': profile}, headers=headers).json()['status'] == 'not_configured'
        assert client.get(url, headers=headers).json()['status'] == 'not_configured'


def test_request_expiry_never_loops_pending(control):
    c, host = control
    data = focused_snapshot()
    c.access(data, 'tactics', now=NOW)
    later = NOW + timedelta(seconds=31)
    fresh = json.loads(json.dumps(data).replace(STAMP, later.isoformat()))
    result = c.access(fresh, now=later)
    assert result['status'] == 'unavailable' and result['reason'] == 'application_timeout'


@pytest.mark.parametrize('content', ['x' * 2049, '{"sequence":1,"sequence":2}', '[]'])
def test_oversize_duplicate_or_malformed_file_is_not_overwritten(control, content):
    c, _ = control
    path = c.root / 'control/ui-capture.json'
    path.write_text(content)
    assert c.access(focused_snapshot(), 'tactics', now=NOW)['status'] == 'unavailable'
    assert path.read_text() == content


def test_different_session_old_high_sequence_is_not_reused(control):
    c, host = control
    old = {**host, 'session_id': 'OLD', 'sequence': 900}
    (c.root / 'control/ui-capture.json').write_text(json.dumps(old))
    assert c.access(focused_snapshot(), 'tactics', now=NOW)['sequence'] == 1


def test_same_session_status_sequence_is_respected(control):
    c, host = control
    (c.root / 'diagnostics/ui-capture-status.json').write_text(json.dumps({**host, 'accepted_sequence': 90}))
    assert c.access(focused_snapshot(), 'tactics', now=NOW)['sequence'] == 91


def test_stale_ack_and_unresolved_focus_never_ready(control):
    c, host = control
    data = focused_snapshot()
    c.access(data, 'tactics', now=NOW - timedelta(seconds=1))
    data = json.loads(json.dumps(data).replace(STAMP, NOW.isoformat()))
    status = dict(**host, applied_sequence=1, focus_path=PANEL_ROOT, focus_resolved=False, applied_at=NOW.isoformat())
    path = c.root / 'diagnostics/ui-capture-status.json'
    path.write_text(json.dumps(status))
    assert c.access(data, now=NOW)['status'] == 'applied'
    path.write_text(json.dumps({**status, 'focus_resolved': True, 'applied_at': (NOW - timedelta(seconds=16)).isoformat()}))
    assert c.access(data, now=NOW)['status'] == 'unavailable'


def test_focused_tactics_duplicate_or_malformed_values_fail_closed():
    for mode in ('duplicate', 'malformed'):
        data = focused_snapshot()
        if mode == 'duplicate':
            data['facts'].append(deepcopy(data['facts'][0]))
            recount(data)
        else:
            data['facts'][0]['value'] = '积极进取4-4-4 - 控制球权'
        assert projection(data)['status'] == 'unavailable'


def test_server_configuration_never_discovers_private_root(monkeypatch):
    monkeypatch.delenv('FOOTBALL_ASSISTANT_PRIVATE_ROOT', raising=False)
    assert Settings.from_env(reader_only=True).bridge_private_root is None
    monkeypatch.setenv('FOOTBALL_ASSISTANT_PRIVATE_ROOT', '/explicit/private/bridge')
    assert Settings.from_env(reader_only=True).bridge_private_root == Path('/explicit/private/bridge').absolute()


def test_unsupported_platform_rejects_before_filesystem_access(tmp_path, monkeypatch):
    from football_assistant_data.ui_capture_control import PosixCaptureFiles
    from football_assistant_data.windows_capture_files import WindowsCaptureFiles
    monkeypatch.setattr(PosixCaptureFiles, 'supported', False)
    monkeypatch.setattr(WindowsCaptureFiles, 'supported', False)
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported platform must not open even a reparse/link path')
    monkeypatch.setattr(PosixCaptureFiles, 'directory', forbidden)
    monkeypatch.setattr(WindowsCaptureFiles, 'directory', forbidden)
    result = UiCaptureController(tmp_path).access(focused_snapshot(), 'tactics', now=NOW)
    assert result == dict(status='unavailable', reason='unsupported_platform', profile=None, sequence=None)
    assert UiCaptureController(None).access({}, 'schedule')['status'] == 'not_configured'


def test_authenticated_api_exposes_unsupported_platform(tmp_path, monkeypatch):
    from football_assistant_data.ui_capture_control import PosixCaptureFiles
    from football_assistant_data.windows_capture_files import WindowsCaptureFiles
    monkeypatch.setattr(PosixCaptureFiles, 'supported', False)
    monkeypatch.setattr(WindowsCaptureFiles, 'supported', False)
    settings = Settings(data_dir=tmp_path, runtime_file=tmp_path / 'runtime.json', token='test', bridge_private_root=tmp_path)
    with TestClient(create_app(settings, enable_agent=False), base_url='http://127.0.0.1') as client:
        headers = {'Authorization': 'Bearer test'}
        for response in (client.get('/v1/reader/capture-profile', headers=headers),
                         client.post('/v1/reader/capture-profile', headers=headers, json={'profile': 'tactics'})):
            assert response.status_code == 200
            assert response.json()['reason'] == 'unsupported_platform'
            assert response.json()['status'] == 'unavailable'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX atomic write/flock integration test')
def test_posix_real_adapter_atomic_write_and_cross_controller_lock(posix_control):
    from football_assistant_data.ui_capture_control import PosixCaptureFiles
    c, _ = posix_control
    file_errors, error_lock = [], Lock()

    def record(stage, error):
        # Fixture-only diagnostic: do not log file contents, paths or credentials.
        with error_lock:
            trace = error.__traceback__
            while trace and trace.tb_next:
                trace = trace.tb_next
            name = getattr(error, 'filename', '') or ''
            kind = name if name in ('.ui-capture.lock', 'ui-capture.json', 'host-session.json', 'ui-capture-status.json') else 'temporary' if str(name).startswith('.ui-capture-') else 'directory_component'
            file_errors.append(dict(stage=stage, error=type(error).__name__, errno=getattr(error, 'errno', None),
                                    path_kind=kind, function=trace.tb_frame.f_code.co_name if trace else None,
                                    line=trace.tb_lineno if trace else None))

    class TracedFiles(PosixCaptureFiles):
        @contextmanager
        def directory(self, path):
            try:
                with super().directory(path) as directory:
                    yield directory
            except Exception as error:
                record('directory_enter_body_or_exit', error)
                raise

        @contextmanager
        def locked(self, directory):
            try:
                with super().locked(directory):
                    yield
            except Exception as error:
                record('lock_enter_body_or_exit', error)
                raise

        def read(self, directory, name, *, optional=False):
            try:
                return super().read(directory, name, optional=optional)
            except Exception as error:
                record('read:' + name, error)
                raise

        def write_request(self, directory, payload):
            try:
                return super().write_request(directory, payload)
            except Exception as error:
                record('write_request', error)
                raise

    files = TracedFiles()
    def write(_):
        return UiCaptureController(c.root, files=files).access(focused_snapshot(), 'tactics', now=NOW)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(12)))
    # Report the originating failure before sorting can mask it as None/int TypeError.
    if any(r['status'] != 'pending' for r in results):
        print('CONTROL_FILE_FAILURES=' + json.dumps(file_errors))
    assert all(r['status'] == 'pending' for r in results), dict(results=results, file_errors=file_errors)
    assert sorted(r['sequence'] for r in results) == list(range(1, 13))
    assert read_request(c)['sequence'] == 12
    assert (c.root / 'control/ui-capture.json').stat().st_mode & 0o777 == 0o600
    assert not list((c.root / 'control').glob('.ui-capture-*'))


@pytest.mark.skipif(os.name != 'posix', reason='POSIX regular-file/hard-link security test')
def test_posix_hard_link_is_rejected(posix_control):
    c, _ = posix_control
    target = c.root / 'unrelated'
    target.write_text('{}')
    os.link(target, c.root / 'control/ui-capture.json')
    assert c.access(focused_snapshot(), 'tactics', now=NOW)['status'] == 'unavailable'
    assert target.read_text() == '{}'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX bounded file parser integration test')
@pytest.mark.parametrize('content', ['x' * 2049, '{"sequence":1,"sequence":2}', '[]'])
def test_posix_oversize_duplicate_and_malformed_requests_remain_rejected(posix_control, content):
    c, _ = posix_control
    path = c.root / 'control/ui-capture.json'
    path.write_text(content)
    assert c.access(focused_snapshot(), 'tactics', now=NOW)['status'] == 'unavailable'
    assert path.read_text() == content


@pytest.mark.skipif(os.name != 'posix', reason='real POSIX first-creation contention experiment')
def test_posix_first_lock_creation_contention(tmp_path, capsys):
    """Both modes use only new test directories. Legacy errors are evidence, not
    ignored errors in production: every exclusive-create attempt must succeed.
    """
    from football_assistant_data.ui_capture_control import PosixCaptureFiles
    files = PosixCaptureFiles()
    legacy_errors, fixed_errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for iteration in range(30):
            for mode in ('legacy', 'exclusive'):
                folder = tmp_path / f'{mode}-{iteration}'
                folder.mkdir()
                barrier = Barrier(8)
                with files.directory(folder) as directory:
                    def acquire(_):
                        barrier.wait(timeout=15)
                        try:
                            if mode == 'legacy':
                                # Exact old syscall pattern, isolated diagnostic fixture.
                                fd = os.open('.ui-capture.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
                                os.close(fd)
                            else:
                                # Independent proposed syscall pattern, not production.
                                flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
                                try:
                                    fd = os.open('.ui-capture.lock', flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
                                except FileExistsError:
                                    fd = os.open('.ui-capture.lock', flags, dir_fd=directory)
                                os.close(fd)
                            return None
                        except OSError as error:
                            return dict(stage='lock_open_before_flock' if mode == 'legacy' else 'exclusive_lock',
                                        error=type(error).__name__, errno=error.errno)
                    errors = [result for result in pool.map(acquire, range(8)) if result]
                    (legacy_errors if mode == 'legacy' else fixed_errors).extend(errors)
    summary = dict(rounds=30, workers=8, legacy_errors=legacy_errors, exclusive_errors=fixed_errors)
    with capsys.disabled():
        print('POSIX_LOCK_CREATION_COMPARISON=' + json.dumps(summary, separators=(',', ':')))
    assert not fixed_errors, summary
