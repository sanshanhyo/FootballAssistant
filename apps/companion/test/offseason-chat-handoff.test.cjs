'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RealReaderClient } = require('../src/reader-clients.cjs');
test('partial native chat and advice retain partial provenance, never full business readiness', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (endpoint) => {
    calls.push(endpoint);
    return { status: 'partial', source_status: 'partial_native_candidates', reply: 'Only observed candidates', conversation_id: 'conversation', context: { observed_at: new Date().toISOString(), limitations: ['Current team is unknown'] } };
  }});
  for (const input of [{message: '你看一下吧'}, {message: '谁当门将合适', capability: 'tactical_analysis'}]) {
    const reply = await client.reply(input);
    assert.equal(reply.metadata.source, 'native_offseason_reader');
    assert.equal(reply.metadata.partial, true);
    assert.equal(reply.metadata.readiness.production_ready, false);
    assert.deepEqual(reply.cards, []);
  }
  assert.deepEqual(calls, ['/v1/chat', '/v1/agent/business-advice']);
});
