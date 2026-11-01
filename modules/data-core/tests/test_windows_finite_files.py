"""Synthetic parser checks; Windows handle checks are explicitly platform-gated."""
import json
import os
import pytest
from football_assistant_data.windows_finite_files import (
    WindowsFiniteFiles, parse_file, FILES, CONTROL_BYTES, EVIDENCE_BYTES, MAX_EVENTS,
)
from football_assistant_data.windows_capture_files import WindowsCaptureFiles, _components


def test_fixed_files_and_no_base_allowlist_expansion():
    assert FILES[-1] not in WindowsCaptureFiles._names
    with pytest.raises(ValueError):
        parse_file('../session.json', b'{}')
    assert parse_file(FILES[0], b'{"schema_version":4}') == {'schema_version': 4}
    assert parse_file(FILES[-1], b'{"seq":0}\r\n{"seq":1}\n') == [{'seq': 0}, {'seq': 1}]
    assert parse_file(FILES[-1], b'') == []


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]',
                                    b'null', b'{"x":1e999}', b'{"x":[-1e999]}', b'\xff', b'{', b'{"a":{"b":1,"b":2}}'])
def test_strict_objects(raw):
    for name in (FILES[0], FILES[-1]):
        with pytest.raises(ValueError):
            parse_file(name, raw + (b'\n' if name == FILES[-1] else b''))


def test_exact_bounds_and_incomplete_tail():
    assert parse_file(FILES[0], b'{}' + b' ' * (CONTROL_BYTES - 2)) == {}
    for name, size in ((FILES[0], CONTROL_BYTES), (FILES[-1], EVIDENCE_BYTES)):
        with pytest.raises(ValueError, match='oversize'):
            parse_file(name, b' ' * (size + 1))
    with pytest.raises(ValueError, match='incomplete'):
        parse_file(FILES[-1], b'{}\n{}')
    with pytest.raises(ValueError, match='too_many'):
        parse_file(FILES[-1], b'{}\n' * (MAX_EVENTS + 1))
    assert len(parse_file(FILES[-1], b'{}\n' * MAX_EVENTS)) == MAX_EVENTS
    with pytest.raises(ValueError):
        parse_file(FILES[-1], b'{}\n\n')


def test_no_network_or_alias_paths():
    for path in (r'\\server\share\private', r'\\?\C:\private', 'https://example.test',
                 r'C:\private\..\elsewhere', r'C:\private\x:stream', r'C:private'):
        with pytest.raises(ValueError):
            _components(path)


def test_non_windows_refuses_transport(tmp_path):
    if os.name == 'nt':
        pytest.skip('non-Windows refusal')
    with pytest.raises(OSError, match='unsupported_platform'):
        WindowsFiniteFiles().read_snapshot(tmp_path)


windows = pytest.mark.skipif(os.name != 'nt', reason='requires actual Windows security and kernel handles')


def _secure_windows_test_object(path):
    """Provision only this test-created object, not a real producer directory.

    Elevated Windows tokens can default new objects to Administrators ownership.
    Production intentionally requires TOKEN_USER ownership, so establish that
    fixture prerequisite explicitly instead of weakening the production check.
    """
    import ctypes
    from football_assistant_data.windows_capture_files import HANDLE, DWORD, BOOL
    files = WindowsFiniteFiles()
    security = files.security
    security.ConvertSidToStringSidW.restype = BOOL
    security.ConvertSidToStringSidW.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = BOOL
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, DWORD, ctypes.POINTER(HANDLE), ctypes.POINTER(DWORD)]
    security.SetFileSecurityW.restype = BOOL
    security.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, DWORD, HANDLE]
    token, descriptor, old_descriptor, old_owner = HANDLE(), HANDLE(), HANDLE(), HANDLE()
    sid_text = ctypes.c_wchar_p()
    files._check(security.OpenProcessToken(files.api.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        size = DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        assert 0 < size.value <= 65536
        buffer = ctypes.create_string_buffer(size.value)
        files._check(security.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)))
        user_sid = ctypes.cast(buffer, ctypes.POINTER(HANDLE))[0]
        with files._open(str(path), 0x20080, 7, directory=path.is_dir()) as handle:
            result = security.GetSecurityInfo(handle, 1, 1, ctypes.byref(old_owner), None, None, None, ctypes.byref(old_descriptor))
            assert result == 0
            if not security.EqualSid(old_owner, user_sid):
                with pytest.raises(ValueError, match='finite_source_not_owned_by_current_user'):
                    files._owner(handle)  # Real non-owner negative, before provisioning.
            # Log categories only, never the account SID/name or private path.
            print('WINDOWS_TEST_FIXTURE_OWNER_BEFORE', {
                'current_user': bool(security.EqualSid(old_owner, user_sid)),
                'administrators': bool(security.IsWellKnownSid(old_owner, 26)),
            })
        files._check(security.ConvertSidToStringSidW(user_sid, ctypes.byref(sid_text)))
        # Protected DACL: this user, SYSTEM and Administrators only. Inheritance
        # applies to this disposable test directory's children, never ancestors.
        sddl = f'O:{sid_text.value}D:P(A;OICI;FA;;;{sid_text.value})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
        files._check(security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None))
        files._check(security.SetFileSecurityW(str(path), 0x80000005, descriptor))
        with files._open(str(path), 0x20080, 7, directory=path.is_dir()) as handle:
            files._owner(handle)  # Actual production owner/DACL guard, no mock.
    finally:
        for allocation in (descriptor, old_descriptor, sid_text):
            if allocation:
                files.api.LocalFree(ctypes.cast(allocation, HANDLE))
        files.api.CloseHandle(token)


