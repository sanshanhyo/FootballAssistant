"""Read-only, bounded transport for one explicitly configured Windows producer.

This is not source registration: caller supplies an independently approved binding.
No renderer paths, network paths, POSIX fallback, or game access are supported.
"""
from contextlib import contextmanager
import ctypes
import json
import math

from .windows_capture_files import WindowsCaptureFiles, DWORD, HANDLE, BOOL, _unique

CONTROL_BYTES = 8192
EVIDENCE_BYTES = 262144
MAX_EVENTS = 64
FILES = ('session.json', 'module-status.json', 'finite-rows-state.json',
         'finite-rows-evidence.jsonl')


def _reject_constant(_):
    raise ValueError('invalid_json_number')


def _object(raw):
    try:
        value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=_unique,
                           parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('invalid_finite_json') from None
    if not isinstance(value, dict):
        raise ValueError('invalid_finite_object')
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError('invalid_json_number')
    return value


def parse_file(name, raw):
    """Pure parser also used by synthetic tests, never a filesystem fallback."""
    if name not in FILES or not isinstance(raw, bytes):
        raise ValueError('invalid_finite_filename')
    bound = EVIDENCE_BYTES if name == FILES[-1] else CONTROL_BYTES
    if len(raw) > bound:
        raise ValueError('oversize_finite_file')
    if name != FILES[-1]:
        return _object(raw)
    if raw and not raw.endswith(b'\n'):
        raise ValueError('incomplete_finite_event')
    lines = raw.splitlines()
    if len(lines) > MAX_EVENTS:
        raise ValueError('too_many_finite_events')
    return [_object(line) for line in lines]


class WindowsFiniteFiles(WindowsCaptureFiles):
    """Reuse handle-pinned traversal, adding owner verification and larger bounds.

    Current-user ownership is necessary, not proof that producer contents are true.
    Binding validation remains the caller's responsibility. Other processes running
    as this user are outside the file transport's trust boundary.
    """
    def __init__(self):
        super().__init__()
        if not self.supported:
            return
        self.security = ctypes.WinDLL('advapi32', use_last_error=True)
        for name, result, arguments in (
            ('OpenProcessToken', BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
            ('GetTokenInformation', BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD, ctypes.POINTER(DWORD)]),
            ('GetSecurityInfo', DWORD, [HANDLE, ctypes.c_int, DWORD, ctypes.POINTER(HANDLE),
                ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE)]),
            ('EqualSid', BOOL, [HANDLE, HANDLE]),
            ('GetAce', BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
            ('IsWellKnownSid', BOOL, [HANDLE, ctypes.c_int]),
        ):
            function = getattr(self.security, name)
            function.restype, function.argtypes = result, arguments
        self.api.GetCurrentProcess.restype = HANDLE
        self.api.GetCurrentProcess.argtypes = []
        self.api.LocalFree.restype = HANDLE
        self.api.LocalFree.argtypes = [HANDLE]

    @contextmanager
    def _open(self, path, access, sharing, disposition=3, directory=False):
        with super()._open(path, access | 0x20000, sharing, disposition, directory) as handle:
            yield handle

    @contextmanager
    def _open_relative(self, parent, name, access, sharing, disposition=3, directory=False):
        with super()._open_relative(parent, name, access | 0x20000, sharing, disposition, directory) as handle:
            yield handle

    def _info(self, handle, *, directory=False, bounded=True):
        info = super()._info(handle, directory=directory, bounded=False)
        if not directory and bounded and (info.size_high or info.size_low > EVIDENCE_BYTES):
            raise ValueError('oversize_finite_file')
        return info

    def _owner(self, handle):
        self._require()
        token, descriptor, owner, dacl = HANDLE(), HANDLE(), HANDLE(), HANDLE()
        self._check(self.security.OpenProcessToken(self.api.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            size = DWORD()
            # TOKEN_USER includes a SID pointer and attributes; allocate from API's
            # required length, capped rather than trusting an unbounded allocation.
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 0 < size.value <= 65536:
                raise ValueError('invalid_owner_token')
            buffer = ctypes.create_string_buffer(size.value)
            self._check(self.security.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)))
            status = self.security.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None,
                                                   ctypes.byref(descriptor))
            if status:
                raise ctypes.WinError(status)
            sid = ctypes.cast(buffer, ctypes.POINTER(HANDLE))[0]
            if not owner.value or not self.security.EqualSid(owner, sid):
                raise ValueError('finite_source_not_owned_by_current_user')
            self._private_acl(dacl, sid)
        finally:
            if descriptor.value:
                self.api.LocalFree(descriptor)
            self.api.CloseHandle(token)

    def _private_acl(self, dacl, owner_sid):
        # Refuse null DACLs and write grants to other users/groups. Current user,
        # SYSTEM and built-in Administrators are the local trusted principals.
        # Unknown/object/callback ACEs fail closed rather than approximating ACLs.
        if not dacl.value:
            raise ValueError('unsafe_finite_acl')
        header = ctypes.string_at(dacl, 8)
        count = int.from_bytes(header[4:6], 'little')
        write_mask = 0x10000000 | 0x40000000 | 0x10000 | 0x40000 | 0x80000 | 0x156
        for index in range(count):
            ace = HANDLE()
            self._check(self.security.GetAce(dacl, index, ctypes.byref(ace)))
            head = ctypes.string_at(ace, 4)
            if head[1] & 8 or head[0] == 1:  # inherit-only / deny
                continue
            if head[0] != 0 or int.from_bytes(head[2:4], 'little') < 12:
                raise ValueError('unsupported_finite_acl')
            mask = int.from_bytes(ctypes.string_at(ace.value + 4, 4), 'little')
            sid = HANDLE(ace.value + 8)
            if mask & write_mask and not (
                self.security.EqualSid(sid, owner_sid)
                or self.security.IsWellKnownSid(sid, 22)  # LocalSystemSid
                or self.security.IsWellKnownSid(sid, 26)  # BuiltinAdministratorsSid
            ):
                raise ValueError('unsafe_finite_acl')

    def _read_finite(self, directory, name):
        if name not in FILES:
            raise ValueError('invalid_finite_filename')
        limit = EVIDENCE_BYTES if name == FILES[-1] else CONTROL_BYTES
        # Producer atomically replaces control files and appends evidence. Allow
        # READ | WRITE | DELETE sharing without following replacement objects:
        # this held handle remains pinned, no-reparse and owner/ACL checked.
        # Size changes, partial JSONL tails and control rereads fail closed.
        with self._open_relative(directory.handle, name, 0x80000000, 7) as handle:
            self._owner(handle)
            info = self._info(handle)
            if info.size_high or info.size_low > limit:
                raise ValueError('oversize_finite_file')
            buffer, count = ctypes.create_string_buffer(limit + 1), DWORD()
            self._check(self.api.ReadFile(handle, buffer, limit + 1, ctypes.byref(count), None))
            after = self._info(handle)
            if count.value != info.size_low or after.size_low != info.size_low:
                raise ValueError('finite_file_changed_during_read')
            return parse_file(name, buffer.raw[:count.value])

    def read_snapshot(self, root):
        with self.directory(root) as directory:
            self._owner(directory.handle)
            session, module, state = (self._read_finite(directory, name) for name in FILES[:3])
            try:
                events = self._read_finite(directory, FILES[-1])
            except FileNotFoundError:
                # The producer creates JSONL only on its first event. This is
                # not a missing control file or missing admitted-batch evidence.
                if state.get('outcome') != 'running' or state.get('consumed') is not False or state.get('batch_id') is not None:
                    raise
                events = []
            # Detect producer turnover while reading separate files. Full logical
            # source/session validation still occurs in the consuming adapter.
            for name, previous in zip(FILES[:3], (session, module, state)):
                if previous != self._read_finite(directory, name):
                    raise ValueError('finite_control_changed_during_read')
            return session, module, state, events


