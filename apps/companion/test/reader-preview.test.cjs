'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { RealReaderClient, previewCard, PREVIEWS } = require('../src/reader-clients.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const tick = () => new Promise(setImmediate);
function envelope(spec, extra = {}) {
  return { source: 'ui', partial: true, production_ready: false, status: spec.status,
    provenance: { session_id: 'game', captured_at: new Date().toISOString() },
    [spec.key]: { status: spec.status, rows: [{ date_display: '周六', opponent_display: 'TEST', player_id: 'DO NOT DISPLAY' }],
      formation_display: '4-3-3', raw_texts: { hidden: 'DO NOT DISPLAY' }, identity: null,
      groups: [{ category_display: '技术', rows: [{ label_display: '传球', value: 0 }] }] }, ...extra };
}
test('preview whitelist renders mapped display only, zero preserved, attributes never assigned to player', () => {
  for (const spec of PREVIEWS) {
    const card = previewCard(spec, envelope(spec));
    assert.equal(card.status, 'available'); assert.equal(card.identity, null);
    assert.equal(JSON.stringify(card).includes('DO NOT DISPLAY'), false);
    assert.equal(card.metadata.partial, true);
    if (spec.id === 'current-page-attributes') {
      assert.equal(card.fields[0].value, null); assert.equal(card.fields[1].value, '0');
      assert.match(card.metadata.limitations.join(), /不绑定任何球员/);
    }
  }
});
test('expired, future, missing timestamp and unavailable projections never retain old values', () => {
  const spec = PREVIEWS[0];
  for (const [patch, status] of [
    [{ provenance: { captured_at: new Date(Date.now() - 16_000).toISOString() } }, 'stale'],
    [{ reasons: ['stale_ui_snapshot'], provenance: null }, 'stale'],
    [{ provenance: { captured_at: new Date(Date.now() + 60_000).toISOString() } }, 'unknown'],
    [{ provenance: null }, 'unknown'], [{ status: 'unavailable' }, 'unknown'], [{ synthetic: true }, 'unknown'],
  ]) { const card = previewCard(spec, envelope(spec, patch)); assert.equal(card.status, status); assert.deepEqual(card.fields, []); }
});
test('preview client GETs only four fixed local routes, failures stay unknown; never calls advice', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (url, body) => { calls.push([url, body]); throw new Error('offline'); } });
  const cards = await client.previews(); assert.equal(cards.length, 3);
  assert.ok(cards.every(card => card.status === 'unknown' && !card.fields.length));
  await assert.rejects(client.uiChangePreview(), /offline/);
  assert.deepEqual(calls.map(([url]) => url), [...PREVIEWS.map(spec => `/v1/reader/${spec.id}`), '/v1/reader/ui-change-preview']);
  assert.ok(calls.every(([,body]) => body === undefined));
});
function runtimeFixture() {
  let pending;
  const runtime = new CompanionRuntime({ realClient: { capabilities: () => [], status: async () => ({ metadata: { limitations: [] } }), reply: async () => { throw Error('must not call model'); },
    previews: () => new Promise(resolve => { pending = resolve; }), uiChangePreview: async () => null } });
  return { runtime, resolve: value => pending(value) };
}
test('preview results cannot cross mode/session or close even when request ignores abort', async () => {
  for (const action of ['mode', 'session', 'close']) {
    const f = runtimeFixture(); f.runtime.setMode('real');
    if (action === 'mode') f.runtime.setMode('mock');
    if (action === 'session') { const old = f.resolve;
      const original = f.runtime.realClient.previews;
      let late; f.runtime.realClient.previews = () => new Promise(resolve => { late = resolve; });
      f.runtime.switchSession(); old([{ id: 'OLD' }]); late([]); f.runtime.realClient.previews = original;
    } else { if (action === 'close') await f.runtime.close(); f.resolve([{ id: 'OLD' }]); }
    await tick(); assert.equal(JSON.stringify(f.runtime.state().readerPreviews).includes('OLD'), false);
    await f.runtime.close();
  }
});
test('stable changes use existing local proactive message path, mute suppresses, polling never POSTs', async () => {
  let frame = 0; let hash = 'a'; let clock = Date.now() - 1000;
  const runtime = new CompanionRuntime({ realClient: { capabilities: () => [], status: async () => ({ metadata: { limitations: [] } }), reply: async () => { throw Error('must not call model'); },
    previews: async () => [], uiChangePreview: async () => ({ status:'ready', kind:'schedule', source:'ui', synthetic:false, partial:true, production_ready:false,
      session_id:'game', event_id:`event-${++frame}`, captured_at:new Date(++clock).toISOString(), display_sha256:hash.repeat(64), scope_sha256:'c'.repeat(64) }) } });
  runtime.setMode('real'); await tick(); await runtime.refreshReaderPreviews(); hash = 'b';
  await runtime.refreshReaderPreviews(); await runtime.refreshReaderPreviews();
  const notices = runtime.state().messages;
  assert.equal(notices.length, 1); assert.equal(notices[0].origin, 'proactive');
  assert.equal(notices[0].sessionId, runtime.sessionId); assert.equal(notices[0].metadata.sessionId, 'game');
  runtime.setProactivity(0); await tick(); hash = 'd'; await runtime.refreshReaderPreviews(); await runtime.refreshReaderPreviews();
  assert.equal(runtime.state().messages.length, 1); await runtime.close();
});
test('settings preview is safely rendered with DOM text, and refresh IPC is explicit', () => {
  const src = name => fs.readFileSync(path.join(__dirname, '../src', name), 'utf8');
  assert.match(src('settings.html'), /id="reader-previews"/);
  assert.match(src('settings.js'), /element.textContent = String\(text\)/);
  assert.match(src('preload.cjs'), /refreshReaderPreviews:.*refresh-reader-previews/);
  assert.match(src('main.cjs'), /handle\('refresh-reader-previews'/);
});

test('already displayed previews expire even while next transport is pending', async () => {
  const f = runtimeFixture(); f.runtime.setMode('real');
  const card = previewCard(PREVIEWS[0], envelope(PREVIEWS[0]));
  f.resolve([card]); await tick();
  assert.equal(f.runtime.state().readerPreviews[0].status, 'available');
  f.runtime.readerPreviews[0].metadata.sampledAt = new Date(Date.now() - 16_000).toISOString();
  assert.equal(f.runtime.state().readerPreviews[0].status, 'stale');
  assert.deepEqual(f.runtime.state().readerPreviews[0].fields, []);
  await f.runtime.close();
});

test('repeated refresh does not overlap and mute fences a late changed frame', async () => {
  let calls = 0; const replies = [];
  const runtime = new CompanionRuntime({ realClient: {
    capabilities: () => [], status: async () => ({ metadata: { limitations: [] } }), reply: async () => {},
    previews: () => { calls++; return new Promise(resolve => replies.push(resolve)); },
    uiChangePreview: async () => null,
  } });
  runtime.setMode('real'); await runtime.refreshReaderPreviews();
  assert.equal(calls, 1);
  runtime.setProactivity(0); assert.equal(calls, 2);
  replies[0]([{ id: 'LATE', status: 'unknown' }]); await tick();
  assert.deepEqual(runtime.state().readerPreviews, []);
  replies[1]([]); await tick();
  assert.deepEqual(runtime.state().messages, []); await runtime.close();
});
