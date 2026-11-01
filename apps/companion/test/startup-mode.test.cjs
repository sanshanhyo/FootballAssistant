'use strict';
// Actual loopback fixture, no external service, model request or game access.
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { initializeCompanion } = require('../src/bootstrap.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const { RealReaderClient, MockReaderClient } = require('../src/reader-clients.cjs');
const { request } = require('../src/backend.cjs');

function terminal(runtime) {
  return new Promise(resolve => {
    const listener = event => { if (event.type === 'request' && event.status !== 'running') { runtime.off('event', listener); resolve(event); } };
    runtime.on('event', listener);
  });
}
async function startup(t, { configured = true } = {}) {
  const calls = [];
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-startup-fixture-'));
  const server = http.createServer(async (req, res) => {
    assert.equal(req.headers.authorization, 'Bearer synthetic-local-fixture-token');
    let body = ''; for await (const chunk of req) body += chunk;
    calls.push({ path: req.url, method: req.method, body: body ? JSON.parse(body) : null });
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'GET') return res.end(JSON.stringify({ status: 'unavailable', production_ready: false, source: null, reasons: ['fixture_no_native_data'] }));
    if (!configured) { res.statusCode = 503; return res.end(JSON.stringify({ detail: { code: 'model_not_configured', message: '需要配置模型服务地址、模型名和 API Key。' } })); }
    res.end(JSON.stringify({ status: 'generated', reply: '本机 fixture 回复，不是真实模型。', limitations: [],
      provenance: { platform: 'windows-x64', adapter_id: 'footballassistant.windows-finite-ui' } }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const runtimeFile = path.join(directory, 'runtime.json');
  await fs.writeFile(runtimeFile, JSON.stringify({ base_url: `http://127.0.0.1:${server.address().port}`, token: 'synthetic-local-fixture-token' }));
  const client = new RealReaderClient({ request: (endpoint, body, options) => request(runtimeFile, endpoint, body, options) });
  const runtime = new CompanionRuntime({ realClient: client });
  let mockCalls = 0;
  runtime.mockClient.snapshot = async () => { mockCalls++; throw Error('normal startup must never invoke mock'); };
  t.after(async () => { await runtime.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await fs.rm(directory, { recursive: true, force: true }); });
  await initializeCompanion(runtime); // The exact helper called by main.cjs, no manual mode switch.
  return { runtime, calls, mockCalls: () => mockCalls };
}

test('normal desktop startup routes current-page question to real authenticated UI-advice, not mock', async t => {
  const { runtime, calls, mockCalls } = await startup(t);
  assert.equal(runtime.state().mode, 'real'); assert.equal(runtime.state().synthetic, false);
  const done = terminal(runtime); runtime.sendMessage({ text: '当前页面属性' });
  assert.equal((await done).status, 'completed');
  const posted = calls.filter(call => call.method === 'POST');
  assert.equal(posted.length, 1); assert.equal(posted[0].path, '/v1/agent/ui-advice');
  assert.equal(posted[0].body.capability, 'player_info');
  const reply = runtime.state().messages.find(item => item.role === 'assistant');
  assert.equal(reply.text, '本机 fixture 回复，不是真实模型。');
  assert.equal(reply.metadata.freshness, 'capture_summary');
  assert.equal(mockCalls(), 0);
});

test('unconfigured real backend reports actual short configuration error without synthetic answer', async t => {
  const { runtime, mockCalls } = await startup(t, { configured: false });
  const done = terminal(runtime); runtime.sendMessage({ text: '你好' });
  const result = await done;
  assert.equal(result.status, 'error'); assert.match(result.error, /需要配置模型服务/);
  assert.equal(runtime.state().mode, 'real'); assert.equal(runtime.state().synthetic, false);
  assert.equal(runtime.state().messages.some(item => item.role === 'assistant'), false);
  assert.equal(mockCalls(), 0);
});

test('offline fixture mode remains explicit opt-in after normal startup', async () => {
  const runtime = new CompanionRuntime({ mockClient: new MockReaderClient({ delay: 0 }) });
  await initializeCompanion(runtime);
  assert.equal(runtime.state().mode, 'real');
  assert.throws(() => runtime.sendMessage({ text: 'test' }), /尚未接入/);
  runtime.setMode('mock');
  const done = terminal(runtime); runtime.sendMessage({ text: 'explicit fixture' });
  assert.equal((await done).status, 'completed');
  assert.equal(runtime.state().synthetic, true);
  assert.match(runtime.state().messages.find(item => item.role === 'assistant').text, /模拟回复/);
  await runtime.close();
});

test('desktop main uses shared real startup path before registering message IPC, without new diagnostic UI', async () => {
  const main = await fs.readFile(path.join(__dirname, '../src/main.cjs'), 'utf8');
  assert.ok(main.includes('await initializeCompanion(runtime);'));
  assert.ok(main.indexOf('await initializeCompanion(runtime);') < main.indexOf('  registerIpc();'));
  const settings = await fs.readFile(path.join(__dirname, '../src/settings.html'), 'utf8');
  assert.doesNotMatch(settings, /id="(?:mode|observations|discovery-capture|tasks)"/);
});
