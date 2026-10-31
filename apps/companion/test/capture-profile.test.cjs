'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const tick = () => new Promise(setImmediate);
function fixture() {
  let sequence = 0; let result; let reads = 0; const writes = [];
  const client = { capabilities: () => [], reply: async () => {}, status: async () => ({ metadata: { limitations: [] } }),
    previews: async () => { reads++; return [{ id: 'schedule', status: 'unknown', fields: [] }]; }, uiChangePreview: async () => null,
    setCaptureProfile: async profile => { writes.push(profile); result = { profile, status: 'pending', sequence: ++sequence }; return result; },
    captureProfileStatus: async () => result,
  };
  const runtime = new CompanionRuntime({ realClient: client }); runtime.setMode('real');
  return { runtime, client, writes, reads: () => reads, status: patch => { result = { ...result, ...patch }; } };
}
test('fixed profile client validates names and only sends profile to the authenticated control route', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (...args) => { calls.push(args); return {}; } });
  for (const profile of ['schedule', 'current_page_attributes', 'tactics', 'next_match']) await client.setCaptureProfile(profile);
  for (const value of ['../root', 'focus=/secret', {}, '']) await assert.rejects(client.setCaptureProfile(value), /不支持/);
  await client.captureProfileStatus();
  assert.equal(calls.length, 5);
  assert.ok(calls.every(call => call[0] === '/v1/reader/capture-profile'));
  assert.deepEqual(calls.slice(0, 4).map(call => call[1]), [{ profile: 'schedule' }, { profile: 'current_page_attributes' }, { profile: 'tactics' }, { profile: 'next_match' }]);
  assert.equal(calls[4][1], undefined);
});
test('applied alone is not success: fresh ready scope confirmation precedes preview fetch', async () => {
  const f = fixture(); await tick(); const before = f.reads();
  await f.runtime.setCaptureProfile('current_page_attributes'); await tick();
  assert.equal(f.runtime.state().captureRequest.status, 'pending'); assert.equal(f.reads(), before);
  assert.deepEqual(f.runtime.state().readerPreviews, []);
  f.status({ status: 'applied' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.status, 'applied'); assert.equal(f.reads(), before);
  f.status({ status: 'ready' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.status, 'ready'); assert.equal(f.reads(), before + 1);
  await f.runtime.close();
});
test('different profile switch rejects late previous profile/sequence confirmations', async () => {
  const f = fixture(); await tick();
  await f.runtime.setCaptureProfile('schedule'); await tick();
  await f.runtime.setCaptureProfile('tactics'); await tick();
  f.status({ profile: 'schedule', sequence: 1, status: 'ready' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.profile, 'tactics');
  assert.equal(f.runtime.state().captureRequest.status, 'pending'); assert.deepEqual(f.runtime.state().readerPreviews, []);
  f.status({ profile: 'tactics', sequence: 2, status: 'ready' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.status, 'ready'); assert.deepEqual(f.writes, ['schedule', 'tactics']);
  await f.runtime.close();
});
test('busy repeated clicks write once and response after session switch cannot attach to a new card', async () => {
  const f = fixture(); await tick(); let resolve; let writes = 0;
  f.client.setCaptureProfile = () => { writes++; return new Promise(done => { resolve = done; }); };
  const request = f.runtime.setCaptureProfile('schedule');
  await f.runtime.setCaptureProfile('schedule'); await f.runtime.setCaptureProfile('current_page_attributes');
  assert.equal(writes, 1);
  f.runtime.switchSession(); resolve({ profile: 'schedule', sequence: 1, status: 'pending' }); await request; await tick();
  assert.equal(f.runtime.state().captureRequest, null); await f.runtime.close();
});
test('POST failure and confirmation disconnect remain failed, never ready', async () => {
  const f = fixture(); await tick();
  f.client.setCaptureProfile = async () => { throw Error('TEST offline'); };
  await f.runtime.setCaptureProfile('schedule');
  assert.equal(f.runtime.state().captureRequest.status, 'failed'); assert.match(f.runtime.state().captureRequest.reason, /offline/);
  f.client.setCaptureProfile = async profile => ({ profile, sequence: 3, status: 'pending' });
  f.client.captureProfileStatus = async () => { throw Error('TEST disconnected'); };
  await f.runtime.setCaptureProfile('current_page_attributes'); await tick();
  assert.equal(f.runtime.state().captureRequest.status, 'failed');
  assert.equal(f.runtime.state().connection.state, 'unavailable');
  await f.runtime.close();
});
test('a POST ready response is not trusted as fresh confirmation and mock mode cannot write', async () => {
  const f = fixture(); await tick();
  f.client.setCaptureProfile = async profile => ({ profile, sequence: 1, status: 'ready' });
  await f.runtime.setCaptureProfile('tactics'); assert.equal(f.runtime.state().captureRequest.status, 'failed');
  f.runtime.setMode('mock'); await assert.rejects(f.runtime.setCaptureProfile('tactics'), /真实/);
  await f.runtime.close();
});

test('unconfigured control response stays explicit rather than waiting forever or claiming applied', async () => {
  const f = fixture(); await tick();
  f.client.setCaptureProfile = async () => ({ profile: null, sequence: null, status: 'not_configured', reason: 'TEST configure control' });
  await f.runtime.setCaptureProfile('schedule');
  assert.equal(f.runtime.state().captureRequest.profile, 'schedule');
  assert.equal(f.runtime.state().captureRequest.status, 'not_configured');
  f.client.setCaptureProfile = async profile => ({ profile, sequence: 4, status: 'pending' });
  f.client.captureProfileStatus = async () => ({ profile: null, sequence: null, status: 'unavailable', reason: 'TEST control removed' });
  await f.runtime.setCaptureProfile('tactics'); await tick();
  assert.equal(f.runtime.state().captureRequest.status, 'unavailable');
  await f.runtime.close();
});

test('next_match control reuses readiness confirmation without claiming a full schedule', async () => {
  const f = fixture(); await tick();
  await f.runtime.setCaptureProfile('next_match'); await tick();
  assert.equal(f.runtime.state().captureRequest.profile, 'next_match');
  assert.equal(f.runtime.state().captureRequest.status, 'pending');
  f.status({ status: 'applied' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.status, 'applied');
  f.status({ status: 'ready' }); await f.runtime.refreshReaderPreviews();
  assert.equal(f.runtime.state().captureRequest.status, 'ready');
  assert.deepEqual(f.writes, ['next_match']); await f.runtime.close();
});
