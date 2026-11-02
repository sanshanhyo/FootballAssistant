"""Reassemble the approved upstream archive locally; never fetch from the network."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

CHUNK_SIZE = 1048572
APPROVED_ARCHIVE_SIZE = 34335572


def _ordinary(path: Path, expected_size: int):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != expected_size:
        raise ValueError(f"Not an ordinary correctly sized archive component: {path.name}")
    return info


def reassemble(manifest_path: Path, output: Path, expected_sha256: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('A fixed upstream SHA-256 is required')
    if manifest_path.name != 'manifest.json':
        raise ValueError('Expected the fixed split-archive manifest filename')
    info = manifest_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128 * 1024:
        raise ValueError('Invalid split-archive manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1
            or manifest.get('sha256') != expected_sha256
            or type(manifest.get('size')) is not int
            or manifest['size'] != APPROVED_ARCHIVE_SIZE
            or not isinstance(manifest.get('parts'), list)
            or len(manifest['parts']) != math.ceil(manifest['size'] / CHUNK_SIZE)):
        raise ValueError('Split archive does not match the approved upstream identity')
    root = manifest_path.resolve(strict=True).parent
    chunks = manifest['parts']
    for index, chunk in enumerate(chunks):
        size = min(CHUNK_SIZE, manifest['size'] - index * CHUNK_SIZE)
        if (not isinstance(chunk, dict) or chunk.get('path') != f'part-{index:03d}.bin'
                or type(chunk.get('size')) is not int or chunk['size'] != size
                or not isinstance(chunk.get('sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', chunk['sha256'])):
            raise ValueError('Invalid chunk order, size, path or hash')
        _ordinary(root / chunk['path'], size)
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise ValueError('Invalid archive output path')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f'.{output.name}.{uuid.uuid4().hex}.tmp')
    overall = hashlib.sha256()
    total = 0
    try:
        with temporary.open('xb') as destination:
            for chunk in chunks:
                source = root / chunk['path']
                before = _ordinary(source, chunk['size'])
                digest = hashlib.sha256()
                count = 0
                flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
                with os.fdopen(os.open(source, flags), 'rb') as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) != (before.st_dev, before.st_ino, before.st_size, 1):
                        raise ValueError('Archive chunk changed before reading')
                    while data := stream.read(65536):
                        count += len(data)
                        if count > chunk['size']:
                            raise ValueError('Archive chunk expanded during read')
                        digest.update(data)
                        overall.update(data)
                        destination.write(data)
                after = _ordinary(source, chunk['size'])
                if ((after.st_dev, after.st_ino, after.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_mtime_ns)
                        or count != chunk['size'] or digest.hexdigest() != chunk['sha256']):
                    raise ValueError('Archive chunk integrity check failed')
                total += count
            if total != manifest['size'] or overall.hexdigest() != expected_sha256:
                raise ValueError('Reassembled archive differs from the approved original ZIP')
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    output = reassemble(args.manifest, args.output, args.expected_sha256)
    print(json.dumps({'archiveSize': output.stat().st_size, 'archiveSha256': args.expected_sha256, 'networkUsed': False}))


if __name__ == '__main__':
    main()
