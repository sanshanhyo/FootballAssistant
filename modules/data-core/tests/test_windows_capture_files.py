"""Windows tests use actual kernel handles; non-Windows must not emulate a pass."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from football_assistant_data.windows_capture_files import WindowsCaptureFiles, _components

windows = pytest.mark.skipif(os.name != 'nt', reason='requires real Windows file/locking APIs')


def test_windows_path_policy_rejects_ambiguous_or_remote_names():
    assert _components(r'C:\private\control') == ('C:\\', ['private', 'control'])
    for path in [r'\\server\share\control', r'\\?\C:\control', r'C:control',
                 r'C:\private\..\control', r'C:\private\x:stream', r'C:\private\x.',
                 r'C:\private\x ', r'C:\private\\control', '/tmp/control']:
        with pytest.raises(ValueError):
            _components(path)


def test_non_windows_transport_fails_closed():
    if os.name == 'nt':
        pytest.skip('non-Windows refusal only')
    files = WindowsCaptureFiles()
    assert not files.supported
    with pytest.raises(OSError, match='unsupported_platform'):
        with files.directory(Path('/tmp')):
            pass


@pytest.fixture
def local_control(tmp_path):
    root = tmp_path / 'private'
    root.mkdir()
    control = root / 'control'
    control.mkdir()
    return control


@windows
def test_real_windows_round_trip_replacement_and_cleanup(local_control):
    files = WindowsCaptureFiles()
    with files.directory(local_control) as directory, files.locked(directory):
        assert files.read(directory, 'ui-capture.json', optional=True) is None
        for sequence in (1, 2):
            payload = json.dumps({'sequence': sequence, 'session_id': 'test', 'text': '埃克拉'}).encode()
            files.write_request(directory, payload)
            assert (local_control / 'ui-capture.json').read_bytes() == payload
            assert files.read(directory, 'ui-capture.json')['sequence'] == sequence
    assert not list(local_control.glob('.ui-capture-*'))


@windows
def test_real_windows_read_rejects_hardlinks_and_write_does_not_touch_victim(local_control, tmp_path):
    victim = tmp_path / 'victim.json'
    victim.write_bytes(b'{"keep":true}')
    os.link(victim, local_control / 'ui-capture.json')
    files = WindowsCaptureFiles()
    with files.directory(local_control) as directory:
        with pytest.raises(ValueError, match='unsafe_control_file'):
            files.read(directory, 'ui-capture.json')
        with pytest.raises(ValueError):
            files.write_request(directory, b'{"replace":true}')
    assert victim.read_bytes() == b'{"keep":true}'


@windows
def test_real_windows_rejects_junction_ancestor(local_control, tmp_path):
    junction = tmp_path / 'junction'
    # Junction creation requires no symlink developer-mode permission. It is
    # confined to this test directory and targets only another temporary folder.
    result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(local_control.parent)], capture_output=True)
    assert result.returncode == 0, 'Windows junction fixture must be created for this security test'
    try:
        with pytest.raises((ValueError, OSError)) as error:
            with WindowsCaptureFiles().directory(junction / 'control'):
                pass
        assert getattr(error.value, 'winerror', None) != 87, 'must reject reparse, not malformed NT arguments'
    finally:
        os.rmdir(junction)


@windows
def test_real_windows_held_ancestors_cannot_be_replaced(local_control):
    files = WindowsCaptureFiles()
    with files.directory(local_control):
        with pytest.raises(OSError):
            local_control.rename(local_control.with_name('moved'))
        with pytest.raises(OSError):
            local_control.parent.rename(local_control.parent.with_name('moved-root'))
    local_control.rename(local_control.with_name('moved'))


@windows
def test_real_windows_cross_process_lock_is_exclusive_and_released(local_control):
    code = '''
import sys
from pathlib import Path
from football_assistant_data.windows_capture_files import WindowsCaptureFiles
files = WindowsCaptureFiles()
try:
    with files.directory(Path(sys.argv[1])) as directory, files.locked(directory):
        pass
except OSError:
    sys.exit(17)
'''
    env = dict(os.environ)
    source = str(Path(__file__).resolve().parents[1] / 'src')
    env['PYTHONPATH'] = source + os.pathsep + env.get('PYTHONPATH', '')
    files = WindowsCaptureFiles()
    with files.directory(local_control) as directory, files.locked(directory):
        result = subprocess.run([sys.executable, '-c', code, str(local_control)], env=env, capture_output=True, timeout=15)
        assert result.returncode == 17, result.stderr.decode(errors='replace')
        with pytest.raises(OSError):
            (local_control / '.ui-capture.lock').unlink()
    result = subprocess.run([sys.executable, '-c', code, str(local_control)], env=env, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


@windows
@pytest.mark.parametrize('data', [b'x' * 2049, b'{"x":1,"x":2}', b'[]', b'not JSON'])
def test_real_windows_rejects_oversize_duplicate_and_invalid_json(local_control, data):
    (local_control / 'ui-capture.json').write_bytes(data)
    with WindowsCaptureFiles().directory(local_control) as directory:
        with pytest.raises(ValueError):
            WindowsCaptureFiles().read(directory, 'ui-capture.json')


@windows
def test_real_windows_failed_rename_cleans_owned_temporary(local_control):
    files = WindowsCaptureFiles()
    (local_control / 'ui-capture.json').write_bytes(b'{"old":true}')
    with files.directory(local_control) as directory:
        # A held read handle disallows deletion/replacement of the destination.
        with files._open(str(local_control / 'ui-capture.json'), 0x80000000, 1):
            with pytest.raises(OSError) as error:
                files.write_request(directory, b'{"new":true}')
            assert error.value.winerror in (5, 32), "must be access/sharing refusal, not malformed rename (87)"
        assert files.read(directory, 'ui-capture.json') == {'old': True}
    assert not list(local_control.glob('.ui-capture-*'))


def test_windows_evidence_still_rejected_by_controller_platform_guard():
    from capture_control_fixture import memory_control
    from test_ui_capture_control import focused_snapshot
    from test_display_profile import NOW
    controller, _ = memory_control()
    data = focused_snapshot()
    data['observation']['source']['platform'] = 'windows-x64'
    result = controller.access(data, 'tactics', now=NOW)
    assert result['status'] == 'unavailable'
    assert not (controller.root / 'control/ui-capture.json').exists()


@windows
def test_real_windows_default_adapter_does_not_approve_game_evidence(local_control):
    from football_assistant_data.ui_capture_control import UiCaptureController
    from capture_control_fixture import memory_control
    from test_ui_capture_control import focused_snapshot
    from test_display_profile import NOW
    _, host = memory_control()
    diagnostics = local_control.parent / 'diagnostics'
    diagnostics.mkdir()
    (diagnostics / 'host-session.json').write_text(json.dumps(host))
    controller = UiCaptureController(local_control.parent)
    assert isinstance(controller.files, WindowsCaptureFiles)
    data = focused_snapshot()
    data['observation']['source']['platform'] = 'windows-x64'
    assert controller.access(data, 'tactics', now=NOW)['status'] == 'unavailable'
    assert not (local_control / 'ui-capture.json').exists()


def test_native_rename_buffer_layout_is_length_delimited_and_handle_relative():
    from football_assistant_data.windows_capture_files import _RenameInfo, _IoStatusBlock, _rename_buffer
    buffer = _rename_buffer(1234)
    info = _RenameInfo.from_buffer(buffer)
    assert info.root == 1234 and info.replace == 1
    assert info.length == len('ui-capture.json'.encode('utf-16-le'))
    assert len(buffer) == max(ctypes.sizeof(_RenameInfo), _RenameInfo.name.offset + info.length)
    assert buffer.raw[_RenameInfo.name.offset:_RenameInfo.name.offset + info.length].decode('utf-16-le') == 'ui-capture.json'
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(_RenameInfo) == 24
        assert [_RenameInfo.root.offset, _RenameInfo.length.offset, _RenameInfo.name.offset] == [8, 16, 20]
        assert ctypes.sizeof(_IoStatusBlock) == 16
        assert _IoStatusBlock.information.offset == 8


@windows
def test_real_windows_no_absolute_child_opens_after_directory_is_held(local_control, monkeypatch):
    files = WindowsCaptureFiles()
    with files.directory(local_control) as directory:
        def forbidden(*args, **kwargs):
            pytest.fail('no absolute-path open allowed through the write-shared final parent')
        monkeypatch.setattr(files, '_open', forbidden)
        with files.locked(directory):
            files.write_request(directory, b'{"sequence":1}')
            files.write_request(directory, b'{"sequence":2}')
            assert files.read(directory, 'ui-capture.json') == {'sequence': 2}


def test_native_object_attributes_layout():
    from football_assistant_data.windows_capture_files import _ObjectAttributes, _UnicodeString
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(_ObjectAttributes) == 48
        assert [_ObjectAttributes.root.offset, _ObjectAttributes.name.offset, _ObjectAttributes.attributes.offset] == [8, 16, 24]
        assert ctypes.sizeof(_UnicodeString) == 16
        assert _UnicodeString.buffer.offset == 8


@pytest.mark.parametrize('disposition', [1, 3, 4])
def test_nt_relative_open_requests_read_attributes_and_closes_on_validation_failure(monkeypatch, disposition):
    """Injected ABI contract test, not a claim of executing Windows APIs."""
    from types import SimpleNamespace
    from football_assistant_data.windows_capture_files import HANDLE
    calls = []
    files = WindowsCaptureFiles.__new__(WindowsCaptureFiles)
    files.api = SimpleNamespace(CloseHandle=lambda handle: calls.append(('close', handle.value)))
    def create(output, access, *args):
        assert access & 0x80, 'metadata inspection needs FILE_READ_ATTRIBUTES even on write-only temp'
        assert access & 0x100000, 'synchronous NT handle needs SYNCHRONIZE'
        ctypes.cast(output, ctypes.POINTER(HANDLE))[0] = HANDLE(123)
        return 0
    files.nt = SimpleNamespace(NtCreateFile=create)
    def inspect(handle, **kwargs):
        if getattr(handle, 'value', handle) == 123:
            raise ValueError('injected_metadata_failure')
    monkeypatch.setattr(files, '_info', inspect)
    monkeypatch.setattr(files, '_delete_owned', lambda handle: calls.append(('delete', handle.value)))
    with pytest.raises(ValueError, match='injected_metadata_failure'):
        with files._open_relative(99, '.ui-capture-test', 0x40010000, 0, disposition=disposition):
            pytest.fail('invalid handle must never escape')
    assert calls == ([('delete', 123)] if disposition == 1 else []) + [('close', 123)]
