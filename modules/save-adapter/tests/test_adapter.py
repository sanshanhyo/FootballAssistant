from football_assistant_save.adapter import probe, read_snapshot


def test_probe_requires_explicit_copy_and_handles_missing(tmp_path):
    assert probe(tmp_path/"missing.fm").status == "error"
    assert probe(tmp_path/"missing.fm",confirmed_copy=True).status == "missing"


def test_invalid_copy_is_not_empty_roster(tmp_path):
    copy = tmp_path/"synthetic-invalid-copy.fm"
    copy.write_bytes(b"not a real football manager save")
    before = copy.read_bytes()
    result = read_snapshot(copy,confirmed_copy=True)
    assert result["probe"]["status"] in ("error","unsupported")
    assert result["observation"] is None
    assert copy.read_bytes() == before


def test_unsupported_version_report_retains_detected_build(tmp_path, monkeypatch):
    import pytest
    fmsave = pytest.importorskip("fmsave")
    copy = tmp_path/"synthetic-unsupported-copy.fm"
    copy.write_bytes(b"synthetic test input")
    def reject(*args, **kwargs):
        raise fmsave.UnsupportedGameError("copy is an FM27 save (27.0.0+2486695). fmsave 0.7.0 reads FM26 saves only")
    monkeypatch.setattr(fmsave,"open",reject)
    result = probe(copy,confirmed_copy=True)
    assert result.status == "unsupported"
    assert result.detected_game == "FM27"
    assert result.detected_build == "27.0.0+2486695"
