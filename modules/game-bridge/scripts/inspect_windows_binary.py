#!/usr/bin/env python3
"""Identify explicitly supplied PE32+ AMD64 files without loading or executing them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys

MAX_HEADERS = 65536


class InvalidBinary(ValueError):
    """Unsupported, malformed, or changing input; no trusted identity produced."""


def parse_headers(data: bytes, file_size: int) -> dict:
    def need(ok: bool, reason: str) -> None:
        if not ok:
            raise InvalidBinary(reason)

    def u16(offset: int) -> int:
        return struct.unpack_from("<H", data, offset)[0]

    def u32(offset: int) -> int:
        return struct.unpack_from("<I", data, offset)[0]

    need(len(data) >= 64 and data[:2] == b"MZ", "Missing DOS header")
    pe = u32(60)
    need(64 <= pe <= len(data) - 24, "Invalid PE header offset")
    need(data[pe:pe + 4] == b"PE\0\0", "Missing PE signature")
    need(u16(pe + 4) == 0x8664, "Only AMD64 is supported")
    count, optional_size, optional = u16(pe + 6), u16(pe + 20), pe + 24
    need(1 <= count <= 32, "Section count exceeds supported bounds")
    need(112 <= optional_size <= len(data) - optional, "Invalid optional header size")
    need(u16(optional) == 0x20B, "Only PE32+ is supported")
    need(u32(optional + 108) <= (optional_size - 112) // 8, "Invalid directory count")
    image_size, headers_size = u32(optional + 56), u32(optional + 60)
    table = optional + optional_size
    need(table + count * 40 <= headers_size <= min(len(data), MAX_HEADERS, file_size),
         "Truncated or oversized headers")
    need(headers_size <= image_size, "Invalid image size")
    preferred = struct.unpack_from("<Q", data, optional + 24)[0]
    need(preferred + image_size <= 0xFFFFFFFFFFFFFFFF, "Preferred image address overflow")
    sections, virtual_ranges, raw_ranges = [], [], []
    for index in range(count):
        entry = table + index * 40
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, entry + 8)
        extent = max(virtual_size, raw_size)
        need(rva <= image_size and extent <= image_size - rva, "Section exceeds image")
        need(not extent or rva >= headers_size, "Section overlaps headers")
        need(raw_offset <= file_size and raw_size <= file_size - raw_offset, "Section exceeds file")
        need(not raw_size or raw_offset >= headers_size, "Raw section overlaps headers")
        for start, length, previous in ((rva, extent, virtual_ranges), (raw_offset, raw_size, raw_ranges)):
            need(not length or all(start + length <= a or a + n <= start for a, n in previous),
                 "Overlapping sections")
            if length:
                previous.append((start, length))
        sections.append(dict(name=data[entry:entry + 8].split(b"\0", 1)[0].decode("ascii", "backslashreplace"),
                             rva=rva, virtual_size=virtual_size, raw_size=raw_size, raw_offset=raw_offset,
                             characteristics=u32(entry + 36)))
    return dict(architecture="amd64", format="PE32+", timestamp=u32(pe + 8),
                timestamp_is_build_proof=False, checksum=u32(optional + 64),
                image_size=image_size, headers_size=headers_size, preferred_image_base=preferred, sections=sections)


def inspect(path: Path, reported_game_build: str | None = None) -> dict:
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise InvalidBinary("Input must be a regular file")
        metadata = parse_headers(source.read(MAX_HEADERS), before.st_size)
        source.seek(0)
        digest, remaining = hashlib.sha256(), before.st_size
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise InvalidBinary("File changed during hashing")
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(source.fileno())
        if source.read(1) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise InvalidBinary("File changed during hashing")
    return dict(file_basename=path.name, file_size=before.st_size, sha256=digest.hexdigest(),
                reported_game_build=reported_game_build, reported_game_build_trusted=False,
                supported_game_build_verified=False, **metadata)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--reported-game-build", help="Optional user label; never treated as verified")
    args = parser.parse_args(argv)
    try:
        result = [inspect(path, args.reported_game_build) for path in args.files]
    except InvalidBinary as error:
        print(json.dumps(dict(error="invalid_binary", message=str(error))), file=sys.stderr)
        return 2
    except OSError as error:
        print(json.dumps(dict(error="file_io", message=str(error))), file=sys.stderr)
        return 3
    print(json.dumps(dict(schema_version=1, binaries=result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
