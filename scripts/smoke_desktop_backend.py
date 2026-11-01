"""Hermetic frozen-backend health smoke; no model calls or game operations."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
binary = ROOT / "build/desktop-backend/football-assistant-backend" / ("football-assistant-backend.exe" if os.name == "nt" else "football-assistant-backend")
with tempfile.TemporaryDirectory(prefix="fa-frozen-smoke-") as directory:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    ordinary = {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "SystemRoot", "SYSTEMROOT", "WINDIR", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "LANG"}
    env = {key: value for key, value in os.environ.items() if key in ordinary}
    env.update(FOOTBALL_ASSISTANT_DATA_DIR=directory, FOOTBALL_ASSISTANT_PORT=str(port), FOOTBALL_ASSISTANT_DESKTOP="1")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    child = subprocess.Popen([str(binary)], cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(300):
            if child.poll() is not None:
                raise RuntimeError(f"Frozen backend exited before readiness ({child.returncode})")
            try:
                health = json.load(opener.open(f"http://127.0.0.1:{port}/health", timeout=1))
                runtime = json.loads((Path(directory) / "runtime.json").read_text())
                request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/status", headers={"Authorization": "Bearer " + runtime["token"]})
                status = json.load(opener.open(request, timeout=1))
                assert health["service"] == "football-assistant" and status["modelConfigured"] is False
                persona_request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/agent/persona", headers={"Authorization": "Bearer " + runtime["token"]})
                persona = json.load(opener.open(persona_request, timeout=1))
                assert persona["status"] == "ready" and Path(persona["path"]).resolve() == (Path(directory) / "persona.md").resolve()
                # Exercise the frozen format checkers, not just import/readiness.
                for field, bad in (("event_id", "not-a-uuid"),
                                   ("captured_at", "2026-02-30T00:00:00Z"),
                                   ("observed_at", "not-a-date")):
                    body = json.loads((ROOT / "contracts/examples/runtime-observation.json").read_text(encoding="utf-8"))
                    body[field] = bad
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/observations",
                        data=json.dumps(body).encode(),
                        headers={"Authorization": "Bearer " + runtime["token"], "Content-Type": "application/json"})
                    try:
                        opener.open(request, timeout=2).close()
                    except HTTPError as error:
                        assert error.code == 422
                    else:
                        raise AssertionError(f"Frozen backend accepted invalid {field}")
                ready = True
                break
            except (OSError, ValueError):
                time.sleep(.1)
        if not ready:
            raise RuntimeError("Frozen backend readiness timed out")
        print(json.dumps({"frozenBackend": "ready", "authenticatedStatus": True, "modelConfigured": False, "modelCalls": 0, "invalidFormatsRejected": 3, "personaCreated": (Path(directory) / "persona.md").is_file()}))
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
