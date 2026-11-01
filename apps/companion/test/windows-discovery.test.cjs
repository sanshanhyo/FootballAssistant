'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { request } = require('../src/backend.cjs');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const { allowsWindowIpc } = require('../src/companion-security.cjs');
const { validateImport, diagnosticReply, asksImportedDiagnostic } = require('../src/windows-discovery.cjs');
const envelope = () => ({ status: 'manual_import_snapshot', import_mode: 'manual_single_event', imported_at: new Date().toISOString(), projection: {
  status: 'partial_display_state', fields: { displayed_position: 'TEST-POSITION' },
  field_provenance: { displayed_position: { panel_index: 0, container_path: '0/6/0', label_path: '0/6/0/0', value_path: '0/6/0/1', association: 'fixed_same_container_same_event', semantic_identity_verified: false } },
  source_identity_unverified: true, page_identity_verified: false, business_identity_known: false, entity_id: null,
  snapshot_atomic: false, source_freshness: 'unknown', captured_at: null, partial: true,
} });

test('deterministic imported diagnostic routing uses one GET, no model, advice, snapshot, watch or mock', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (...args) => { calls.push(args); return envelope(); } });
  const reply = await client.reply({ message: '查看导入诊断中当前球员的位置', conversationId: 'conversation', capability: 'player_info', adviceMode: 'ui_evidence' });
  assert.deepEqual(calls.map(c => c[0]), ['/v1/reader/windows-discovery']);
  assert.equal(calls[0][1], undefined);
  assert.match(reply.text, /TEST-POSITION/); assert.match(reply.text, /身份未验证，时效未知/);
  assert.equal(reply.metadata.synthetic, null); assert.equal(reply.metadata.source, 'manual_import'); assert.equal(reply.metadata.freshness, 'unknown');
  assert.equal(reply.metadata.sampledAt, null); assert.equal(reply.metadata.readiness.production_ready, false);
  assert.equal(reply.cards[0].identity, null); assert.equal(reply.cards[0].fields[1].value, '0/6/0/0');
  assert.equal(asksImportedDiagnostic('看看当前球员位置'), false);
  assert.equal(asksImportedDiagnostic('show imported diagnostic'), true);
});
test('missing, inconsistent, malformed or promoted envelopes fail closed', () => {
  for (const mutate of [e => { e.status = 'unavailable'; }, e => { e.projection.page_identity_verified = true; }, e => { e.projection.source_freshness = 'current'; }, e => { e.projection.fields.displayed_position = {}; }, e => { e.projection.field_provenance.displayed_position.value_path = '../file'; }, e => { e.projection.business_identity_known = true; }]) {
    const data = envelope(); mutate(data); const r = diagnosticReply(data, 'c');
    assert.deepEqual(r.cards, []); assert.doesNotMatch(r.text, /TEST-POSITION/); assert.equal(r.metadata.freshness, 'unknown');
  }
  assert.deepEqual(diagnosticReply(null, 'c').cards, []);
});
test('manual import accepts only bounded JSON objects, snapshots input and never accepts file paths', async () => {
  const original = { capture: { event: 'owned-synthetic' }, expected_source: { pid: 12 } };
  const copy = validateImport(original); original.capture.event = 'changed'; assert.equal(copy.capture.event, 'owned-synthetic');
  for (const input of ['C:\\private\\capture.json', { path: '/tmp/capture' }, { capture: [], expected_source: {} }, { capture: {}, expected_source: {}, file: 'x' }, { capture: { text: 'x'.repeat(32768) }, expected_source: {} }]) assert.throws(() => validateImport(input));
  const calls = []; const client = new RealReaderClient({ request: async (...args) => { calls.push(args); return {}; } });
  await client.importWindowsDiscovery(copy); await client.clearWindowsDiscovery();
  assert.equal(calls[0][0], '/v1/reader/windows-discovery/import'); assert.deepEqual(calls[0][1], copy);
  assert.equal(calls[1][2].method, 'DELETE'); assert.equal(calls[1][1], undefined);
});
test('only trusted settings window can import/get/clear; pet tool read is main-owned', () => {
  for (const name of ['windows-discovery-import', 'windows-discovery-get', 'windows-discovery-clear']) {
    const context = { role: 'settings', trustedMainFrame: true, currentUrl: 'file:///settings', pageUrl: 'file:///settings' };
    assert.equal(allowsWindowIpc(context, name), true);
    assert.equal(allowsWindowIpc({ ...context, role: 'pet' }, name), false);
    assert.equal(allowsWindowIpc({ ...context, trustedMainFrame: false }, name), false);
  }
});
test('controlled transport authenticates exact methods and refuses endpoint/method widening', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'discovery-client-')); t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'runtime.json'); await fs.writeFile(file, JSON.stringify({ token: 'secret-only-main-process', base_url: 'http://127.0.0.1:43123' }));
  const calls = []; const fetch = async (url, options) => { calls.push({ url, ...options }); return { ok: true, text: async () => '{}' }; };
  await request(file, '/v1/reader/windows-discovery', undefined, { fetch });
  await request(file, '/v1/reader/windows-discovery/import', { capture: {}, expected_source: {} }, { fetch });
  await request(file, '/v1/reader/windows-discovery', undefined, { fetch, method: 'DELETE' });
  assert.deepEqual(calls.map(c => c.method), ['GET', 'POST', 'DELETE']);
  for (const call of calls) { assert.equal(call.headers.Authorization, 'Bearer secret-only-main-process'); assert.equal(call.redirect, 'error'); }
  for (const [endpoint, body, method] of [['/v1/chat', undefined, 'DELETE'], ['/v1/reader/windows-discovery/import', undefined, 'DELETE'], ['/v1/reader/windows-discovery', {}, undefined], ['/v1/reader/windows-discovery', undefined, 'PUT']]) {
    await assert.rejects(request(file, endpoint, body, { fetch, method }));
  }
  await assert.rejects(request(file, '/v1/reader/windows-discovery/import', { capture: { text: 'x'.repeat(32768) }, expected_source: {} }, { fetch }));
  assert.equal(calls.length, 3);
});
test('runtime exposes deterministic read-only tool label, not an AI advice tool', async t => {
  const calls = [];
  const client = new RealReaderClient({ request: async endpoint => { calls.push(endpoint); if (endpoint === '/v1/reader/windows-discovery') return envelope(); return {}; } });
  const runtime = new CompanionRuntime({ realClient: client }); t.after(() => runtime.close());
  runtime.setMode('real');
  const tools = []; const done = new Promise(resolve => runtime.on('event', event => { if (event.type === 'tool') tools.push(event.tool); if (event.type === 'request' && event.status === 'completed') resolve(); }));
  runtime.sendMessage({ text: '查看导入诊断' }); await done;
  assert.equal(tools.at(-1).name, 'reader.windows-discovery');
  assert.equal(tools.at(-1).metadata.freshness, 'unknown');
  assert.equal(calls.some(p => p.startsWith('/v1/agent/') || p === '/v1/chat'), false);
  assert.match(runtime.state().messages.at(-1).text, /TEST-POSITION/);
});

