'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
function readiness() {
  const now = Date.now();
  return { production_ready: false, reasons: ['no_business_snapshot'], offseason_readiness: {
    schema: 'fa-offseason-readiness/1', status: 'partial', source: 'native_offseason_reader', scope: 'partial_native_query',
    producer_verified: true, synthetic: false, production_ready: false, freshness: 'fresh',
    observed_at: new Date(now).toISOString(), expires_at: new Date(now + 30000).toISOString(), session_id: 'fixture',
    observed_fields: ['current_manager'], capabilities: { player_info: { ready: true, partial: true },
      transfer_analysis: { ready: false, partial: true }, tactical_analysis: { ready: false, partial: true }, schedule_analysis: { ready: false, partial: true } },
  } };
}
test('verified partial status enables only observed query capability, never full business readiness', async () => {
  const data = readiness(), calls = [];
  const client = new RealReaderClient({ request: async endpoint => { calls.push(endpoint); return data; } });
  const result = await client.status();
  assert.deepEqual(calls, ['/v1/reader/business/status']);
  assert.equal(result.metadata.source, 'native_offseason_reader');
  assert.equal(result.readiness.production_ready, false);
  assert.equal(result.capabilities.filter(x => x.available).length, 1);
  assert.equal(result.capabilities[0].partial, true);
  for (const mutation of [v => v.producer_verified = false, v => v.synthetic = true,
    v => v.expires_at = new Date(Date.now() - 1).toISOString(), v => v.observed_at = new Date(Date.now() - 40000).toISOString()]) {
    const bad = structuredClone(data); mutation(bad.offseason_readiness);
    assert.equal(client.capabilities(bad).some(x => x.available), false);
  }
});
test('busy general response is an AI conversation without fabricated evidence or lost scope', async () => {
  const scope = { save_id: 'session:test', character_id: 'official.eckera' };
  const client = new RealReaderClient({ request: async () => ({ status: 'general_advice', source_status: 'general_knowledge',
    reply: '先聊思路，我会偏向接球稳、出击判断好的门将。', conversation_id: 'c', character_context: scope }) });
  const result = await client.reply({ message: '推荐谁当门将', capability: 'player_info', characterContext: scope });
  assert.equal(result.metadata.source, 'agent'); assert.deepEqual(result.cards, []);
  assert.equal(result.metadata.readiness?.production_ready, false);
  const wrong = new RealReaderClient({ request: async () => ({ status: 'general_advice', source_status: 'general_knowledge', reply: 'x' }) });
  await assert.rejects(wrong.reply({ message: '门将推荐', capability: 'player_info', characterContext: scope }), /范围不匹配/);
});
test('runtime chooses partial chat path and retains updated limited readiness after the reply', async t => {
  const data = readiness(), calls = [];
  const client = new RealReaderClient({ request: async (endpoint, body) => {
    calls.push(endpoint);
    if (!body) return data;
    return { status: 'general_advice', source_status: 'general_knowledge', reply: '聊聊选门将的思路吧。', conversation_id: body.conversation_id,
      character_context: body.character_context, offseason_readiness: data.offseason_readiness };
  } });
  const runtime = new CompanionRuntime({ realClient: client }); t.after(() => runtime.close());
  runtime.mode = 'real';
  runtime.realConnection = { state: 'connected', readiness: data };
  const done = new Promise(resolve => runtime.on('event', e => { if (e.type === 'request' && e.status !== 'running') resolve(e); }));
  runtime.sendMessage({ text: '推荐门将', capability: 'player_info' });
  const event = await done;
  assert.equal(event.status, 'completed');
  assert.ok(calls.includes('/v1/chat')); assert.ok(!calls.includes('/v1/agent/business-advice'));
  assert.equal(runtime.state().capabilities.find(x => x.id === 'player_info').partial, true);
});
test('partial schedule capability preserves the existing calendar evidence path', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (endpoint, body) => {
    calls.push(endpoint);
    return { status: 'unavailable', reply: '先谈轮换思路。', character_context: body.character_context };
  } });
  await client.reply({ message: '该怎么轮换', capability: 'schedule_analysis', nativePartial: true });
  assert.deepEqual(calls, ['/v1/agent/auto-calendar-advice']);
});
