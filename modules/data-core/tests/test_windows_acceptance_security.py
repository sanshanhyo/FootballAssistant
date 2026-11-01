"""Portable policy checks and explicitly gated real Windows kernel checks."""
import ctypes
import hashlib
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from football_assistant_data.windows_acceptance_security import (
    AcceptanceFiles, EXPECTED_ACCOUNT, private_sddl, validate_user_data_name,
)


def test_private_descriptor_has_only_exact_owner_system_admin():
    assert EXPECTED_ACCOUNT == 'ALAWELL\\Husky'
    assert private_sddl('S-1-5-21-123') == 'O:S-1-5-21-123D:P(A;OICI;FA;;;S-1-5-21-123)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    for value in (None, '', 'BA', 'S-1-5);(A;;FA;;;WD)', 'S-1-5 '):
        with pytest.raises(ValueError, match='invalid_user_sid'):
            private_sddl(value)


@pytest.mark.parametrize('name', ['', '../x', 'a/b', 'a\\b', 'name:', 'Name', 'a'*65, None])
def test_new_directory_name_cannot_escape(name):
    with pytest.raises(ValueError, match='invalid_acceptance_directory_name'):
        validate_user_data_name(name)


def test_new_directory_name_valid():
    assert validate_user_data_name('capture-20261101') == 'capture-20261101'


def test_mutations_require_identity_before_any_filesystem(monkeypatch):
    files = AcceptanceFiles()
    def refuse():
        raise ValueError('normal_husky_identity_required')
    monkeypatch.setattr(files, 'verify_user', refuse)
    for operation in (lambda: files.harden_capture('x'), lambda: files.create_user_data('x'),
                      lambda: files.write_new('x', 'settings.json', b'{}'),
                      lambda: files.stage_portable('x', 'y', '0'*64)):
        with pytest.raises(ValueError, match='normal_husky_identity_required'):
            operation()


def test_filename_and_write_payload_allowlist(monkeypatch):
    files = AcceptanceFiles()
    monkeypatch.setattr(files, '_require_user', lambda: None)
    for name, payload in [('../settings.json', b'{}'), ('runtime.json', b'{}'),
                          ('settings.json', b''), ('settings.json', b' '*4097),
                          ('settings.json', '{}'), ('settings.json', b'{"x":1,"x":2}')]:
        with pytest.raises(ValueError):
            files.write_new('not-accessed', name, payload)
    with pytest.raises(ValueError, match='invalid_control_filename'):
        files.read_control('not-accessed', 'finite-rows-request.json')


def test_bounds_fail_before_open():
    files = AcceptanceFiles()
    for bound in (True, 0, -1, 2*1024**3+1):
        with pytest.raises(ValueError, match='invalid_hash_bound'):
            files.hash_local_file('not-accessed', bound)


def test_no_posix_transport_fallback():
    if os.name == 'nt':
        pytest.skip('non-Windows refusal')
    with pytest.raises(OSError, match='unsupported_platform'):
        AcceptanceFiles().verify_user()


windows = pytest.mark.skipif(os.name != 'nt', reason='requires Windows kernel and token security')


def _fixture(tmp_path):
    from test_windows_finite_files import _secure_windows_test_object
    root = tmp_path / 'windows-finite-rows-private'
    root.mkdir()
    _secure_windows_test_object(root)
    files = AcceptanceFiles()
    # Test-created objects only: no production identity policy is relaxed.
    # Tests exercise primitive Windows operations as the CI user's SID.
    with files._token_user() as (_, sid):
        text = ctypes.c_wchar_p()
        files._check(files.security.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            files._sid_text = text.value
        finally:
            files.api.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    files._verified = True
    return files, root, _secure_windows_test_object


@windows
def test_windows_atomic_new_write_refuses_overwrite_and_consumed(tmp_path):
    files, root, _ = _fixture(tmp_path)
    files.assert_unused(root)
    files.write_new(root, 'finite-rows-request.json', b'{"test":1}')
    assert (root / 'finite-rows-request.json').read_bytes() == b'{"test":1}'
    with pytest.raises(FileExistsError):
        files.write_new(root, 'finite-rows-request.json', b'{"test":2}')
    assert (root / 'finite-rows-request.json').read_bytes() == b'{"test":1}'
    assert not list(root.glob('.acceptance-*'))
    with pytest.raises(ValueError, match='prior_request'):
        files.assert_unused(root)


@windows
def test_windows_reads_bounds_and_hash_hardlink_refusal(tmp_path):
    files, root, secure = _fixture(tmp_path)
    control = root / 'session.json'
    control.write_bytes(b'{}')
    secure(control)
    assert files.read_control(root, 'session.json') == {}
    assert files.read_plan(control) == b'{}'
    assert files.hash_local_file(control, 10) == hashlib.sha256(b'{}').hexdigest()
    control.write_bytes(b' ' * 8193)
    with pytest.raises(ValueError, match='outside_bound'):
        files.read_control(root, 'session.json')
    os.link(control, root / 'other.json')
    with pytest.raises(ValueError, match='unsafe_control_file'):
        files.hash_local_file(control, 10000)


@windows
def test_windows_private_directory_at_creation_and_portable_copy(tmp_path, monkeypatch):
    files, root, secure = _fixture(tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(root))
    data = files.create_user_data('one-shot')
    with files.directory(data) as directory:
        files._owner(directory.handle)
    with pytest.raises(FileExistsError):
        files.create_user_data('one-shot')
    source = root / 'source.exe'
    source.write_bytes(b'not-an-executable-test-fixture')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='portable_hash_mismatch'):
        files.stage_portable(source, data, '0'*64)
    assert not (data / 'FootballAssistant-verified.exe').exists()
    destination = files.stage_portable(source, data, digest)
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        files.stage_portable(source, data, digest)


