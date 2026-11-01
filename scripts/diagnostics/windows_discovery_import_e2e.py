"""Executable local HTTP→controlled Node client→pet reply proof, SYNTHETIC ONLY.

Starts a temporary reader-only FastAPI server. No game, Electron, model provider,
private evidence, arbitrary input path or credentials from another app are used.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules/data-core/src"))
# Source checkout support; installed distributions already map this package.
if importlib.util.find_spec("football_assistant_contracts") is None:
    spec = importlib.util.spec_from_file_location("football_assistant_contracts", ROOT / "contracts/__init__.py",
                                                submodule_search_locations=[str(ROOT / "contracts")])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

import uvicorn
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings

NODE_PROOF = r"""
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const {request} = require(path.join(input.root, 'apps/companion/src/backend.cjs'));
const {RealReaderClient} = require(path.join(input.root, 'apps/companion/src/reader-clients.cjs'));
const calls = [];
const controlled = (endpoint, body, options) => { calls.push(endpoint); return request(input.runtime, endpoint, body, options); };
(async () => {
  const before = await controlled('/v1/reader/business/status');
  assert.equal(before.production_ready, false);
  const imported = await controlled('/v1/reader/windows-discovery/import', input.bundle);
  assert.equal(imported.status, 'manual_import_snapshot');
  assert.equal(imported.projection.fields.displayed_position, 'TEST-POSITION');
  assert.equal(imported.projection.source_freshness, 'unknown');
  assert.equal(imported.projection.business_identity_known, false);
  const reader = new RealReaderClient({request: controlled});
  const reply = await reader.reply({message:'查看导入诊断', conversationId:null});
  assert.match(reply.text, /TEST-POSITION/);
  assert.equal(reply.metadata.freshness, 'unknown');
  assert.equal(reply.metadata.sampledAt, null);
  assert.equal(reply.metadata.readiness?.production_ready === true, false);
  const serialized = JSON.stringify(reply);
  assert.ok(serialized.includes(input.labelPath) && serialized.includes(input.valuePath));
  // Exercise the settings raw-text path: duplicate keys reach backend unchanged.
  const raw = JSON.stringify(input.bundle);
  const duplicate = raw.replace('"pid":123', '"pid":123,"pid":123');
  assert.notEqual(duplicate, raw);
  await assert.rejects(reader.importWindowsDiscoveryText(duplicate));
  assert.equal((await reader.windowsDiscovery()).status, 'unavailable');
  const afterFailure = await reader.reply({message:'查看导入诊断', conversationId:null});
  assert.ok(!afterFailure.text.includes('TEST-POSITION'));
  const restored = await reader.importWindowsDiscoveryText(raw);
  assert.equal(restored.projection.fields.displayed_position, 'TEST-POSITION');
  const after = await controlled('/v1/reader/business/status');
  assert.equal(after.production_ready, false);
  assert.ok(!calls.some(p => p.startsWith('/v1/agent/') || p === '/v1/chat' || p.includes('capture-profile')));
  const row = await reader.importWindowsDiscoveryText(JSON.stringify(input.rowBundle));
  assert.equal(row.projection.projection_mode, 'goalkeeper_row0');
  assert.equal(row.projection.fields.displayed_attribute.value, 17);
  const rowReply = await reader.reply({message:'查看导入诊断', conversationId:null});
  assert.match(rowReply.text, /出击\(倾向\)/);
  assert.match(rowReply.text, /17/);
  assert.equal(rowReply.metadata.freshness, 'unknown');
  assert.equal(rowReply.metadata.synthetic, null);
  assert.equal(rowReply.metadata.sampledAt, null);
  for (const ref of input.rowPaths) assert.ok(JSON.stringify(rowReply).includes(ref));
  assert.ok(!calls.some(p => p.startsWith('/v1/agent/') || p === '/v1/chat' || p.includes('capture-profile')));
  const badRow = structuredClone(input.rowBundle);
  badRow.capture.result.Observations[2].Text = '21';
  await assert.rejects(reader.importWindowsDiscoveryText(JSON.stringify(badRow)));
  assert.equal((await reader.windowsDiscovery()).status, 'unavailable');
  await reader.importWindowsDiscoveryText(JSON.stringify(input.rowBundle));
  await controlled('/v1/reader/windows-discovery', undefined, {method:'DELETE'});
  const cleared = await controlled('/v1/reader/windows-discovery');
  assert.equal(cleared.status, 'unavailable');
  const empty = await reader.reply({message:'查看导入诊断', conversationId:null});
  assert.ok(!empty.text.includes('TEST-POSITION'));
  console.log('PASS synthetic position + targeted row HTTP import → pet diagnostic reply → invalid-clear; no model/game calls or player identity.');
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
"""


def bundle():
    # Invented TEST observation, not a real player's data or a runtime success claim.
    container = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0"
    source = dict(pid=123, entry_tid=456, session_id="11111111-1111-4111-8111-111111111111",
                  bridge_sha256="a" * 64,
                  game_sha256="820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a")
    nonce = "22222222-2222-4222-8222-222222222222"
    capture = dict(source, phase="single_shot_raw_discovery_result", callback_tid=456, nonce=nonce,
                   page_identity_verified=False, business_facts=False, terminal=True,
                   result=dict(Status="raw_diagnostics", Reason="bounded_raw_diagnostics", PageIdentityVerified=False,
                               PanelIndex=0, FocusPath="0/6", Request=dict(SchemaVersion=3, Nonce=nonce, ApprovalSha256="b" * 64),
                               Observations=[dict(Path=container+"/0", Text="位\u200b置"),
                                             dict(Path=container+"/1/0/0", Text="TEST-\u200bPOSITION")]))
    return dict(capture=capture, expected_source=source, operator_context="TEST operator context, not player identity"), container


def row_bundle():
    # Generic published display label with invented value17: never a real player's fixture.
    fixture, _ = bundle()
    category = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0"
    row = category + "/2/0/0/0/0"
    paths = [category + "/0", row + "/0/0/0/0/0/0/0/0/0", row + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0"]
    fixture["projection_mode"] = "goalkeeper_row0"
    fixture["operator_context"] = "TEST synthetic row observation, not player identity"
    capture = fixture["capture"]
    capture["nonce"] = "33333333-3333-4333-8333-333333333333"
    capture["result"].update(Reason="approved_row_targets_complete", FocusPath=category)
    capture["result"]["Request"]["Nonce"] = capture["nonce"]
    capture["result"]["Observations"] = [dict(Path=path, Text=text) for path, text in
        zip(paths, ["守\u200b门", "出击(倾\u200b向)", "1\u200b7"])]
    return fixture, paths


def main():
    if shutil.which("node") is None:
        raise SystemExit("Node is required; no simulated pass.")
    with tempfile.TemporaryDirectory(prefix="fa-discovery-e2e-") as directory:
        root = Path(directory)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            settings = Settings(data_dir=root, runtime_file=root / "runtime.json", port=port)
            server = uvicorn.Server(uvicorn.Config(create_app(settings, enable_agent=False),
                                    host="127.0.0.1", port=port, log_level="error", access_log=False))
            worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(.02)
                if not server.started:
                    raise RuntimeError("Temporary reader-only backend did not start; no success claim.")
                fixture, container = bundle()
                row, paths = row_bundle()
                payload = dict(root=str(ROOT), runtime=str(settings.runtime_file), bundle=fixture,
                               labelPath=container+"/0", valuePath=container+"/1/0/0", rowBundle=row, rowPaths=paths)
                subprocess.run(["node", "-e", NODE_PROOF], input=json.dumps(payload), text=True,
                               check=True, timeout=30, cwd=ROOT)
            finally:
                server.should_exit = True
                worker.join(timeout=10)
                if worker.is_alive():
                    raise RuntimeError("Temporary server did not stop.")


if __name__ == "__main__":
    main()
