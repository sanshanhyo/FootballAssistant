"""Read only an explicitly confirmed stable copy; FM27 remains unsupported."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AdapterProbe:
    status: str
    detected_game: str | None = None
    detected_build: str | None = None
    adapter_version: str = "fmsave-0.7.0"
    sha256: str | None = None
    warnings: list[str] = field(default_factory=list)


def probe(snapshot_path: Path, *, confirmed_copy: bool = False) -> AdapterProbe:
    """Never claim real FM27 support by patching the FM26 version guard."""
    snapshot_path = Path(snapshot_path)
    if not confirmed_copy:
        return AdapterProbe("error",warnings=["Only an explicitly confirmed stable save copy may be probed."])
    if not snapshot_path.is_file():
        return AdapterProbe("missing",warnings=["The specified save copy is not a file."])
    if snapshot_path.is_symlink():
        return AdapterProbe("error",warnings=["Specify a regular copy, not a symbolic link."])
    try:
        before = snapshot_path.stat()
        digest = hashlib.sha256()
        with snapshot_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024*1024),b""):
                digest.update(chunk)
        result = AdapterProbe("unsupported",sha256=digest.hexdigest())
        try:
            import fmsave
        except ImportError:
            result.warnings = ["Optional fmsave dependency missing; run uv sync --extra save. FM27 is not supported by fmsave 0.7.0."]
            return result
        if importlib.metadata.version("fmsave") != "0.7.0":
            result.warnings = ["Only the audited fmsave 0.7.0 may be used; another version needs review."]
            return result
        try:
            with fmsave.open(snapshot_path,strict=True) as save:
                result.detected_game = save.info.game
                result.detected_build = save.info.build
                result.warnings = ["This reader supports FM26. No FM27 fact export is implemented or verified."]
        except fmsave.UnsupportedGameError as error:
            version = re.search(r" is an (FM[0-9]+) save \(([0-9A-Za-z.+_-]{1,80})\)\. fmsave", str(error))
            if version:
                result.detected_game, result.detected_build = version.groups()
            result.warnings = ["fmsave 0.7.0 rejected this game version. FM27 support is not implemented."]
        except Exception:
            result.status = "error"
            result.warnings = ["Save copy could not be parsed or failed strict validation; no facts were imported."]
        after = snapshot_path.stat()
        if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
            return AdapterProbe("error",warnings=["Save copy changed during probing; discard this attempt."])
        return result
    except OSError:
        return AdapterProbe("error",warnings=["Save copy could not be read; no facts were imported."])


def read_snapshot(snapshot_path: Path, *, confirmed_copy: bool = False) -> dict:
    result = probe(snapshot_path,confirmed_copy=confirmed_copy)
    # There is deliberately no FM27 parser or empty-roster fallback.
    return {"probe":asdict(result),"observation":None}


def main():
    parser = argparse.ArgumentParser(description="Read-only probe of an explicitly confirmed save copy (FM27 unsupported)")
    parser.add_argument("snapshot",type=Path)
    parser.add_argument("--confirmed-copy",action="store_true",required=True)
    args = parser.parse_args()
    result = probe(args.snapshot,confirmed_copy=args.confirmed_copy)
    print(json.dumps(asdict(result),ensure_ascii=False,indent=2))
    raise SystemExit(0 if result.status == "available" else 2)
