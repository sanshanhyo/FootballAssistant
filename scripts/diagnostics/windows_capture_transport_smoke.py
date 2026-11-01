"""Temporary-file-only smoke for the supplied Windows transport module.
Run: python windows_capture_transport_smoke.py windows_capture_files.py
No FM, subprocesses, networking, user configuration or path/value logging.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.name != 'nt':
        print(json.dumps({'status': 'unsupported_platform'}))
        return 2
    spec = importlib.util.spec_from_file_location('fa_transport_probe', sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    files = module.WindowsCaptureFiles()
    stage = 'start'
    try:
        with tempfile.TemporaryDirectory(prefix='fa-control-smoke-') as temp:
            root = Path(temp) / 'private'
            root.mkdir()
            control = root / 'control'
            control.mkdir()
            stage = 'directory'
            with files.directory(control) as directory:
                def forbidden(*args, **kwargs):
                    raise AssertionError('absolute_child_open')
                original_open = files._open
                files._open = forbidden
                stage = 'lock'
                with files.locked(directory):
                    for sequence in (1, 2):
                        stage = 'write-' + str(sequence)
                        files.write_request(directory, json.dumps({'sequence': sequence}).encode())
                        stage = 'read-' + str(sequence)
                        assert files.read(directory, 'ui-capture.json') == {'sequence': sequence}
                    stage = 'contended-lock'
                    try:
                        with files.locked(directory):
                            raise AssertionError('lock_not_exclusive')
                    except OSError as error:
                        assert error.winerror in (32, 33), 'wrong_lock_failure'
                    stage = 'parent-rename'
                    try:
                        control.rename(root / 'moved')
                    except OSError as error:
                        assert error.winerror in (5, 32), 'wrong_parent_rename_failure'
                    else:
                        raise AssertionError('parent_not_pinned')
                files._open = original_open
            stage = 'hardlink'
            victim = root / 'victim.json'
            victim.write_bytes(b'{"keep":true}')
            (control / 'ui-capture.json').unlink()
            os.link(victim, control / 'ui-capture.json')
            with files.directory(control) as directory:
                try:
                    files.read(directory, 'ui-capture.json')
                except ValueError:
                    pass
                else:
                    raise AssertionError('hardlink_accepted')
            assert victim.read_bytes() == b'{"keep":true}'
            assert not list(control.glob('.ui-capture-*'))
        print(json.dumps({'status': 'passed', 'checks': ['create', 'replace', 'read', 'no-absolute-child-open', 'lock-exclusive', 'parent-pinned', 'hardlink-refused', 'temporary-cleanup']}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'stage': stage, 'type': type(error).__name__, 'winerror': getattr(error, 'winerror', None)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
