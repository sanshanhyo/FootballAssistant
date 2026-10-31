"""Bounded Windows control-file transport; no game access or platform approval.

Local drive paths only. Every parent is opened without following reparse points
and held without delete sharing until the operation finishes. Only the final
parent permits write sharing required by rename. All descendant opens and renames
are NT handle-relative, never paths through that write-shared directory. Reparse
points are not followed. No path-rename or POSIX fallback.
"""
import ctypes
import json
import ntpath
import os
import uuid
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass

DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p
BOOL = ctypes.c_int32


class _FileInfo(ctypes.Structure):
    _fields_ = [('attributes', DWORD), ('times', DWORD * 6), ('volume', DWORD),
                ('size_high', DWORD), ('size_low', DWORD), ('links', DWORD),
                ('index_high', DWORD), ('index_low', DWORD)]


class _Overlapped(ctypes.Structure):
    _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                ('offset', DWORD), ('offset_high', DWORD), ('event', HANDLE)]


class _RenameInfo(ctypes.Structure):
    # Native FileRenameInformation (10); first BOOLEAN/ULONG union is DWORD-sized.
    _fields_ = [('replace', DWORD), ('root', HANDLE), ('length', DWORD),
                ('name', ctypes.c_uint16 * 1)]


class _IoStatusValue(ctypes.Union):
    _fields_ = [('status', ctypes.c_int32), ('pointer', HANDLE)]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [('value', _IoStatusValue), ('information', ctypes.c_size_t)]


def _rename_buffer(directory_handle):
    name = 'ui-capture.json'.encode('utf-16-le')
    # FileName is length-delimited UTF-16, not an added sizeof(struct) tail.
    size = max(ctypes.sizeof(_RenameInfo), _RenameInfo.name.offset + len(name))
    memory = ctypes.create_string_buffer(size)
    info = _RenameInfo.from_buffer(memory)
    info.replace, info.root, info.length = 1, directory_handle, len(name)
    ctypes.memmove(ctypes.addressof(memory) + _RenameInfo.name.offset, name, len(name))
    return memory


