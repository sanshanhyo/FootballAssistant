"""Windows-only primitives for an explicitly approved normal-user acceptance run.

No import-time actions, credential handling, game calls, ownership transfer, or
POSIX fallback. Only explicit harden/create/write/stage calls mutate objects.
"""
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import ntpath
import os
from pathlib import Path
import re
import uuid

from .windows_capture_files import (
    WindowsCaptureFiles, DWORD, HANDLE, BOOL, _ObjectAttributes, _UnicodeString,
    _IoStatusBlock, _Directory, _RenameInfo, _components,
)
from .windows_finite_files import WindowsFiniteFiles, _object

EXPECTED_ACCOUNT = 'ALAWELL\\Husky'
CONTROLS = ('session.json', 'module-status.json', 'finite-rows-state.json')
CAPTURE_FILES = CONTROLS + ('finite-rows-evidence.jsonl', 'finite-rows-request.json')
WRITABLE_NAMES = ('settings.json', 'finite-rows-request.json')


def private_sddl(sid):
    if not isinstance(sid, str) or re.fullmatch(r'S-\d+(?:-\d+)+', sid) is None:
        raise ValueError('invalid_user_sid')
    return f'O:{sid}D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'


def validate_user_data_name(name):
    if not isinstance(name, str) or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name) is None:
        raise ValueError('invalid_acceptance_directory_name')
    return name


