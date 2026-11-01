import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[3]/'scripts'/'fm_metadata_probe.py'
s=importlib.util.spec_from_file_location('fm_metadata_probe',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def test_only_exact_image_and_plugin_are_selected():
    processes=[{'pid':1,'image':'C:/game/fm.exe'},{'pid':2,'image':'C:/game/notfm.exe'}]
    called=[]
    def modules(pid):
        called.append(pid); return [{'name':'GAME_PLUGIN.DLL'},{'name':'other.dll'}]
    result=m.select_records(processes,modules)
    assert called == [1]
    assert result[0]['modules'] == [{'name':'GAME_PLUGIN.DLL'}]


def test_empty_and_multiple_processes():
    assert m.report(lambda: []) == {"status": "not_running", "processes": []}
    rows=[{"pid": 1, "image": "C:/fm.exe"}, {"pid": 2, "image": "D:/fm.exe"}]
    result=m.select_records(rows, lambda pid: [{"name": "other.dll"}])
    assert [x["pid"] for x in result] == [1, 2]
    assert all(x["modules"] == [] for x in result)

def test_access_denied_is_unavailable():
    def denied(): raise PermissionError(5, "Access denied")
    result=m.report(denied)
    assert result["status"] == "unavailable" and "denied" in result["error"]

def test_handle_closed_on_exception():
    closed=[]
    try:
        with m.managed_handle(42, closed.append): raise RuntimeError("failure")
    except RuntimeError: pass
    assert closed == [42]


def test_alpha_tts_controls_are_absent_from_six_page_settings():
    root=Path(__file__).resolve().parents[3]/"apps"/"companion"/"src"
    html=(root/"settings.html").read_text(encoding="utf-8")
    assert 'id="tts-provider"' not in html
    assert 'id="tts-enabled"' not in html
    assert 'id="stt-provider"' in html
    assert html.count('class="settings-page"') == 6


def test_toolhelp_end_does_not_mask_other_errors():
    import pytest
    m.check_enumeration_end(18)
    with pytest.raises(OSError, match="Windows error 5"):
        m.check_enumeration_end(5)
