"""Synthetic grammar fixtures; the real pinned snapshot is tested separately locally."""
from datetime import date
import struct

import pytest
from football_assistant_save.summary import UnsupportedSummary, parse_summary31, read_summary_snapshot


def string(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<I",len(data))+data


def summary(*,schema=31,build="27.0.0+2486695",club="合成标签",year=2026,day=194) -> bytes:
    return (b"\x03\x01tad."+struct.pack("<H",schema)+string("synthetic setup")+string(build)+struct.pack("<I",2)+string("d1")+string("d2")+b"\x00"*8+string("private synthetic manager")+string(club)+b"\x00"*4+struct.pack("<HH",day | (13<<9),year)+b"unparsed tail")


def test_structured_walk_handles_variable_utf8_lengths_and_only_two_fields():
    result = parse_summary31(summary(club="任意长度中文原文标签"))
    assert result["club_label"] == "任意长度中文原文标签"
    assert result["game_date"] == "2026-07-13"
    assert "club_id" not in result and "manager" not in result and "players" not in result
    assert result["unparsed_tail_bytes"] == len(b"unparsed tail")


@pytest.mark.parametrize("bad",[
    summary(schema=29),
    summary(build="27.0.1+9999999"),
    summary()[:20],
    b"\x03\x01tad."+struct.pack("<H",31)+struct.pack("<I",2**32-1),
    b"\x03\x01tad."+struct.pack("<H",31)+struct.pack("<I",1)+b"\xff",
    summary(club=""),
    summary(club="bad\nlabel"),
    summary(day=0),
    summary(year=2100,day=366),
])
def test_unknown_malformed_summary_fails_closed(bad):
    with pytest.raises(UnsupportedSummary):
        parse_summary31(bad)


def test_calendar_codec_accepts_leap_day_366():
    assert parse_summary31(summary(year=2024,day=366))["game_date"] == "2024-12-31"


def test_unverified_snapshot_cannot_claim_ui_validation(tmp_path):
    path = tmp_path/"synthetic-copy.fm"
    path.write_bytes(summary())
    result = read_summary_snapshot(path,confirmed_copy=True)
    assert result["status"] in ("unsupported","error")
    assert result["observation"] is None


def test_new_snapshot_keeps_initial_ui_evidence_separate(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    container = pytest.importorskip("fmsave._container")
    path = tmp_path/"synthetic-container-copy.fm"
    path.write_bytes(b"synthetic container test input")
    data = summary(club="新的原文标签")
    entry = SimpleNamespace(extension=".dat",decompressed_size=len(data),compressed_size=len(data))
    monkeypatch.setattr(container,"read_index",lambda path:SimpleNamespace(sections={"save_game_summary":entry}))
    monkeypatch.setattr(container,"read_section",lambda index,name:data)
    result = read_summary_snapshot(path,confirmed_copy=True)
    assert result["status"] == "experimental_partial"
    observation = result["observation"]
    assert len(observation["payload"]["facts"]) == 2
    provenance = observation["payload"]["facts"][0]["provenance"]
    assert provenance["validation_method"] == "format_checked_initial_sample_ui_crosschecked"
    assert provenance["snapshot_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert provenance["ui_evidence_sample_sha256"] != provenance["snapshot_sha256"]


def test_oversize_compressed_summary_is_rejected_before_read(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from football_assistant_save.summary import MAX_SUMMARY_COMPRESSED_BYTES
    container = pytest.importorskip("fmsave._container")
    path = tmp_path/"synthetic-oversize-index-copy.fm"
    path.write_bytes(b"synthetic index test input")
    entry = SimpleNamespace(extension=".dat",decompressed_size=100,compressed_size=MAX_SUMMARY_COMPRESSED_BYTES+1)
    monkeypatch.setattr(container,"read_index",lambda path:SimpleNamespace(sections={"save_game_summary":entry}))
    called = []
    def must_not_read(*args):
        called.append(True)
        raise AssertionError("oversized section must not be read")
    monkeypatch.setattr(container,"read_section",must_not_read)
    result = read_summary_snapshot(path,confirmed_copy=True)
    assert result["status"] == "unsupported"
    assert result["observation"] is None
    assert called == []
