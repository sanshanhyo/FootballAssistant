"""Synthetic protocol fixtures only. Never reads the real game, runtime or model key."""
from contextlib import contextmanager
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

from football_assistant_data.config import ROOT,Settings
from football_assistant_data.reader import create_reader_app,writer_guard
from football_assistant_data.reader_cli import arguments,console,execute,watch
from football_assistant_data.reader_client import ReaderClient,ReaderError,runtime_address

TOKEN = "synthetic-reader-token"
AUTH = {"Authorization":"Bearer "+TOKEN}


def settings(tmp_path):
    return Settings(data_dir=tmp_path,runtime_file=tmp_path/"runtime.json",token=TOKEN)


def fixture():
    now = datetime.now(timezone.utc).isoformat()
    return {"schema_version":"0.2.0","event_id":str(uuid4()),"captured_at":now,"observed_at":now,"synthetic":True,
            "source":{"kind":"runtime","adapter_id":"synthetic-reader","adapter_version":"test","platform":"unknown","freshness":"live"},
            "game":{"product":"FM27","build":"synthetic-build","session_id":"synthetic-session","game_time":None},
            "status":"partial","payload":{"kind":"fact_snapshot","facts":[{"entity_kind":"ui_element","entity_id":"/synthetic/"+str(i),
            "field":"visible_text","value":"Synthetic cached UI "+str(i)} for i in range(3)]}}


def test_reader_app_is_independent_and_truthful_with_snapshot_paging(tmp_path):
    with TestClient(create_reader_app(settings(tmp_path)),base_url="http://127.0.0.1") as client:
        assert not (tmp_path/"companion.sqlite").exists()
        assert client.get("/health").json()["agent_enabled"] is False
        assert client.get("/v1/chat").status_code==404
        assert client.post("/v1/chat",json={"message":"must not dispatch"},headers=AUTH).status_code==404
        assert client.get("/v1/reader/snapshot").status_code==401
        empty = client.get("/v1/reader/snapshot",headers=AUTH).json()
        assert empty["facts"]==[] and empty["partial"] is True and empty["observation"] is None
        body = fixture()
        assert client.post("/v1/observations",json=body,headers=AUTH).status_code==200
        first = client.get("/v1/reader/snapshot?limit=1",headers=AUTH).json()
        assert first["observation"]["synthetic"] is True
        assert first["observation"]["status"]=="partial" and first["partial"] is True
        assert first["facts_total"]==3 and first["next_cursor"]==1 and first["has_more"]
        assert first["native_records"]["payload_decoded"] is False
        assert "cached" in first["limitations"][0]
        second = client.get("/v1/reader/snapshot",params={"after":1,"limit":2,"event_id":body["event_id"]},headers=AUTH).json()
        assert second["next_cursor"]==3 and second["has_more"] is False
        assert client.get("/v1/reader/snapshot?event_id=changed",headers=AUTH).status_code==409
        assert client.get("/v1/reader/status",headers=AUTH).json()["native_records"]["field_values_known"] is False


def test_reader_import_blocks_all_agent_and_provider_imports(tmp_path):
    program = '''
import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('football_assistant_agent','pydantic_ai','openai'):
   raise AssertionError('reader tried an agent/provider import')
sys.meta_path.insert(0,Block())
from pathlib import Path
from football_assistant_data.reader import create_reader_app
from football_assistant_data.config import Settings
from fastapi.testclient import TestClient
folder=Path(sys.argv[1])
with TestClient(create_reader_app(Settings(data_dir=folder,runtime_file=folder/'runtime.json')),base_url='http://127.0.0.1') as client:
 assert client.get('/health').json()['agent_enabled'] is False
assert not (folder/'companion.sqlite').exists()
'''
    result = subprocess.run([sys.executable,"-c",program,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@contextmanager
def server_fixture(tmp_path,handler):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path,self.headers.get("Authorization")))
            code,payload,headers = handler(self.path,self.headers)
            raw = json.dumps(payload).encode()
            self.send_response(code)
            for key,value in headers.items():self.send_header(key,value)
            self.end_headers();self.wfile.write(raw)
        def log_message(self,*args):pass
    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    runtime = tmp_path/"runtime with spaces.json"
    def write(token=TOKEN):
        runtime.write_text(json.dumps({"base_url":f"http://127.0.0.1:{server.server_port}","token":token,"pid":os.getpid(),"started_at":"synthetic"}))
    write()
    try:yield ReaderClient(runtime),seen,write
    finally:server.shutdown();server.server_close();thread.join()


