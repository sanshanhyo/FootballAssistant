'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const { MockReaderClient, DisconnectedReaderClient, metadata } = require('../src/reader-clients.cjs');
const { allowsMicrophone } = require('../src/companion-security.cjs');
const tick = () => new Promise(resolve => setImmediate(resolve));

function controlledClient() {
  const resolutions = [];
  return {
    resolutions,
    capabilities: () => new MockReaderClient().capabilities(),
    snapshot: ({ sessionId }) => new Promise(resolve => resolutions.push(() => resolve({ metadata: metadata(sessionId), cards: [] }))),
  };
}

test('startup is explicitly simulated and real mode never silently invokes mock', async () => {
  const client = controlledClient();
  const runtime = new CompanionRuntime({ mockClient: client });
  const state = await runtime.init();
  assert.equal(state.mode, 'mock'); assert.equal(state.proactivity, 80); assert.equal(state.historyEnabled, false);
  assert.equal(state.connection.state, 'simulated'); assert.equal(state.synthetic, true);
  assert.ok(state.limitations.length); assert.ok(state.capabilities.every(item => item.synthetic));
  assert.equal(client.resolutions.length, 0);
  const real = runtime.setMode('real');
  assert.equal(real.connection.state, 'unavailable'); assert.equal(real.synthetic, false);
  assert.ok(real.capabilities.every(item => !item.available));
  assert.throws(() => runtime.sendMessage({ text: '你好' }), /尚未接入/);
  await assert.rejects(runtime.simulateEvent(), /明确选择模拟模式/);
  assert.equal(client.resolutions.length, 0); await runtime.close();
});

test('backend and session changes reject late responses even when transport ignores abort', async () => {
  const client = controlledClient(); const runtime = new CompanionRuntime({ mockClient: client }); const events = [];
  runtime.on('event', event => events.push(event));
  const first = runtime.sendMessage({ text: '旧请求' }); await tick();
  const changed = runtime.setMode({ mode: 'mock', backendId: 'second-mock' });
  assert.ok(changed.epoch > first.epoch); assert.notEqual(changed.sessionId, first.sessionId);
  client.resolutions[0](); await tick();
  assert.equal(runtime.state().messages.length, 0);
  assert.equal(events.filter(event => event.type === 'message' && event.message.role === 'assistant').length, 0);
  assert.ok(events.some(event => event.type === 'request' && event.requestId === first.requestId && event.status === 'cancelled'));
  assert.throws(() => runtime.sendMessage({ text: 'late', generation: first.epoch }), /已切换/);
  assert.throws(() => runtime.sendMessage({ text: 'late', conversationId: first.sessionId }), /已切换/);
  await runtime.close();
});

test('parallel replies retain request attribution and cancellation discards late completion', async () => {
  const client = controlledClient(); const runtime = new CompanionRuntime({ mockClient: client });
  const one = runtime.sendMessage({ text: '第一条' }); const two = runtime.sendMessage({ text: '第二条' }); await tick();
  assert.equal(runtime.state().pendingRequests.length, 2);
  client.resolutions[1](); await tick();
  const reply = runtime.state().messages.find(item => item.role === 'assistant');
  assert.equal(reply.requestId, two.requestId); assert.equal(reply.metadata.synthetic, true);
  assert.equal(runtime.cancelRequest(one.requestId).cancelled, true);
  client.resolutions[0](); await tick();
  assert.equal(runtime.state().messages.filter(item => item.role === 'assistant').length, 1);
  assert.equal(runtime.state().pendingRequests.length, 0); await runtime.close();
});

test('missing and stale examples preserve unknown null values and complete provenance', async () => {
  const runtime = new CompanionRuntime({ mockClient: new MockReaderClient({ delay: 0 }) });
  await runtime.simulateEvent('missing'); await runtime.simulateEvent('stale');
  const [missing, stale] = runtime.state().messages;
  assert.ok(missing.cards[0].fields.every(field => field.value === null && field.status === 'unknown'));
  assert.equal(stale.metadata.freshness, 'stale'); assert.ok(Date.parse(stale.metadata.sampledAt) < Date.now() - 60_000);
  for (const message of [missing, stale]) {
    for (const field of ['source', 'sourceLabel', 'sessionId', 'sampledAt', 'partial', 'limitations', 'synthetic']) assert.ok(Object.hasOwn(message.metadata, field));
    assert.equal(message.metadata.synthetic, true); assert.equal(message.metadata.partial, true);
    assert.equal(message.cards[0].metadata.sessionId, message.sessionId);
  }
  await runtime.close();
});

