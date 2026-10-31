"""Ownership probes must never signal a Windows console or kill its owner."""
import ctypes
from types import SimpleNamespace

import pytest

from football_assistant_data import process_utils


@pytest.mark.parametrize("wait_result,expected", [(258, True), (0, False), (0xFFFFFFFF, True)])
def test_windows_probe_only_waits_and_closes_handle(monkeypatch, wait_result, expected):
    calls = []
    def open_process(*args):
        calls.append(("open", args))
        return 0x123456789  # A 64-bit HANDLE must not be narrowed to an int.
    def wait(*args):
        calls.append(("wait", args))
        return wait_result
    def close(*args):
        calls.append(("close", args))
        return True
    kernel = SimpleNamespace(OpenProcess=open_process, WaitForSingleObject=wait, CloseHandle=close)
    def load(name, **kwargs):
        assert name == "kernel32" and kwargs == {"use_last_error": True}
        return kernel
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setattr(process_utils, "_IS_WINDOWS", True)
    monkeypatch.setattr(process_utils.os, "kill", lambda *args: pytest.fail("Windows probe sent a signal"))
    assert process_utils.process_is_alive(1234) is expected
    assert calls == [("open", (0x00100000, False, 1234)), ("wait", (0x123456789, 0)), ("close", (0x123456789,))]
    assert kernel.OpenProcess.restype is ctypes.wintypes.HANDLE
    assert kernel.WaitForSingleObject.argtypes == [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    assert kernel.CloseHandle.argtypes == [ctypes.wintypes.HANDLE]


@pytest.mark.parametrize("error,expected", [(87, False), (5, True), (6, True)])
def test_windows_probe_unknown_and_denied_fail_closed(monkeypatch, error, expected):
    def open_process(*args):
        return None
    kernel = SimpleNamespace(OpenProcess=open_process, WaitForSingleObject=lambda *args: pytest.fail("invalid handle waited"), CloseHandle=lambda *args: pytest.fail("invalid handle closed"))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    monkeypatch.setattr(process_utils, "_IS_WINDOWS", True)
    monkeypatch.setattr(process_utils.os, "kill", lambda *args: pytest.fail("Windows probe sent a signal"))
    assert process_utils.process_is_alive(1234) is expected


def test_windows_probe_does_not_truncate_pid(monkeypatch):
    monkeypatch.setattr(process_utils, "_IS_WINDOWS", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: pytest.fail("oversized PID passed to Windows"), raising=False)
    assert process_utils.process_is_alive(0x100000001)


@pytest.mark.parametrize("error,expected", [(None, True), (ProcessLookupError(), False), (PermissionError(), True), (OSError(), True)])
def test_posix_probe_is_non_signaling_and_conservative(monkeypatch, error, expected):
    def kill(pid, sig):
        assert (pid, sig) == (1234, 0)
        if error is not None:
            raise error
    monkeypatch.setattr(process_utils, "_IS_WINDOWS", False)
    monkeypatch.setattr(process_utils.os, "kill", kill)
    assert process_utils.process_is_alive(1234) is expected