def test_loopback_only_no_redirect_proxy_and_token_rotation(tmp_path,monkeypatch):
    for url in ("https://127.0.0.1:1","http://example.com:1","http://127.0.0.1:1@evil.test:1","http://127.0.0.1:1/prefix","http://localhost:1"):
        with pytest.raises(ReaderError):runtime_address({"base_url":url})
    monkeypatch.setenv("http_proxy","http://127.0.0.1:1")
    token = [TOKEN]
    def handler(path,headers):
        if path=="/health":return 200,{"service":"football-assistant","status":"ok"},{}
        if path=="/v1/events/1":return 302,{}, {"Location":"http://127.0.0.1:1/secret"}
        return (200 if headers.get("Authorization")=="Bearer "+token[0] else 401),{"ok":True},{}
    with server_fixture(tmp_path,handler) as (client,seen,write):
        assert client.get("/v1/status")["ok"]
        token[0]="rotated-synthetic-token";write(token[0])
        assert client.get("/v1/status")["ok"]
        assert seen[-1][1]=="Bearer "+token[0]
        with pytest.raises(ReaderError,match="HTTP 302"):client.get("/v1/events/1")
        with pytest.raises(ReaderError,match="fixed read-only"):client.get("/v1/chat")
    with pytest.raises(ReaderError) as error:client.get("/v1/status")
    assert error.value.code=="disconnected" and TOKEN not in str(error.value)


def test_auth_retry_rereads_runtime_and_legacy_snapshot_is_partial(tmp_path):
    writes = []
    def handler(path,headers):
        if path=="/health":return 200,{"service":"football-assistant","status":"ok"},{}
        if path.startswith("/v1/reader/"):return 404,{},{}
        if path=="/v1/status" and headers.get("Authorization")=="Bearer "+TOKEN:
            writes[0]("rotated");return 401,{},{}
        if path=="/v1/status":return 200,{"source_status":{"event_id":"synthetic-event"}},{}
        if path.startswith("/v1/events?"):return 200,{"latest_cursor":9},{}
        if path=="/v1/monitoring/fields":return 200,{"source_status":{"event_id":"synthetic-event"},"fields":[{"entity_kind":"ui_element","value":"Synthetic"}]},{}
        return 404,{},{}
    with server_fixture(tmp_path,handler) as (client,seen,write):
        writes.append(write)
        assert client.status()["latest_event_cursor"]==9
        page = client.snapshot(limit=1)
        assert page["reader_api"]=="legacy" and page["partial"] is True
        assert page["observation"] is None and page["facts"][0]["value"]=="Synthetic"


def test_watch_advances_bounded_pages_skips_diagnostics_recovers_and_no_spin():
    pages = iter([
        {"events":[{"kind":"native_observer_state_changed","cursor":1}],"next_cursor":1,"has_more":True},
        {"events":[{"kind":"ui_text_changed","cursor":2,"details_truncated":True}],"next_cursor":2,"has_more":False},
        ReaderError("disconnected","Disconnected"),
        {"events":[],"next_cursor":2,"has_more":True},
        {"events":[],"next_cursor":2,"has_more":False},
        {"events":[],"next_cursor":2,"latest_cursor":0,"cursor_reset_required":True},
    ])
    cursors = [];output = [];sleeps = []
    class Client:
        def get(self,path,**query):
            cursors.append(query["after"]);page = next(pages)
            if isinstance(page,Exception):raise page
            return page
    args = SimpleNamespace(after=0,interval=1,polls=6)
    assert watch(Client(),args,output=output.append,sleep=sleeps.append)==0
    assert cursors==[0,1,2,2,2,2] and len(sleeps)==5
    assert [event["kind"] for event in output if event["type"]=="change"]==["ui_text_changed"]
    assert any(event.get("code")=="cursor_stalled" for event in output)
    assert any(event.get("state")=="recovered" for event in output)
    assert output[-1]["type"]=="cursor_reset"


def test_console_has_no_eval_game_writes_or_arbitrary_methods():
    class Client:
        def status(self):return {"source_status":{"synthetic":True}}
        def get(self,*args,**kwargs):raise AssertionError("unexpected API access")
    output = []
    assert console(Client(),stream=io.StringIO("help\neval 1+1\nset player 99\nstatus\nquit\n"),output=output.append)==0
    assert output[0]["read_only"]
    assert output[1]["error"]["code"]==output[2]["error"]["code"]=="unsupported"
    assert output[3]["source_status"]["synthetic"]
    with pytest.raises(ReaderError):arguments("watch",["--interval","0"])


