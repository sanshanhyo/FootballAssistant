"""Thread-safe in-memory capture-file contract, not a production filesystem adapter.

Runs request/session/sequence state-machine tests on every OS without pretending
that the Mac bridge or POSIX no-follow filesystem APIs are supported on Windows.
"""
from contextlib import contextmanager
import json
from threading import RLock
from football_assistant_data.ui_capture_control import UiCaptureController, _unique


class MemoryPath:
    def __init__(self, files, name=''):
        self.files, self.name = files, name

    def __truediv__(self, name):
        return MemoryPath(self.files, self.name + '/' + name)

    def write_text(self, text):
        self.files.contents[self.name] = text

    def read_text(self):
        try:
            return self.files.contents[self.name]
        except KeyError:
            raise FileNotFoundError(self.name) from None

    def exists(self):
        return self.name in self.files.contents


class MemoryCaptureFiles:
    supported = True

    def __init__(self):
        self.contents = {}
        self.gate = RLock()

    @contextmanager
    def directory(self, path):
        yield path

    @contextmanager
    def locked(self, control):
        with self.gate:
            yield

    def read(self, directory, name, *, optional=False):
        try:
            content = (directory / name).read_text()
        except FileNotFoundError:
            if optional:
                return None
            raise
        if len(content.encode()) > 2048:
            raise ValueError('oversize_control_file')
        result = json.loads(content, object_pairs_hook=_unique)
        if not isinstance(result, dict):
            raise ValueError('invalid_control_file')
        return result

    def write_request(self, control, payload):
        (control / 'ui-capture.json').write_text(payload.decode())


def memory_control():
    files = MemoryCaptureFiles()
    root = MemoryPath(files)
    host = dict(pid=123, session_id='TEST-session', managed_build_sha256='a' * 64)
    (root / 'diagnostics/host-session.json').write_text(json.dumps(host))
    return UiCaptureController(root, files=files), host