class _UnicodeString(ctypes.Structure):
    _fields_ = [('length', ctypes.c_uint16), ('maximum_length', ctypes.c_uint16), ('buffer', HANDLE)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [('length', DWORD), ('root', HANDLE), ('name', ctypes.POINTER(_UnicodeString)),
                ('attributes', DWORD), ('security_descriptor', HANDLE), ('security_qos', HANDLE)]


@dataclass(frozen=True)
class _Directory:
    handle: int


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_field')
        value[key] = item
    return value


def _components(path):
    raw = os.fspath(path)
    drive, tail = ntpath.splitdrive(raw)
    # Reject UNC, device namespaces, drive-relative paths, ADS and ambiguous names.
    if len(drive) != 2 or drive[1] != ':' or not drive[0].isascii() or not drive[0].isalpha() or not tail.startswith(('\\', '/')):
        raise ValueError('local_absolute_control_path_required')
    parts = tail.replace('/', '\\').split('\\')[1:]
    if any(not item or item in ('.', '..') or item[-1:] in (' ', '.') or any(c in item for c in ':\x00<>"|?*') for item in parts):
        raise ValueError('unsafe_control_path')
    return drive + '\\', parts


class WindowsCaptureFiles:
    supported = os.name == 'nt'
    _names = frozenset(('host-session.json', 'ui-capture-status.json', 'ui-capture.json'))

    def __init__(self):
        self.api = None
        if not self.supported:
            return
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.nt = ctypes.WinDLL('ntdll')
        self.nt.NtSetInformationFile.restype = ctypes.c_int32
        self.nt.NtSetInformationFile.argtypes = [HANDLE, ctypes.POINTER(_IoStatusBlock), HANDLE, DWORD, ctypes.c_int]
        self.nt.NtCreateFile.restype = ctypes.c_int32
        self.nt.NtCreateFile.argtypes = [ctypes.POINTER(HANDLE), DWORD, ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock), HANDLE, DWORD, DWORD, DWORD, DWORD, HANDLE, DWORD]
        self.nt.RtlNtStatusToDosError.restype = DWORD
        self.nt.RtlNtStatusToDosError.argtypes = [ctypes.c_int32]
        signatures = {
            'CreateFileW': (HANDLE, [ctypes.c_wchar_p, DWORD, DWORD, HANDLE, DWORD, DWORD, HANDLE]),
            'CloseHandle': (BOOL, [HANDLE]),
            'GetFinalPathNameByHandleW': (DWORD, [HANDLE, ctypes.c_wchar_p, DWORD, DWORD]),
            'GetDriveTypeW': (DWORD, [ctypes.c_wchar_p]),
            'GetFileType': (DWORD, [HANDLE]),
            'GetFileInformationByHandle': (BOOL, [HANDLE, ctypes.POINTER(_FileInfo)]),
            'ReadFile': (BOOL, [HANDLE, HANDLE, DWORD, ctypes.POINTER(DWORD), HANDLE]),
            'WriteFile': (BOOL, [HANDLE, HANDLE, DWORD, ctypes.POINTER(DWORD), HANDLE]),
            'FlushFileBuffers': (BOOL, [HANDLE]),
            'LockFileEx': (BOOL, [HANDLE, DWORD, DWORD, DWORD, DWORD, ctypes.POINTER(_Overlapped)]),
            'UnlockFileEx': (BOOL, [HANDLE, DWORD, DWORD, DWORD, ctypes.POINTER(_Overlapped)]),
            'SetFileInformationByHandle': (BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.api, name)
            function.restype, function.argtypes = result, arguments

    def _require(self):
        if self.api is None:
            raise OSError('unsupported_platform')

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    @contextmanager
    def _open(self, path, access, sharing, disposition=3, directory=False):
        self._require()
        flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT / BACKUP_SEMANTICS
        handle = self.api.CreateFileW(path, access, sharing, None, disposition, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._info(handle, directory=directory)
            yield handle
        finally:
            self.api.CloseHandle(handle)

    def _check_nt(self, status):
        if status != 0:
            raise ctypes.WinError(self.nt.RtlNtStatusToDosError(status))

    @contextmanager
    def _open_relative(self, parent, name, access, sharing, disposition=3, directory=False):
        self._require()
        if not name or name in ('.', '..') or any(c in name for c in '/\\:\x00'):
            raise ValueError('single_control_component_required')
        self._info(parent, directory=True)
        encoded = name.encode('utf-16-le')
        if len(encoded) > 65532:
            raise ValueError('control_component_too_long')
        name_buffer = ctypes.create_string_buffer(encoded)
        unicode = _UnicodeString(len(encoded), len(encoded), ctypes.addressof(name_buffer))
        attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(unicode),
                                       0x1040, None, None)  # OBJ_DONT_REPARSE | OBJ_CASE_INSENSITIVE
        handle, io = HANDLE(), _IoStatusBlock()
        options = 0x00200000 | 0x20 | (1 if directory else 0x40)
        # FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT |
        # FILE_DIRECTORY_FILE / FILE_NON_DIRECTORY_FILE. No unbounded path lookup.
        status = self.nt.NtCreateFile(ctypes.byref(handle), access | 0x100000, ctypes.byref(attributes),
            ctypes.byref(io), None, 0x80, sharing, {3: 1, 1: 2, 4: 3}[disposition], options, None, 0)
        self._check_nt(status)
        try:
            self._check_nt(io.value.status)
            self._info(handle, directory=directory)
            yield handle.value
        finally:
            self.api.CloseHandle(handle)

    def _info(self, handle, *, directory=False, bounded=True):
        if self.api.GetFileType(handle) != 1:  # FILE_TYPE_DISK only
            raise ValueError('unsafe_control_file')
        info = _FileInfo()
        self._check(self.api.GetFileInformationByHandle(handle, ctypes.byref(info)))
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise ValueError('reparse_or_wrong_file_type')
        if not directory and (info.links != 1 or (bounded and (info.size_high or info.size_low > 2048))):
            raise ValueError('unsafe_control_file')
        return info

    def _final_path(self, handle):
        # Resolve the held drive root to its volume GUID, so remapping a DOS drive
        # letter cannot redirect subsequent child opens while handles are held.
        buffer = ctypes.create_unicode_buffer(32768)
        length = self.api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 1)
        self._check(length)
        if length >= len(buffer) or not buffer.value.startswith('\\\\?\\Volume{'):
            raise ValueError('local_volume_path_required')
        return buffer.value

    @contextmanager
    def directory(self, path):
        self._require()
        current, parts = _components(path)
        if self.api.GetDriveTypeW(current) != 3:  # fixed local volume, never mapped network shares
            raise ValueError('local_fixed_volume_required')
        with ExitStack() as stack:
            # FILE_LIST_DIRECTORY participates in sharing checks. Ancestors keep
            # share READ only. The final parent needs SHARE_WRITE for rename, but
            # no subsequent child operation resolves its absolute pathname.
            handle = stack.enter_context(self._open(current, 0x81, 1, directory=True))
            self._final_path(handle)  # reject a remote/device root; do not reopen this path
            for index, component in enumerate(parts):
                sharing = 3 if index == len(parts) - 1 else 1
                handle = stack.enter_context(self._open_relative(handle, component, 0xA1, sharing, directory=True))
            yield _Directory(handle)

    def read(self, directory, name, *, optional=False):
        if name not in self._names:
            raise ValueError('invalid_control_filename')
        try:
            with self._open_relative(directory.handle, name, 0x80000000, 1) as handle:
                buffer, count = ctypes.create_string_buffer(2049), DWORD()
                self._check(self.api.ReadFile(handle, buffer, 2049, ctypes.byref(count), None))
                self._info(handle)
                if count.value > 2048:
                    raise ValueError('oversize_control_file')
                value = json.loads(buffer.raw[:count.value], object_pairs_hook=_unique)
                if not isinstance(value, dict):
                    raise ValueError('invalid_control_file')
                return value
        except FileNotFoundError:
            if optional:
                return None
            raise

    @contextmanager
    def locked(self, directory):
        # OPEN_ALWAYS, never truncate. No delete sharing pins this lock's identity.
        with self._open_relative(directory.handle, '.ui-capture.lock', 0xC0000000, 3, disposition=4) as handle:
            overlapped = _Overlapped()
            # Exclusive, fail immediately: a competing controller is unavailable,
            # not an unbounded HTTP request waiting on a potentially hostile lock.
            self._check(self.api.LockFileEx(handle, 3, 0, 1, 0, ctypes.byref(overlapped)))
            try:
                yield
            finally:
                self._check(self.api.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)))

    def write_request(self, directory, payload):
        if not isinstance(payload, bytes) or len(payload) > 2048:
            raise ValueError('request_too_large')
        # Validate an existing destination, but never write through it. A later
        # replacement of that name is also replaced, not followed or truncated.
        self.read(directory, 'ui-capture.json', optional=True)
        temporary = '.ui-capture-' + uuid.uuid4().hex
        with self._open_relative(directory.handle, temporary, 0x40000000 | 0x10000, 0, disposition=1) as handle:
            renamed = False
            try:
                count = DWORD()
                buffer = ctypes.create_string_buffer(payload)
                self._check(self.api.WriteFile(handle, buffer, len(payload), ctypes.byref(count), None))
                if count.value != len(payload):
                    raise OSError('short_control_write')
                self._check(self.api.FlushFileBuffers(handle))
                self._info(handle)
                memory = _rename_buffer(directory.handle)
                io = _IoStatusBlock()
                # The Win32 FileRenameInfo wrapper rejects the non-NULL root on
                # real Windows (87). Native class 10 supports RootDirectory;
                # keep both source and destination handle-bound, no path fallback.
                # NtCreateFile above requests synchronous non-alertable I/O.
                status = self.nt.NtSetInformationFile(handle, ctypes.byref(io), memory, len(memory), 10)
                if status != 0:
                    raise ctypes.WinError(self.nt.RtlNtStatusToDosError(status))
                if io.value.status < 0:
                    raise ctypes.WinError(self.nt.RtlNtStatusToDosError(io.value.status))
                renamed = True
            finally:
                if not renamed:
                    # Delete the owned file by handle, never unlink a raced name.
                    delete = ctypes.c_ubyte(1)
                    self._check(self.api.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), 1))