def test_reader_settings_ignore_model_env_and_existing_writer(tmp_path,monkeypatch):
    monkeypatch.setenv("FOOTBALL_ASSISTANT_API_KEY","synthetic-not-a-real-key")
    monkeypatch.setenv("FOOTBALL_ASSISTANT_MODEL_EXTRA_BODY","invalid-json-reader-must-ignore")
    assert Settings.from_env(reader_only=True).api_key==""
    config = settings(tmp_path)
    with writer_guard(config):
        with pytest.raises(RuntimeError,match="already owns"):
            with writer_guard(config):pass


def test_launchers_preserve_space_paths_and_do_not_open_gui(tmp_path):
    spec = importlib.util.spec_from_file_location("launch_reader",ROOT/"scripts/launch_reader.py")
    launcher = importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    assert "${0:A:h:h}" in (ROOT/"scripts/Reader.command").read_text()
    assert 'cd /d "%~dp0.."' in (ROOT/"scripts/Reader.cmd").read_text()
    def handler(path,headers):
        if path=="/health":return 200,{"service":"football-assistant","status":"ok"},{}
        if path=="/v1/reader/status":return 200,{"reader_api":1},{}
        return 200,{"facts":[]},{}
    with server_fixture(tmp_path,handler) as (client,seen,write):
        assert launcher.ensure_service(client.runtime_file,start=False)=={"service":"reused","reader_api":1}


def test_watch_can_start_disconnected_then_recover_without_replaying_history():
    output = [];sleeps = [];calls = []
    class Client:
        attempts = 0
        def status(self):
            self.attempts += 1
            if self.attempts==1:raise ReaderError("disconnected","Disconnected")
            return {"latest_event_cursor":50}
        def get(self,path,**query):
            calls.append(query["after"])
            return {"events":[],"next_cursor":50,"has_more":False}
    assert watch(Client(),SimpleNamespace(after=None,interval=1,polls=3),output=output.append,sleep=sleeps.append)==50
    assert calls==[50,50] and sleeps==[1,1]
    assert [item["state"] for item in output]==["unavailable","recovered"]


def test_launcher_leaves_unrelated_listener_and_live_owner_untouched(tmp_path,monkeypatch):
    spec = importlib.util.spec_from_file_location("launch_reader",ROOT/"scripts/launch_reader.py")
    launcher = importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    data = tmp_path/"separate data"
    monkeypatch.setenv("FOOTBALL_ASSISTANT_DATA_DIR",str(data))
    with server_fixture(tmp_path,lambda path,headers:(200,{"service":"unrelated","status":"ok"},{})) as (client,seen,write):
        monkeypatch.setenv("FOOTBALL_ASSISTANT_PORT",str(urlsplit(json.loads(client.runtime_file.read_text())["base_url"]).port))
        before = client.runtime_file.read_bytes()
        with pytest.raises(ReaderError) as error:launcher.ensure_service(client.runtime_file,start=True)
        assert error.value.code=="incompatible_service"
        assert client.runtime_file.read_bytes()==before and not data.exists()
        with pytest.raises(ReaderError) as error:launcher.ensure_service(data/"missing runtime.json",start=True)
        assert error.value.code=="port_in_use" and not data.exists()
    data.mkdir()
    config = settings(data)
    # This subprocess remains alive while the guard probes its PID. No signal is sent.
    owner = subprocess.Popen([sys.executable,"-c","import sys; sys.stdin.read()"],stdin=subprocess.PIPE)
    try:
        config.runtime_file.write_text(json.dumps({"pid":owner.pid}))
        with pytest.raises(RuntimeError,match="owns this data directory"):
            with writer_guard(config):pass
        assert owner.poll() is None
    finally:
        owner.communicate(timeout=5)


@pytest.mark.skipif(shutil.which("zsh") is None,reason="macOS launcher requires zsh; Windows script is checked separately")
def test_mac_command_uses_quoted_project_path_and_isolated_environment(tmp_path):
    project = tmp_path/"project with spaces"
    scripts = project/"scripts";scripts.mkdir(parents=True)
    launcher = scripts/"Reader.command"
    shutil.copyfile(ROOT/"scripts/Reader.command",launcher)
    tools = tmp_path/"fake tools";tools.mkdir()
    fake_uv = tools/"uv"
    fake_uv.write_text("#!/bin/sh\npwd\nprintf '%s\\n' \"$UV_PROJECT_ENVIRONMENT\" \"$@\"\n")
    fake_uv.chmod(0o700)
    result = subprocess.run([shutil.which("zsh"),str(launcher)],env={**os.environ,"PATH":str(tools)+os.pathsep+os.environ.get("PATH","")},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.splitlines()==[str(project),str(project/".venv-reader"),"run","--frozen","python","scripts/launch_reader.py"]