test('raw paste preserves duplicate keys through authenticated fixed-endpoint transport', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'discovery-raw-')); t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'runtime.json'); await fs.writeFile(file, JSON.stringify({ token: 'secret-only-main-process', base_url: 'http://127.0.0.1:43123' }));
  const calls = []; const fetch = async (url, options) => { calls.push({ url, ...options }); return { ok: true, text: async () => '{}' }; };
  const rawJson = '{"capture":{"pid":1,"pid":2},"expected_source":{}}';
  const client = new RealReaderClient({ request: (endpoint, body, options) => request(file, endpoint, body, { ...options, fetch }) });
  await client.importWindowsDiscoveryText(rawJson);
  assert.equal(calls[0].method, 'POST'); assert.equal(calls[0].body, rawJson);
  assert.equal(calls[0].headers.Authorization, 'Bearer secret-only-main-process');
  await assert.rejects(request(file, '/v1/chat', undefined, { rawJson, fetch }));
  await assert.rejects(request(file, '/v1/reader/windows-discovery', undefined, { rawJson, fetch }));
  await assert.rejects(request(file, '/v1/reader/windows-discovery/import', {}, { rawJson, fetch }));
  assert.equal(calls.length, 1);
});
test('invalid renderer text clears server state once; failed clear explicitly warns stale server import may remain', async () => {
  const calls = []; const client = new RealReaderClient({ request: async (...args) => { calls.push(args); return {}; } });
  for (const input of ['C:\\private\\capture.json', 'x'.repeat(32769), { file: '/tmp/raw' }]) await assert.rejects(client.importWindowsDiscoveryText(input), /已清除/);
  assert.equal(calls.length, 3); assert.ok(calls.every(c => c[0] === '/v1/reader/windows-discovery' && c[2].method === 'DELETE'));
  const failed = new RealReaderClient({ request: async () => { throw Error('unauthorized'); } });
  await assert.rejects(failed.importWindowsDiscoveryText(null), /可能仍保留上次导入/);
});
