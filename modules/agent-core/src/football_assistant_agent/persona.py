"""A single bounded UTF-8 persona file; no includes, directory scans or model access."""
from dataclasses import dataclass
from importlib.resources import files
import os
from pathlib import Path
import stat

MAX_PERSONA_BYTES = 16_384


def default_persona():
    return files('football_assistant_agent').joinpath('resources/persona.md').read_text(encoding='utf-8')


@dataclass(frozen=True)
class Persona:
    text: str
    path: Path | None
    status: str
    reason: str | None = None
    using_default: bool = False
    created: bool = False

    def metadata(self):
        return dict(path=str(self.path) if self.path else None, status=self.status, reason=self.reason,
                    using_default=self.using_default, created=self.created, max_bytes=MAX_PERSONA_BYTES,
                    encoding='UTF-8', reload='next_request')


def _ordinary(info):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _parents_safe(path):
    for parent in path.parents:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_persona_path')


def load_persona(settings):
    default = default_persona()
    data_dir = getattr(settings, 'data_dir', None)
    configured = getattr(settings, 'persona_file', None)
    path = Path(configured).expanduser().absolute() if configured else Path(data_dir).absolute() / 'persona.md' if data_dir else None
    if path is None:
        return Persona(default, None, 'fallback', 'persona_path_not_configured', True)
    created = False
    try:
        if path.suffix.lower() != '.md':
            raise ValueError('persona_extension_must_be_md')
        _parents_safe(path)
        # O_EXCL never replaces a user file, including a broken link. Concurrent
        # first launches may read fallback briefly, but never overwrite edits.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(default.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            created = True
        before = path.lstat()
        if not _ordinary(before):
            raise ValueError('unsafe_persona_file')
        if before.st_size > MAX_PERSONA_BYTES:
            raise ValueError('persona_too_large')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not _ordinary(opened) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('persona_file_changed')
            _parents_safe(path)
            current = path.lstat()
            if not _ordinary(current) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('persona_file_changed')
            payload = stream.read(MAX_PERSONA_BYTES + 1)
        if len(payload) > MAX_PERSONA_BYTES:
            raise ValueError('persona_too_large')
        text = payload.decode('utf-8-sig')  # Windows editors may write a UTF-8 BOM.
        if not text.strip() or '\x00' in text:
            raise ValueError('persona_empty_or_invalid')
        return Persona(text, path, 'ready', using_default=created or text == default, created=created)
    except UnicodeError:
        return Persona(default, path, 'fallback', 'persona_invalid_utf8', True, created)
    except (OSError, ValueError) as error:
        reason = str(error) if isinstance(error, ValueError) else 'persona_file_unavailable'
        return Persona(default, path, 'fallback', reason, True, created)