def _private_windows_fixture(tmp_path):
    root = tmp_path / 'private'
    root.mkdir()
    _secure_windows_test_object(root)
    for name in FILES:
        child = root / name
        child.write_bytes(b'{}\n')
        _secure_windows_test_object(child)
    return root


@windows
def test_windows_snapshot_and_hardlink_rejection(tmp_path):
    root = _private_windows_fixture(tmp_path)
    files = WindowsFiniteFiles()
    assert files.read_snapshot(root) == ({}, {}, {}, [{}])
    (root / FILES[0]).unlink()
    os.link(root / FILES[1], root / FILES[0])
    with pytest.raises(ValueError, match='unsafe_control_file'):
        files.read_snapshot(root)


@windows
def test_windows_per_file_bounds(tmp_path):
    root = _private_windows_fixture(tmp_path)
    (root / FILES[0]).write_bytes(b'{}' + b' ' * CONTROL_BYTES)
    with pytest.raises(ValueError, match='oversize'):
        WindowsFiniteFiles().read_snapshot(root)


def test_lifetime_non_windows_refuses():
    from football_assistant_data.windows_finite_files import WindowsProducerLifetime
    if os.name == 'nt':
        pytest.skip('non-Windows refusal')
    with pytest.raises(OSError, match='unsupported_platform'):
        WindowsProducerLifetime(1, 2)


@windows
def test_windows_pinned_process_and_thread_lifetime():
    import ctypes
    from football_assistant_data.windows_finite_files import WindowsProducerLifetime
    kernel = ctypes.WinDLL('kernel32')
    lifetime = WindowsProducerLifetime(os.getpid(), kernel.GetCurrentThreadId())
    try:
        assert lifetime.alive()
    finally:
        lifetime.close()
    assert not lifetime.alive()
    lifetime.close()


@pytest.mark.parametrize('waits,expected', [([258, 258], True), ([0, 258], False),
                                         ([258, 0], False), ([0xffffffff, 258], False)])
def test_lifetime_wait_failures_clear_without_reopening_pid(waits, expected):
    from football_assistant_data.windows_finite_files import WindowsProducerLifetime
    class FakeKernel:
        def __init__(self):
            self.waits, self.closed = iter(waits), []
        def WaitForSingleObject(self, handle, timeout):
            assert handle in (111, 222) and timeout == 0
            return next(self.waits)
        def CloseHandle(self, handle):
            self.closed.append(handle)
    lifetime = WindowsProducerLifetime.__new__(WindowsProducerLifetime)
    lifetime.process, lifetime.thread, lifetime.window_class = 111, 222, None
    lifetime.api = FakeKernel()
    assert lifetime.alive() is expected
    lifetime.close()
    lifetime.close()
    assert lifetime.api.closed == [222, 111]
    assert lifetime.alive() is False


@pytest.mark.parametrize('relative', [False, True])
@pytest.mark.parametrize('directory', [False, True])
def test_all_finite_handles_request_read_control(monkeypatch, relative, directory):
    from contextlib import contextmanager
    calls = []
    @contextmanager
    def fake_open(self, *args):
        calls.append(args)
        yield 123
    method = '_open_relative' if relative else '_open'
    monkeypatch.setattr(WindowsCaptureFiles, method, fake_open)
    files = WindowsFiniteFiles.__new__(WindowsFiniteFiles)
    args = (77, 'session.json', 0xA1, 1, 3, directory) if relative else ('C:\\private', 0x81, 1, 3, directory)
    with getattr(files, method)(*args) as handle:
        assert handle == 123
    access_index = 2 if relative else 1
    assert calls[0][access_index] == args[access_index] | 0x20000
    assert calls[0][-1] is directory