class WindowsProducerLifetime:
    """Pin producer process/thread lifetimes; never reopen a reused PID/TID.

    Optional exact window class is independently supplied registration context,
    not evidence-selected. No memory access, injection or native game invocation.
    """
    def __init__(self, pid, entry_tid, window_class=None):
        import os
        if os.name != 'nt':
            raise OSError('unsupported_platform')
        if type(pid) is not int or type(entry_tid) is not int or not 0 < pid <= 0xffffffff or not 0 < entry_tid <= 0xffffffff:
            raise ValueError('invalid_producer_identity')
        if window_class is not None and (not isinstance(window_class, str) or not 0 < len(window_class) <= 256
                                         or '\0' in window_class):
            raise ValueError('invalid_window_class')
        self.pid, self.entry_tid, self.window_class = pid, entry_tid, window_class
        self.process, self.thread = None, None
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, result, args in (
            ('OpenProcess', HANDLE, [DWORD, BOOL, DWORD]),
            ('OpenThread', HANDLE, [DWORD, BOOL, DWORD]),
            ('GetProcessIdOfThread', DWORD, [HANDLE]),
            ('WaitForSingleObject', DWORD, [HANDLE, DWORD]),
            ('CloseHandle', BOOL, [HANDLE]),
        ):
            function = getattr(self.api, name)
            function.restype, function.argtypes = result, args
        try:
            self.process = self.api.OpenProcess(0x100000 | 0x1000, False, pid)
            if not self.process:
                raise ctypes.WinError(ctypes.get_last_error())
            self.thread = self.api.OpenThread(0x100000 | 0x800, False, entry_tid)
            if not self.thread:
                raise ctypes.WinError(ctypes.get_last_error())
            if self.api.GetProcessIdOfThread(self.thread) != pid:
                raise ValueError('producer_thread_process_mismatch')
            if not self.alive():
                raise ValueError('producer_not_live')
        except BaseException:
            self.close()
            raise

    def alive(self):
        if not self.process or not self.thread or any(
            self.api.WaitForSingleObject(handle, 0) != 258 for handle in (self.process, self.thread)
        ):
            return False
        if self.window_class is None:
            return True
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(BOOL, HANDLE, ctypes.c_ssize_t)
        user.EnumWindows.restype, user.EnumWindows.argtypes = BOOL, [callback_type, ctypes.c_ssize_t]
        user.GetWindowThreadProcessId.restype = DWORD
        user.GetWindowThreadProcessId.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
        user.GetClassNameW.restype, user.GetClassNameW.argtypes = ctypes.c_int, [HANDLE, ctypes.c_wchar_p, ctypes.c_int]
        user.IsWindowVisible.restype, user.IsWindowVisible.argtypes = BOOL, [HANDLE]
        matches = []

        @callback_type
        def visit(window, _):
            pid = DWORD()
            tid = user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value == self.pid and tid == self.entry_tid and user.IsWindowVisible(window):
                name = ctypes.create_unicode_buffer(257)
                count = user.GetClassNameW(window, name, len(name))
                if 0 < count < 256 and name.value == self.window_class:
                    matches.append(window)
            return True

        return bool(user.EnumWindows(visit, 0)) and len(matches) == 1

    def close(self):
        for attribute in ('thread', 'process'):
            handle = getattr(self, attribute, None)
            if handle:
                self.api.CloseHandle(handle)
                setattr(self, attribute, None)
