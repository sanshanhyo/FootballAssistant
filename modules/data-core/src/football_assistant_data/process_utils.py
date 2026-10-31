"""Conservative, non-destructive process liveness checks for reader ownership."""
from __future__ import annotations

import os

_IS_WINDOWS = os.name == "nt"


def _windows_process_is_alive(pid: int) -> bool:
    # os.kill(pid, 0) is CTRL_C_EVENT on Windows, not a harmless POSIX probe.
    # Query only synchronization state; never request termination permissions.
    import ctypes
    from ctypes import wintypes

    if pid > 0xFFFFFFFF:
        return True  # Do not truncate an untrusted PID into another process ID.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        # Only a nonexistent PID is safe to treat as stale. Access denied and
        # other unknown failures must not authorize a second writer.
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER
    try:
        return kernel32.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def process_is_alive(pid: int) -> bool:
    """Return False only for a known-dead process; PID reuse remains possible."""
    if _IS_WINDOWS:
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # Permission denied/unknown is not evidence of death.
    return True