@pytest.mark.parametrize('changed', [None, *FILES[:3]])
def test_snapshot_rechecks_all_bounded_control_files(changed):
    from contextlib import contextmanager
    class SyntheticFiles(WindowsFiniteFiles):
        def __init__(self):
            self.calls = []
        @contextmanager
        def directory(self, root):
            from types import SimpleNamespace
            assert root == 'explicit-test-only-root'
            yield SimpleNamespace(handle=123)
        def _owner(self, handle):
            assert handle == 123
        def _read_finite(self, directory, name):
            seen = name in self.calls
            self.calls.append(name)
            if name == FILES[-1]:
                return []
            return {'revision': 2 if name == changed and seen else 1}
    files = SyntheticFiles()
    if changed:
        with pytest.raises(ValueError, match='control_changed'):
            files.read_snapshot('explicit-test-only-root')
    else:
        assert files.read_snapshot('explicit-test-only-root') == ({'revision': 1},) * 3 + ([],)
        assert files.calls == list(FILES) + list(FILES[:3])
    assert len(files.calls) <= 7


@pytest.mark.parametrize('name', FILES)
def test_finite_read_shares_atomic_replacement_and_append(name):
    from contextlib import contextmanager
    from types import SimpleNamespace
    class StopRead(Exception):
        pass
    class SyntheticFiles(WindowsFiniteFiles):
        def __init__(self):
            pass
        @contextmanager
        def _open_relative(self, parent, selected, access, sharing):
            assert (parent, selected, access, sharing) == (123, name, 0x80000000, 7)
            raise StopRead
            yield
    with pytest.raises(StopRead):
        SyntheticFiles()._read_finite(SimpleNamespace(handle=123), name)


@pytest.mark.parametrize('admitted', [False, True])
def test_only_unconsumed_running_producer_may_await_first_evidence_file(admitted):
    from contextlib import contextmanager
    from types import SimpleNamespace
    class SyntheticFiles(WindowsFiniteFiles):
        def __init__(self): pass
        @contextmanager
        def directory(self, root): yield SimpleNamespace(handle=123)
        def _owner(self, handle): pass
        def _read_finite(self, directory, name):
            if name == FILES[-1]: raise FileNotFoundError('first event not written')
            if name == 'finite-rows-state.json':
                return dict(outcome='running',consumed=admitted,batch_id='bound-batch' if admitted else None)
            return {'session_id':'synthetic'}
    if admitted:
        with pytest.raises(FileNotFoundError): SyntheticFiles().read_snapshot('synthetic-root')
    else:
        assert SyntheticFiles().read_snapshot('synthetic-root')[-1] == []


def test_owner_mismatch_is_rejected_before_acl_check():
    """Default group ownership is not a production ownership exception."""
    import ctypes
    from types import SimpleNamespace
    from football_assistant_data.windows_capture_files import HANDLE, DWORD
    calls = []
    class Security:
        def OpenProcessToken(self, process, rights, token):
            ctypes.cast(token, ctypes.POINTER(HANDLE))[0] = 99
            return 1
        def GetTokenInformation(self, token, kind, buffer, length, size):
            ctypes.cast(size, ctypes.POINTER(DWORD))[0] = ctypes.sizeof(HANDLE)
            if buffer is not None:
                ctypes.cast(buffer, ctypes.POINTER(HANDLE))[0] = 123
            return 1
        def GetSecurityInfo(self, handle, kind, flags, owner, *rest):
            ctypes.cast(owner, ctypes.POINTER(HANDLE))[0] = 456
            return 0
        def EqualSid(self, owner, current):
            assert owner.value == 456 and current == 123
            return 0
    files = WindowsFiniteFiles.__new__(WindowsFiniteFiles)
    files.security = Security()
    files.api = SimpleNamespace(GetCurrentProcess=lambda: 1, CloseHandle=lambda handle: calls.append('closed'))
    files._require = lambda: None
    files._private_acl = lambda *args: calls.append('acl')
    with pytest.raises(ValueError, match='finite_source_not_owned_by_current_user'):
        files._owner(77)
    assert calls == ['closed']
