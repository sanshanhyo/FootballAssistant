"""Local writer ownership shared by full backend and standalone reader."""
from __future__ import annotations
import json
import os
from contextlib import contextmanager
from .config import Settings
from .storage import private_directory


@contextmanager
def writer_guard(settings: Settings):
    """Refuse a second reader writer, including launches on a different port."""
    private_directory(settings.data_dir)
    # Also recognizes the pre-reader backend, which does not acquire this lock.
    for runtime_file in {settings.runtime_file,settings.data_dir / "runtime.json"}:
        try:
            pid = json.loads(runtime_file.read_text(encoding="utf-8")).get("pid")
            if isinstance(pid,int) and pid > 0 and pid != os.getpid():
                try:
                    os.kill(pid,0)
                except ProcessLookupError:
                    pass
                else:
                    raise RuntimeError("A service owns this data directory; reuse its runtime file.")
        except (OSError,ValueError,TypeError,AttributeError):
            pass
    with (settings.data_dir / ".reader-writer.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0");stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("A reader already owns this data directory.") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