test('history persistence is opt-in and clearing chat does not delete explicit memories', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'companion-runtime-'));
  const file = path.join(directory, 'state.json');
  try {
    const runtime = new CompanionRuntime({ file, mockClient: new MockReaderClient({ delay: 0 }) });
    await runtime.init(); await runtime.simulateEvent();
    const memory = await runtime.saveMemory({ text: '用户明确保存的偏好' });
    let saved = JSON.parse(await fs.readFile(file, 'utf8'));
    assert.equal(saved.messages.length, 0); assert.equal(saved.memories.length, 1);
    runtime.setHistoryEnabled(true); await runtime.persist();
    saved = JSON.parse(await fs.readFile(file, 'utf8')); assert.equal(saved.messages.length, 1);
    const restored = new CompanionRuntime({ file }); await restored.init();
    assert.equal(restored.getHistory().messages.length, 1); assert.equal(restored.getMemories().entries[0].id, memory.id);
    await restored.clearHistory(); assert.equal(restored.getHistory().messages.length, 0); assert.equal(restored.getMemories().entries.length, 1);
    assert.equal((await restored.deleteMemory(memory.id)).deleted, true);
    await restored.close(); await runtime.close();
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});

test('malformed local storage is preserved and never replaced by automatic startup', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'companion-storage-')); const file = path.join(directory, 'state.json');
  try {
    await fs.writeFile(file, '{malformed'); const runtime = new CompanionRuntime({ file }); await runtime.init();
    assert.match(runtime.state().storageWarning, /原文件未被删除/);
    runtime.setProactivity(50); await runtime.close();
    assert.equal(await fs.readFile(file, 'utf8'), '{malformed');
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});

test('real reader unavailable contract has no implicit transport or synthetic fallback', async () => {
  const reader = new DisconnectedReaderClient(); assert.equal((await reader.status()).synthetic, false);
  for (const method of ['snapshot', 'rawUi', 'events', 'native']) await assert.rejects(reader[method](), /尚未接入/);
  assert.throws(() => reader.watch(() => {}), /尚未接入/);
});

test('microphone policy supports Electron check and request shapes only for trusted audio main frame', () => {
  const pageUrl = 'file:///app/index.html';
  const trusted = { trustedContents: true, currentUrl: pageUrl, pageUrl };
  const base = { isMainFrame: true, requestingUrl: pageUrl };
  assert.equal(allowsMicrophone(trusted, 'media', { ...base, mediaType: 'audio' }, true), true);
  assert.equal(allowsMicrophone(trusted, 'media', { ...base, mediaTypes: ['audio'] }), true);
  for (const details of [
    { ...base, mediaTypes: ['audio', 'video'] }, { ...base, mediaTypes: ['video'] },
    { ...base, mediaTypes: [] }, { ...base, mediaTypes: ['audio'], isMainFrame: false },
    { ...base, mediaTypes: ['audio'], requestingUrl: 'file:///app/settings.html' },
    { mediaTypes: ['audio'] },
  ]) assert.equal(allowsMicrophone(trusted, 'media', details), false);
  for (const mediaType of ['video', 'unknown', undefined]) assert.equal(allowsMicrophone(trusted, 'media', { ...base, mediaType }, true), false);
  assert.equal(allowsMicrophone({ ...trusted, trustedContents: false }, 'media', { ...base, mediaTypes: ['audio'] }), false);
  assert.equal(allowsMicrophone(trusted, 'display-capture', { ...base, mediaTypes: ['audio'] }), false);
});

test('simulated disconnection cancels pending replies and requires an explicit recovery scenario', async () => {
  const client = controlledClient(); const runtime = new CompanionRuntime({ mockClient: client });
  const pending = runtime.sendMessage({ text: '断线前请求' }); await tick();
  const disconnecting = runtime.simulateEvent('disconnected'); await tick();
  assert.equal(runtime.state().connection.state, 'disconnected');
  assert.equal(runtime.state().pendingRequests.length, 0); assert.ok(runtime.state().epoch > pending.epoch);
  assert.throws(() => runtime.sendMessage({ text: '断线时请求' }), /模拟连接已失效/);
  client.resolutions[0](); client.resolutions[1](); await disconnecting; await tick();
  assert.equal(runtime.state().messages.filter(item => item.origin === 'reply').length, 0);
  const recovering = runtime.simulateEvent('default'); await tick();
  client.resolutions[2](); await recovering;
  assert.equal(runtime.state().connection.state, 'simulated'); await runtime.close();
});
