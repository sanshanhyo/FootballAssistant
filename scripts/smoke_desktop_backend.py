"""Hermetic frozen-backend health smoke; no model calls or game operations."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

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
                ready = True
                break
            except (OSError, ValueError):
                time.sleep(.1)
        if not ready:
            raise RuntimeError("Frozen backend readiness timed out")
        print(json.dumps({"frozenBackend": "ready", "authenticatedStatus": True, "modelConfigured": False, "modelCalls": 0, "personaCreated": (Path(directory) / "persona.md").is_file()}))
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
