'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { request } = require('../src/backend.cjs');
const { RealReaderClient, adviceCapability, businessMetadata } = require('../src/reader-clients.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const readiness = { status: 'unavailable', production_ready: false, source: null, reasons: ['native_producer_not_verified', 'no_business_snapshot'], capabilities: { schedule_analysis: { ready: false, missing_requirements: ['business_snapshot'] } } };
async function fixture(t, handler) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'real-reader-'));
  const server = http.createServer(handler); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const file = path.join(directory, 'runtime.json');
  await fs.writeFile(file, JSON.stringify({ base_url: `http://127.0.0.1:${server.address().port}`, token: 'secret-not-for-renderer' }));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await fs.rm(directory, { recursive: true, force: true }); });
  return { file, client: new RealReaderClient({ request: (endpoint, body, options) => request(file, endpoint, body, options) }) };
}
function terminal(runtime) {
  return new Promise(resolve => { const listener = event => { if (event.type === 'request' && event.status !== 'running') { runtime.off('event', listener); resolve(event); } }; runtime.on('event', listener); });
}
test('authenticated live loopback transport displays deterministic blocked advice, never chat or mock fallback', async t => {
  const calls = [];
  const { client } = await fixture(t, async (req, res) => {
    assert.equal(req.headers.authorization, 'Bearer secret-not-for-renderer');
    let body = ''; for await (const chunk of req) body += chunk;
    calls.push({ url: req.url, method: req.method, body: body && JSON.parse(body) });
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/v1/reader/business/status') res.end(JSON.stringify(readiness));
    else if (req.url === '/v1/reader/business/snapshot') res.end(JSON.stringify({ ...readiness, snapshot: null }));
    else if (req.url === '/v1/agent/business-advice') res.end(JSON.stringify({ status: 'blocked', readiness, reply: '没有经过验证的业务数据', facts: [], inferences: [], missing_requirements: ['business_snapshot'] }));
    else { res.statusCode = 500; res.end('{}'); }
  });
  const runtime = new CompanionRuntime({ realClient: client }); t.after(() => runtime.close());
  runtime.setMode('real'); assert.equal(runtime.state().canSend, true);
  const done = terminal(runtime); runtime.sendMessage({ text: '看看我的赛程', adviceMode: 'native' }); assert.equal((await done).status, 'completed');
  const reply = runtime.state().messages.find(item => item.role === 'assistant');
  assert.match(reply.text, /验证/); assert.equal(reply.metadata.synthetic, false); assert.equal(reply.metadata.sessionId, null); assert.deepEqual(reply.cards, []);
  assert.deepEqual((await client.snapshot()).cards, []);
  assert.equal(calls.some(call => call.url === '/v1/chat'), false);
  const posted = calls.find(call => call.method === 'POST').body;
  assert.deepEqual(Object.keys(posted).sort(), ['capability', 'conversation_id', 'message']);
  assert.equal(posted.capability, 'schedule_analysis');
  assert.equal(JSON.stringify(runtime.state()).includes('secret-not-for-renderer'), false);
});
test('normal greetings and educational FM questions remain chat; explicit capabilities are validated', async () => {
  const calls = []; const client = new RealReaderClient({ request: async (url, body) => { calls.push({ url, body }); return url.endsWith('/status') ? readiness : { reply: '你好', conversation_id: body.conversation_id }; } });
  const runtime = new CompanionRuntime({ realClient: client }); runtime.setMode('real');
  for (const message of ['你好', '什么是战术', '转会窗规则', '介绍赛程拥挤的概念']) {
    assert.equal(adviceCapability(message), null);
    const done = terminal(runtime); runtime.sendMessage({ text: message }); await done;
  }
  assert.equal(calls.filter(call => call.url === '/v1/chat').length, 4);
  assert.equal(adviceCapability('分析我的战术'), 'tactical_analysis');
  for (const message of ['分析当前阵容', '查看当前球员属性', '看看球队赛程', '给我引援建议', '看看当前页面', '分析这个球员', '看看这页']) assert.notEqual(adviceCapability(message), null);
  assert.equal(adviceCapability('请求', 'player_info'), 'player_info');
  assert.throws(() => runtime.sendMessage({ text: 'hi', capability: 'shell' }), /不支持/);
  await runtime.close();
});
test('transport bounds methods, exposes 401/404, supports abort and timeout, and never leaks tokens', async t => {
  let code = 401;
  const { file, client } = await fixture(t, (_req, res) => { if (code === 0) return; res.statusCode = code; res.end('{}'); });
  await assert.rejects(client.status(), error => error.code === 'unauthorized');
  code = 404;
  await assert.rejects(client.reply({ message: 'test', capability: 'player_info' }), error => error.code === 'unsupported');
  await assert.rejects(request(file, '/v1/reader/business/snapshot', {}), /请求方法/);
  await assert.rejects(request(file, '/v1/agent/business-advice'), /请求方法/);
  code = 0;
  await assert.rejects(request(file, '/v1/reader/business/status', undefined, { timeoutMs: 10 }), /超时/);
  const controller = new AbortController(); const pending = client.status({ signal: controller.signal }); controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
});
test('provenance preserves game session independently of conversation, stale data has no cards, partial verified facts need not satisfy all capabilities', async () => {
  const source = { kind: 'native_read', session_id: 'game-session', observed_at: new Date().toISOString(), captured_at: new Date().toISOString(), synthetic: false, game_build: 'build', evidence_ref: 'evidence' };
  let envelope = { ...readiness, source, status: 'partial', production_ready: true, reasons: [], snapshot: { snapshot_id: 'snap-1', world_date: '2026-10-30', players: null } };
  const client = new RealReaderClient({ request: async () => envelope });
  const result = await client.snapshot(); assert.equal(result.metadata.sessionId, 'game-session'); assert.equal(result.metadata.snapshotId, 'snap-1');
  assert.equal(result.metadata.provenance.evidence_ref, 'evidence'); assert.equal(result.cards[0].fields.find(field => field.label === '/players').value, null);
  envelope = { ...envelope, reasons: ['capture_not_fresh'], snapshot: null };
  assert.equal((await client.snapshot()).metadata.freshness, 'stale'); assert.deepEqual((await client.snapshot()).cards, []);
  assert.equal(businessMetadata({ ...envelope, reasons: ['observation_time_unknown'] }).freshness, 'unknown');
});
test('real reconnect and cancellation fence old replies even if transport ignores abort', async () => {
  const replies = []; const client = new RealReaderClient({ request: async (url) => url.endsWith('/status') ? readiness : new Promise(resolve => replies.push(resolve)) });
  const runtime = new CompanionRuntime({ realClient: client }); runtime.setMode('real');
  const first = runtime.sendMessage({ text: '你好' }); await new Promise(setImmediate);
  runtime.setMode('real'); replies[0]({ reply: 'OLD' }); await new Promise(setImmediate);
  assert.equal(runtime.state().messages.length, 0);
  const second = runtime.sendMessage({ text: '你好' }); await new Promise(setImmediate); runtime.cancelRequest(second.requestId);
  replies[1]({ reply: 'CANCELLED' }); await new Promise(setImmediate);
  assert.equal(runtime.state().messages.filter(message => message.role === 'assistant').length, 0);
  assert.ok(runtime.state().epoch > first.epoch); await runtime.close();
});
test('token rotation during an in-flight response rejects the old backend identity', async t => {
  const { file } = await fixture(t, (_req, res) => res.end('{}'));
  await assert.rejects(request(file, '/v1/reader/business/status', undefined, { fetch: async () => {
    const runtime = JSON.parse(await fs.readFile(file, 'utf8')); runtime.token = 'rotated-secret-not-for-renderer'; await fs.writeFile(file, JSON.stringify(runtime));
    return { ok: true, text: async () => JSON.stringify(readiness) };
  } }), error => error.code === 'connection_changed');
});
test('future generated advice preserves cited snapshot facts while stale envelopes never render cards', async () => {
  let reasons = [];
  const client = new RealReaderClient({ request: async () => ({ status: 'generated', reply: '建议/推断', readiness: { production_ready: true, reasons, source: { kind: 'native_read', session_id: 'game', observed_at: new Date().toISOString(), synthetic: false } }, facts: [{ snapshot_id: 'snap', field_ref: '/world_date', value: '2026-10-30' }] }) });
  const result = await client.reply({ message: 'test', capability: 'schedule_analysis' });
  assert.equal(result.metadata.snapshotId, 'snap'); assert.equal(result.cards[0].fields[0].label, 'snap /world_date');
  reasons = ['observation_not_fresh']; assert.deepEqual((await client.reply({ message: 'test', capability: 'schedule_analysis' })).cards, []);
});
test('successful retry restores connection state after a real transport failure', async () => {
  let failed = true;
  const client = new RealReaderClient({ request: async url => { if (url.endsWith('/status')) return readiness; if (failed) throw Error('offline'); return { reply: 'recovered' }; } });
  const runtime = new CompanionRuntime({ realClient: client }); runtime.setMode('real');
  let done = terminal(runtime); runtime.sendMessage({ text: '你好' }); assert.equal((await done).status, 'error'); assert.equal(runtime.state().connection.state, 'unavailable');
  failed = false; done = terminal(runtime); runtime.sendMessage({ text: '你好' }); assert.equal((await done).status, 'completed'); assert.equal(runtime.state().connection.state, 'connected');
  await runtime.close();
});
test('Alpha defaults current-game questions to explicit partial UI advice, no native promotion or fallback', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (url, body) => {
    calls.push({ url, body });
    if (url.endsWith('/status')) return readiness;
    return { status: 'generated', reply: 'TEST UI only', conversation_id: body.conversation_id,
      provenance: { session_id: 'TEST-game', event_id: 'TEST-event', captured_at: 'TEST-time' },
      limitations: ['TEST partial UI'], page: { name: null, verified: false } };
  } });
  const runtime = new CompanionRuntime({ realClient: client }); runtime.setMode('real');
  const done = terminal(runtime); runtime.sendMessage({ text: '看看我的赛程' }); await done;
  assert.equal(calls.filter(call => call.url === '/v1/agent/ui-advice').length, 1);
  assert.equal(calls.some(call => ['/v1/chat', '/v1/agent/business-advice'].includes(call.url)), false);
  const reply = runtime.state().messages.find(item => item.role === 'assistant');
  assert.equal(reply.metadata.source, 'ui'); assert.equal(reply.metadata.partial, true);
  assert.equal(reply.metadata.readiness.production_ready, false); assert.deepEqual(reply.cards, []);
  assert.equal(reply.metadata.sessionId, 'TEST-game');
  assert.match(runtime.state().limitations.join(' '), /部分 UI 采样文本/);
  assert.match(runtime.state().limitations.join(' '), /隐藏或缓存/);
  assert.match(runtime.state().limitations.join(' '), /不会使原生能力就绪/);
  assert.equal(runtime.state().limitations.join(' ').includes('业务建议只使用服务端验证事实'), false);
  assert.throws(() => runtime.sendMessage({ text: 'TEST', adviceMode: 'fake' }), /不支持/);
  await runtime.close();
});