@windows
def test_windows_hardening_preserves_owner_and_fixed_scope(tmp_path):
    files, root, secure = _fixture(tmp_path)
    control = root / 'session.json'
    control.write_bytes(b'{}')
    secure(control)
    files.harden_capture(root)
    assert files.read_control(root, 'session.json') == {}
    # Existing hardlinks must reject before any DACL mutation.
    os.link(control, root / 'module-status.json')
    with pytest.raises(ValueError, match='unsafe_control_file'):
        files.harden_capture(root)


@pytest.mark.parametrize('domain,name,elevated,error', [
    ('ALAWELL', 'CodexSandboxOffline', 0, 'normal_husky_identity_required'),
    ('OTHER', 'Husky', 0, 'normal_husky_identity_required'),
    ('ALAWELL', 'Husky', 1, 'non_elevated_normal_user_required'),
])
def test_token_identity_and_elevation_refuse_before_descriptor(monkeypatch, domain, name, elevated, error):
    files = AcceptanceFiles()
    @contextmanager
    def token():
        yield 1, 2
    def lookup(_system, _sid, account, _account_size, account_domain, _domain_size, _use):
        account.value, account_domain.value = name, domain
        return 1
    def information(_token, kind, value, length, returned):
        assert kind == 20
        ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32))[0] = elevated
        ctypes.cast(returned, ctypes.POINTER(ctypes.c_uint32))[0] = 4
        return 1
    monkeypatch.setattr(files, '_token_user', token)
    files.security = SimpleNamespace(LookupAccountSidW=lookup, GetTokenInformation=information)
    with pytest.raises(ValueError, match=error):
        files.verify_user()
    assert files._verified is False


def test_unused_does_not_suppress_permission_errors(monkeypatch):
    files = AcceptanceFiles()
    @contextmanager
    def directory(_):
        yield SimpleNamespace(handle=1)
    @contextmanager
    def denied(*args, **kwargs):
        raise PermissionError('test-access-denied')
        yield
    monkeypatch.setattr(files, 'directory', directory)
    monkeypatch.setattr(files, '_owner_only', lambda handle: None)
    monkeypatch.setattr(files, '_open_relative', denied)
    with pytest.raises(PermissionError):
        files.assert_unused('unused')


@pytest.mark.parametrize('bad_owner', [False, True])
def test_hardening_all_owners_preflight_and_exact_dacl_only_handles(monkeypatch, bad_owner):
    files = AcceptanceFiles()
    events = []
    @contextmanager
    def directory(_):
        yield SimpleNamespace(handle=1)
    @contextmanager
    def opened(parent, name, *args, **kwargs):
        handle = 2 if kwargs.get('directory') else 3 + list(
            ('session.json', 'module-status.json', 'finite-rows-state.json',
             'finite-rows-evidence.jsonl', 'finite-rows-request.json')).index(name)
        yield handle
    @contextmanager
    def descriptor():
        yield 100
    def owner(handle):
        events.append(('owner', handle))
        if bad_owner and handle == 7:
            raise ValueError('source_not_owned_by_current_user')
    def get_dacl(_descriptor, present, dacl, _defaulted):
        ctypes.cast(present, ctypes.POINTER(ctypes.c_int32))[0] = 1
        ctypes.cast(dacl, ctypes.POINTER(ctypes.c_void_p))[0] = 100
        return 1
    def set_dacl(handle, flags, _descriptor):
        events.append(('dacl', handle, flags))
        assert len([e for e in events if e[0] == 'owner']) == 6
        return 0
    monkeypatch.setattr(files, '_require_user', lambda: None)
    monkeypatch.setattr(files, 'directory', directory)
    monkeypatch.setattr(files, '_open_relative', opened)
    monkeypatch.setattr(files, '_owner_only', owner)
    monkeypatch.setattr(files, '_owner', lambda handle: None)
    monkeypatch.setattr(files, '_info', lambda handle: SimpleNamespace(size_low=2, size_high=0))
    monkeypatch.setattr(files, '_descriptor', descriptor)
    files.security = SimpleNamespace(GetSecurityDescriptorDacl=get_dacl)
    files.nt = SimpleNamespace(NtSetSecurityObject=set_dacl)
    if bad_owner:
        with pytest.raises(ValueError, match='source_not_owned'):
            files.harden_capture(r'C:\approved\windows-finite-rows-private')
        assert not [e for e in events if e[0] == 'dacl']
    else:
        files.harden_capture(r'C:\approved\windows-finite-rows-private')
        assert [e for e in events if e[0] == 'dacl'] == [('dacl', h, 0x80000004) for h in range(2, 8)]
