import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "modules/game-bridge/scripts/inspect_windows_binary.py"
spec = importlib.util.spec_from_file_location("windows_binary_identity", SCRIPT)
assert spec and spec.loader
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def fixture() -> bytearray:
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<HHI", data, 68, 0x8664, 1, 123)
    struct.pack_into("<H", data, 84, 112)
    struct.pack_into("<H", data, 88, 0x20B)
    struct.pack_into("<Q", data, 112, 0x140000000)
    struct.pack_into("<II", data, 144, 8192, 512)
    data[200:205] = b".text"
    struct.pack_into("<IIII", data, 208, 100, 4096, 512, 512)
    return data


def test_file_identity_and_cli(tmp_path, capsys):
    path = tmp_path / "a spaced file.dll"
    data = fixture()
    path.write_bytes(data)
    result = identity.inspect(path, "FM27-unverified")
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["file_basename"] == path.name
    assert result["architecture"] == "amd64"
    assert result["sections"][0]["raw_offset"] == 512
    assert not result["reported_game_build_trusted"]
    assert not result["timestamp_is_build_proof"]
    assert not result["supported_game_build_verified"]
    assert identity.main([str(path), str(path), "--reported-game-build", "FM27"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output["binaries"]) == 2
    assert output["binaries"][0]["reported_game_build"] == "FM27"


@pytest.mark.parametrize("offset,format,value", [
    (60, "I", 0xFFFFFFFF), (68, "H", 0x14C), (70, "H", 33),
    (84, "H", 111), (88, "H", 0x10B), (144, "I", 100),
    (148, "I", 65537), (196, "I", 1000), (212, "I", 0xFFFFFFFF),
    (216, "I", 0xFFFFFFFF), (220, "I", 1024), (220, "I", 100),
    (112, "Q", 0xFFFFFFFFFFFFFFFE),
])
def test_malformed_headers(offset, format, value):
    data = fixture()
    struct.pack_into("<" + format, data, offset, value)
    with pytest.raises(identity.InvalidBinary):
        identity.parse_headers(data, len(data))


def test_truncated_header_and_distinct_errors(tmp_path, capsys):
    data = fixture()
    for length in (0, 63, 80, 199, 239, 511):
        with pytest.raises(identity.InvalidBinary):
            identity.parse_headers(data[:length], 1024)
    bad = tmp_path / "not-a-dll.dll"
    bad.write_bytes(b"not executable")
    assert identity.main([str(bad)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_binary"
    assert identity.main([str(tmp_path / "missing.dll")]) == 3
    assert json.loads(capsys.readouterr().err)["error"] == "file_io"


def test_overlapping_sections():
    data = fixture()
    struct.pack_into("<H", data, 70, 2)
    data[240:280] = data[200:240]
    with pytest.raises(identity.InvalidBinary, match="Overlapping"):
        identity.parse_headers(data, len(data))


def test_streaming_hash_and_change_detection(tmp_path, monkeypatch):
    path = tmp_path / "large.dll"
    data = fixture() + b"overlay" * 200_000
    path.write_bytes(data)
    assert identity.inspect(path)["sha256"] == hashlib.sha256(data).hexdigest()
    real_fstat = identity.os.fstat
    calls = 0

    def changed_fstat(fd):
        nonlocal calls
        calls += 1
        value = real_fstat(fd)
        if calls == 1:
            return value
        from types import SimpleNamespace
        return SimpleNamespace(st_size=value.st_size, st_mtime_ns=value.st_mtime_ns + 1,
                               st_ctime_ns=value.st_ctime_ns)

    monkeypatch.setattr(identity.os, "fstat", changed_fstat)
    with pytest.raises(identity.InvalidBinary, match="changed during hashing"):
        identity.inspect(path)