class AcceptanceFiles(WindowsFiniteFiles):
    def __init__(self):
        super().__init__()
        self._verified = False
        self._sid_text = None
        if not self.supported:
            return
        self.nt.NtSetSecurityObject.restype = ctypes.c_int32
        self.nt.NtSetSecurityObject.argtypes = [HANDLE, DWORD, HANDLE]
        for name, result, arguments in (
            ('LookupAccountSidW', BOOL, [ctypes.c_wchar_p, HANDLE, ctypes.c_wchar_p, ctypes.POINTER(DWORD), ctypes.c_wchar_p, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD)]),
            ('ConvertSidToStringSidW', BOOL, [HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]),
            ('ConvertStringSecurityDescriptorToSecurityDescriptorW', BOOL, [ctypes.c_wchar_p, DWORD, ctypes.POINTER(HANDLE), ctypes.POINTER(DWORD)]),
            ('GetSecurityDescriptorDacl', BOOL, [HANDLE, ctypes.POINTER(BOOL), ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
            ('SetSecurityInfo', DWORD, [HANDLE, ctypes.c_int, DWORD, HANDLE, HANDLE, HANDLE, HANDLE]),
        ):
            function = getattr(self.security, name)
            function.restype, function.argtypes = result, arguments

    def _info(self, handle, *, directory=False, bounded=True):
        # Each public operation applies its own explicit bound (artifacts differ
        # from JSON). Keep the common regular-file/single-link/reparse checks.
        return WindowsCaptureFiles._info(self, handle, directory=directory, bounded=False)

    @contextmanager
    def _token_user(self):
        self._require()
        token = HANDLE()
        self._check(self.security.OpenProcessToken(self.api.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            size = DWORD()
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 0 < size.value <= 65536:
                raise ValueError('invalid_owner_token')
            memory = ctypes.create_string_buffer(size.value)
            self._check(self.security.GetTokenInformation(token, 1, memory, size.value, ctypes.byref(size)))
            sid = ctypes.cast(memory, ctypes.POINTER(HANDLE))[0]
            yield token, sid
        finally:
            self.api.CloseHandle(token)

    def verify_user(self):
        self._verified = False
        with self._token_user() as (token, sid):
            name_size, domain_size, use = DWORD(512), DWORD(512), DWORD()
            name, domain = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(512)
            self._check(self.security.LookupAccountSidW(None, sid, name, ctypes.byref(name_size), domain, ctypes.byref(domain_size), ctypes.byref(use)))
            if domain.value + '\\' + name.value != EXPECTED_ACCOUNT:
                raise ValueError('normal_husky_identity_required')
            elevated, size = DWORD(), DWORD()
            self._check(self.security.GetTokenInformation(token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)))
            if size.value != ctypes.sizeof(elevated) or elevated.value != 0:
                raise ValueError('non_elevated_normal_user_required')
            sid_text = ctypes.c_wchar_p()
            self._check(self.security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)))
            try:
                private_sddl(sid_text.value)
                self._sid_text = sid_text.value
            finally:
                self.api.LocalFree(ctypes.cast(sid_text, HANDLE))
        self._verified = True
        return {'normal_user_verified': True, 'elevated': False}

    def _require_user(self):
        if not self._verified:
            self.verify_user()

    def _owner_only(self, handle):
        with self._token_user() as (_, sid):
            owner, descriptor = HANDLE(), HANDLE()
            try:
                result = self.security.GetSecurityInfo(handle, 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
                if result:
                    raise ctypes.WinError(result)
                if not owner.value or not self.security.EqualSid(owner, sid):
                    raise ValueError('source_not_owned_by_current_user')
            finally:
                if descriptor.value:
                    self.api.LocalFree(descriptor)

    @contextmanager
    def _descriptor(self):
        descriptor = HANDLE()
        self._check(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(private_sddl(self._sid_text), 1, ctypes.byref(descriptor), None))
        try:
            yield descriptor
        finally:
            self.api.LocalFree(descriptor)

    def _read_json(self, directory, name, limit, *, private=True):
        with self._open_relative(directory.handle, name, 0x80000000, 7) as handle:
            (self._owner if private else self._owner_only)(handle)
            before = self._info(handle)
            if before.size_high or not 0 < before.size_low <= limit:
                raise ValueError('control_file_outside_bound')
            buffer, count = ctypes.create_string_buffer(limit + 1), DWORD()
            self._check(self.api.ReadFile(handle, buffer, limit + 1, ctypes.byref(count), None))
            after = self._info(handle)
            if count.value != before.size_low or after.size_low != before.size_low or after.size_high:
                raise ValueError('control_changed_during_read')
            return _object(buffer.raw[:count.value])

    def read_control(self, root, name, private=True):
        if name not in CONTROLS:
            raise ValueError('invalid_control_filename')
        with self.directory(root) as directory:
            (self._owner if private else self._owner_only)(directory.handle)
            return self._read_json(directory, name, 8192, private=private)

    def assert_unused(self, root):
        with self.directory(root) as directory:
            self._owner_only(directory.handle)
            for name in ('finite-rows-request.json', 'finite-rows-evidence.jsonl'):
                try:
                    with self._open_relative(directory.handle, name, 0x80, 7) as handle:
                        self._owner_only(handle)
                        info = self._info(handle)
                        if name.endswith('.json') or info.size_high or info.size_low:
                            raise ValueError('prior_request_or_evidence_requires_separate_archive')
                except FileNotFoundError:
                    pass

    def harden_capture(self, root):
        self._require_user()
        raw = os.fspath(root)
        _components(raw)
        if ntpath.basename(raw) != 'windows-finite-rows-private':
            raise ValueError('fixed_capture_directory_required')
        with self.directory(ntpath.dirname(raw)) as parent, ExitStack() as stack:
            handle = stack.enter_context(self._open_relative(parent.handle, ntpath.basename(raw), 0x600A1, 3, directory=True))
            targets = [handle]
            self._owner_only(handle)
            for name in CAPTURE_FILES:
                try:
                    child = stack.enter_context(self._open_relative(handle, name, 0x60080, 1))
                except FileNotFoundError:
                    continue
                self._owner_only(child)
                info = self._info(child)
                if info.size_high or info.size_low > (262144 if name.endswith('.jsonl') else 8192):
                    raise ValueError('capture_file_outside_bound')
                targets.append(child)
            # All existing owners/types have passed before changing any DACL.
            with self._descriptor() as descriptor:
                present, defaulted, dacl = BOOL(), BOOL(), HANDLE()
                self._check(self.security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)))
                if not present.value or not dacl.value:
                    raise ValueError('invalid_private_dacl')
                for target in targets:
                    # OWNER_SECURITY_INFORMATION is intentionally absent.
                    # Native handle operation does not recursively propagate
                    # inheritable ACEs onto non-allowlisted existing children.
                    self._check_nt(self.nt.NtSetSecurityObject(target, 0x80000004, descriptor))
                    self._owner(target)

    @contextmanager
    def _create_directory_relative(self, parent, name, descriptor):
        encoded = name.encode('utf-16-le')
        memory = ctypes.create_string_buffer(encoded)
        unicode = _UnicodeString(len(encoded), len(encoded), ctypes.addressof(memory))
        attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(unicode), 0x1040, descriptor, None)
        handle, io = HANDLE(), _IoStatusBlock()
        status = self.nt.NtCreateFile(ctypes.byref(handle), 0x1200A1, ctypes.byref(attributes), ctypes.byref(io), None, 0x10, 3, 2, 0x00200021, None, 0)
        self._check_nt(status)  # FILE_CREATE: never opens or modifies an existing name.
        try:
            self._check_nt(io.value.status)
            self._info(handle, directory=True)
            self._owner(handle)
            yield handle.value
        finally:
            self.api.CloseHandle(handle)

    @contextmanager
    def _create_private_file(self, parent, name):
        # Explicit TOKEN_USER owner at creation also avoids elevated CI tokens'
        # Administrators default owner. Never changes ownership of existing data.
        if not name or any(c in name for c in '/\\:\x00') or name in ('.', '..'):
            raise ValueError('single_control_component_required')
        encoded = name.encode('utf-16-le')
        memory = ctypes.create_string_buffer(encoded)
        unicode = _UnicodeString(len(encoded), len(encoded), ctypes.addressof(memory))
        with self._descriptor() as descriptor:
            attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(unicode), 0x1040, descriptor, None)
            handle, io = HANDLE(), _IoStatusBlock()
            status = self.nt.NtCreateFile(ctypes.byref(handle), 0x40130080, ctypes.byref(attributes), ctypes.byref(io), None, 0x80, 0, 2, 0x00200060, None, 0)
            self._check_nt(status)
            try:
                try:
                    self._check_nt(io.value.status)
                    self._info(handle)
                    self._owner(handle)
                except Exception:
                    self._delete_owned(handle)
                    raise
                yield handle.value
            finally:
                self.api.CloseHandle(handle)

    def create_user_data(self, name):
        self._require_user()
        validate_user_data_name(name)
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            raise ValueError('local_app_data_required')
        _components(local)
        with self.directory(local) as parent, self._descriptor() as descriptor, ExitStack() as stack:
            self._owner_only(parent.handle)
            try:
                base = stack.enter_context(self._create_directory_relative(parent.handle, 'FootballAssistantAcceptance', descriptor))
            except FileExistsError:
                base = stack.enter_context(self._open_relative(parent.handle, 'FootballAssistantAcceptance', 0xA1, 3, directory=True))
                self._owner(base)
            with self._create_directory_relative(base, name, descriptor):
                pass
        return Path(local) / 'FootballAssistantAcceptance' / name

    def write_new(self, root, name, payload):
        self._require_user()
        if name not in WRITABLE_NAMES or not isinstance(payload, bytes) or not 0 < len(payload) <= 4096:
            raise ValueError('invalid_new_control_file')
        _object(payload)
        with self.directory(root) as directory:
            self._owner(directory.handle)
            temporary = '.acceptance-' + uuid.uuid4().hex
            with self._create_private_file(directory.handle, temporary) as handle:
                published = False
                try:
                    self._owner(handle)
                    buffer, count = ctypes.create_string_buffer(payload), DWORD()
                    self._check(self.api.WriteFile(handle, buffer, len(payload), ctypes.byref(count), None))
                    if count.value != len(payload):
                        raise OSError('short_control_write')
                    self._check(self.api.FlushFileBuffers(handle))
                    encoded = name.encode('utf-16-le')
                    size = max(ctypes.sizeof(_RenameInfo), _RenameInfo.name.offset + len(encoded))
                    memory = ctypes.create_string_buffer(size)
                    info = _RenameInfo.from_buffer(memory)
                    info.replace, info.root, info.length = 0, directory.handle, len(encoded)
                    ctypes.memmove(ctypes.addressof(memory) + _RenameInfo.name.offset, encoded, len(encoded))
                    io = _IoStatusBlock()
                    self._check_nt(self.nt.NtSetInformationFile(handle, ctypes.byref(io), memory, size, 10))
                    self._check_nt(io.value.status)
                    published = True
                finally:
                    if not published:
                        self._delete_owned(handle)

    def read_runtime(self, user_data):
        with self.directory(user_data) as root:
            self._owner(root.handle)
            with self._open_relative(root.handle, 'backend', 0xA1, 3, directory=True) as backend:
                self._owner(backend)
                return self._read_json(_Directory(backend), 'runtime.json', 16384)

    def hash_local_file(self, path, max_bytes):
        if type(max_bytes) is not int or not 0 < max_bytes <= 2 * 1024 ** 3:
            raise ValueError('invalid_hash_bound')
        raw = os.fspath(path)
        _components(raw)
        with self.directory(ntpath.dirname(raw)) as parent:
            # No WRITE/DELETE sharing: bytes cannot change while this handle is held.
            with self._open_relative(parent.handle, ntpath.basename(raw), 0x80000000, 1) as handle:
                info = self._info(handle)
                expected = (info.size_high << 32) | info.size_low
                if not 0 < expected <= max_bytes:
                    raise ValueError('artifact_outside_bound')
                digest, total = hashlib.sha256(), 0
                buffer, count = ctypes.create_string_buffer(512 * 1024), DWORD()
                while total < expected:
                    self._check(self.api.ReadFile(handle, buffer, min(len(buffer), expected - total), ctypes.byref(count), None))
                    if not count.value:
                        raise ValueError('artifact_short_read')
                    total += count.value
                    digest.update(buffer.raw[:count.value])
                after = self._info(handle)
                if ((after.size_high << 32) | after.size_low) != expected:
                    raise ValueError('artifact_changed_during_read')
                return digest.hexdigest()

    def read_plan(self, path):
        raw = os.fspath(path)
        _components(raw)
        with self.directory(ntpath.dirname(raw)) as parent:
            with self._open_relative(parent.handle, ntpath.basename(raw), 0x80000000, 1) as handle:
                info = self._info(handle)
                if info.size_high or not 0 < info.size_low <= 8192:
                    raise ValueError('plan_outside_bound')
                buffer, count = ctypes.create_string_buffer(8193), DWORD()
                self._check(self.api.ReadFile(handle, buffer, 8193, ctypes.byref(count), None))
                after = self._info(handle)
                if count.value != info.size_low or after.size_high or after.size_low != count.value:
                    raise ValueError('plan_changed_during_read')
                return buffer.raw[:count.value]

    def stage_portable(self, source, user_data, expected_sha256):
        self._require_user()
        if not isinstance(expected_sha256, str) or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
            raise ValueError('invalid_portable_sha256')
        raw = os.fspath(source)
        _components(raw)
        name = 'FootballAssistant-verified.exe'
        with self.directory(ntpath.dirname(raw)) as parent, self.directory(user_data) as destination:
            self._owner(destination.handle)
            with self._open_relative(parent.handle, ntpath.basename(raw), 0x80000000, 1) as incoming:
                info = self._info(incoming)
                size = (info.size_high << 32) | info.size_low
                if not 0 < size <= 2 * 1024 ** 3:
                    raise ValueError('portable_outside_bound')
                with self._create_private_file(destination.handle, name) as outgoing:
                    accepted = False
                    try:
                        self._owner(outgoing)
                        digest, total = hashlib.sha256(), 0
                        buffer, count, written = ctypes.create_string_buffer(512 * 1024), DWORD(), DWORD()
                        while total < size:
                            self._check(self.api.ReadFile(incoming, buffer, min(len(buffer), size - total), ctypes.byref(count), None))
                            if not count.value:
                                raise ValueError('portable_short_read')
                            self._check(self.api.WriteFile(outgoing, buffer, count.value, ctypes.byref(written), None))
                            if written.value != count.value:
                                raise OSError('portable_short_write')
                            digest.update(buffer.raw[:count.value])
                            total += count.value
                        after = self._info(incoming)
                        if (after.size_high << 32) | after.size_low != size:
                            raise ValueError('portable_changed_during_read')
                        self._check(self.api.FlushFileBuffers(outgoing))
                        if digest.hexdigest() != expected_sha256:
                            raise ValueError('portable_hash_mismatch')
                        accepted = True
                    finally:
                        if not accepted:
                            self._delete_owned(outgoing)
        return Path(user_data) / name
