import hashlib

import pytest
from football_assistant_save import import_cli


def test_stable_copy_handles_spaces_and_preserves_original(tmp_path):
    source = tmp_path/"source directory with spaces"/"中文 save.fm"
    source.parent.mkdir()
    source.write_bytes(b"synthetic copy test")
    before = source.stat()
    destination,digest = import_cli.copy_stable_save(source,tmp_path/"private copies",settle_seconds=0)
    assert destination.read_bytes() == source.read_bytes()
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.stat().st_mtime_ns == before.st_mtime_ns


def test_changing_source_is_not_copied(tmp_path,monkeypatch):
    source=tmp_path/"changing.fm"
    source.write_bytes(b"before")
    monkeypatch.setattr(import_cli.time,"sleep",lambda _:source.write_bytes(b"changed"))
    with pytest.raises(import_cli.ImportSaveError):
        import_cli.copy_stable_save(source,tmp_path/"copies")
    assert not (tmp_path/"copies").exists()


def test_unsupported_format_never_posts(tmp_path,monkeypatch):
    source=tmp_path/"synthetic.fm"
    source.write_bytes(b"synthetic unsupported format")
    monkeypatch.setattr(import_cli,"read_summary_snapshot",lambda *args,**kwargs:{"status":"unsupported","observation":None,"warning":"unsupported test format"})
    def never_post(*args):
        raise AssertionError("unsupported format must not be published")
    monkeypatch.setattr(import_cli,"publish_observation",never_post)
    result=import_cli.import_save(source,tmp_path/"data",tmp_path/"runtime.json",17827,settle_seconds=0)
    assert result["imported"] is False
    assert result["status"] == "unsupported"
