'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { mountDiscoverySettings, parseInput, WARNING } = require('../src/discovery-settings.js');
function ui(api) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { value: '', disabled: false, textContent: '', children: [], handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }, append(...nodes) { this.children.push(...nodes); }, replaceChildren() { this.children = []; }, set innerHTML(_) { throw Error('HTML injection sink forbidden'); } });
    return elements.get(id);
  };
  const controller = mountDiscoverySettings({ api, document: { getElementById: get, createElement: () => get(Symbol()) } });
  return { get, controller, click: id => get(id).handlers.click(), output: () => get('discovery-fields').children.map(node => node.textContent).join('\n') };
}
const ok = value => ({ ok: true, value });
const envelope = position => ({ status: 'manual_import_snapshot', import_mode: 'manual_single_event', imported_at: '2026-01-01T00:00:00Z', projection: { status: 'partial_display_state', partial: true, source_identity_unverified: true, page_identity_verified: false, business_identity_known: false, entity_id: null, snapshot_atomic: false, source_freshness: 'unknown', captured_at: null, fields: { displayed_position: position }, field_provenance: { displayed_position: { semantic_identity_verified: false, association: 'fixed_same_container_same_event', panel_index: 0, container_path: '0/6/0', label_path: '0/6/0/0', value_path: '0/6/0/1' } } } });
test('manual mount makes no call; import parses two objects and clears pasted text only after success', async () => {
  const calls = [];
  const f = ui({ windowsDiscoveryImport: async input => { calls.push(input); return ok(envelope('TEST position')); } });
  assert.deepEqual(calls, []);
  f.get('discovery-capture').value = '{"synthetic_fixture":true}'; f.get('discovery-source').value = '{"pid":12}';
  await f.click('discovery-import');
  assert.deepEqual(calls, ['{"capture":{"synthetic_fixture":true},"expected_source":{"pid":12}}']);
  assert.equal(f.get('discovery-capture').value, ''); assert.equal(f.get('discovery-source').value, '');
  assert.match(f.output(), /TEST position/); assert.match(f.output(), /0\/6\/0\/1/);
  assert.equal(f.get('discovery-warning').textContent, WARNING);
});
test('local-invalid import clears previous server snapshot once without POST', async () => {
  for (const capture of ['C:\\private\\capture.json', '[]', 'null', '{']) assert.throws(() => parseInput(capture, '{}'));
  assert.throws(() => parseInput('{}', '[]'));
  assert.throws(() => parseInput(JSON.stringify({ value: '中'.repeat(23000) }), '{}'));
  let calls = 0, clears = 0; const f = ui({ windowsDiscoveryImport: async () => { calls++; }, windowsDiscoveryClear: async () => { clears++; return ok({ status: 'unavailable' }); } });
  f.get('discovery-capture').value = '[]'; f.get('discovery-source').value = '{}'; await f.click('discovery-import');
  assert.equal(calls, 0); assert.equal(clears, 1); assert.match(f.get('discovery-status').textContent, /先前的导入已清除/); assert.equal(f.get('discovery-capture').value, '[]'); assert.equal(f.controller.busy, false);
  f.get('discovery-capture').value = JSON.stringify({ value: '中'.repeat(23000) }); await f.click('discovery-import');
  assert.equal(clears, 2); assert.equal(calls, 0); assert.match(f.get('discovery-status').textContent, /32 KiB/);
});
test('refresh and clear are explicit; clears output and input, never recaptures', async () => {
  const calls = []; const f = ui({ windowsDiscoveryGet: async () => { calls.push('get'); return ok(envelope('TEST')); }, windowsDiscoveryClear: async () => { calls.push('clear'); return ok({ status: 'unavailable' }); } });
  await f.click('discovery-refresh'); assert.match(f.output(), /TEST/);
  f.get('discovery-capture').value = '{}'; await f.click('discovery-clear');
  assert.deepEqual(calls, ['get', 'clear']); assert.equal(f.output(), ''); assert.equal(f.get('discovery-capture').value, '');
});
test('busy serializes clicks and failure cannot leave old output visible', async () => {
  let resolve, calls = 0; const api = { windowsDiscoveryGet: () => { calls++; return new Promise(r => { resolve = r; }); }, windowsDiscoveryClear: () => { throw Error('must not run'); } };
  const f = ui(api); const pending = f.click('discovery-refresh');
  assert.equal(f.get('discovery-import').disabled, true); await f.click('discovery-clear'); assert.equal(calls, 1);
  resolve(ok(envelope('TEST'))); await pending; assert.match(f.output(), /TEST/);
  api.windowsDiscoveryGet = async () => ({ ok: false, error: 'TEST unavailable' }); await f.click('discovery-refresh');
  assert.equal(f.output(), ''); assert.match(f.get('discovery-status').textContent, /TEST unavailable/); assert.equal(f.controller.busy, false);
});
test('render treats text as text and does not promote timestamp, names or unvalidated fields', async () => {
  const value = envelope('<script>TEST</script>'); value.projection.fields.player_name = 'MUST NOT RENDER'; value.projection.fields.unused = '<img onerror=TEST>'; 
  const f = ui({ windowsDiscoveryGet: async () => ok(value) }); await f.click('discovery-refresh');
  assert.match(f.output(), /<script>TEST<\/script>/); assert.doesNotMatch(f.output(), /MUST NOT RENDER|onerror|2026-01-01/); assert.match(f.output(), /未验证 \/ 未知/);
});
test('settings panel mounts without automatic refresh and has no file picker', () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/settings.js'), 'utf8');
  assert.match(source, /CompanionDiscoverySettings\?\.mountDiscoverySettings\(\{ document, api \}\);/);
  const html = fs.readFileSync(path.join(__dirname, '../src/settings.html'), 'utf8');
  assert.match(html, /src="discovery-settings.js"/);
  const panel = html.split('id="discovery-title"')[1].split('</section>')[0];
  assert.doesNotMatch(panel, /type="file"/); assert.match(panel, /新鲜度始终未知/);
});
test('unknown identity/freshness/partial contract is mandatory, not inferred from imported_at', async () => {
  for (const patch of [{ page_identity_verified: true }, { source_freshness: 'current' }, { partial: false }, { entity_id: 'TEST-player' }, { captured_at: '2026-01-01' }, { status: 'available' }]) {
    const value = envelope('MUST NOT RENDER'); Object.assign(value.projection, patch);
    const f = ui({ windowsDiscoveryGet: async () => ok(value) }); await f.click('discovery-refresh');
    assert.equal(f.output(), ''); assert.match(f.get('discovery-status').textContent, /不符合/);
  }
});
test('request size includes JSON envelope bytes, not just pasted text', () => {
  const capture = JSON.stringify({ x: 'a'.repeat(32740) });
  assert.ok(capture.length + 2 <= 32768);
  assert.throws(() => parseInput(capture, '{}'), /请求 JSON/);
});

test('missing or malformed provenance never displays a position; each index must be <=511', async () => {
  for (const patch of [{ semantic_identity_verified: true }, { association: 'different_event' }, { panel_index: 1 }, { label_path: '0/6/512' }, { value_path: '<img onerror=TEST>' }, { container_path: '0/'.repeat(33) + '0' }, { label_path: '0/06/0' }]) {
    const value = envelope('MUST NOT RENDER'); Object.assign(value.projection.field_provenance.displayed_position, patch);
    const f = ui({ windowsDiscoveryGet: async () => ok(value) }); await f.click('discovery-refresh');
    assert.doesNotMatch(f.output(), /MUST NOT RENDER|onerror/); assert.match(f.output(), /没有完整/);
  }
  const value = envelope('MUST NOT RENDER'); delete value.projection.field_provenance;
  const f = ui({ windowsDiscoveryGet: async () => ok(value) }); await f.click('discovery-refresh');
  assert.doesNotMatch(f.output(), /MUST NOT RENDER/);
});

test('raw duplicates including escaped equivalents survive to strict backend parsing', () => {
  for (const text of ['{"pid":1,"pid":2}', '{"outer":{"pid":1,"pid":2}}', '{"p\\u0069d":1,"pid":2}']) {
    assert.equal(parseInput(text, '{}'), `{"capture":${text},"expected_source":{}}`);
    assert.equal(parseInput('{}', text), `{"capture":{},"expected_source":${text}}`);
  }
});
test('failed invalid-import cleanup warns old server snapshot may remain, never retries or posts', async () => {
  for (const failure of [async () => ({ ok: false, error: 'TEST failure' }), async () => { throw Error('TEST offline'); }]) {
    let clears = 0, posts = 0;
    const f = ui({ windowsDiscoveryImport: async () => { posts++; }, windowsDiscoveryClear: async () => { clears++; return failure(); } });
    f.get('discovery-capture').value = '{'; f.get('discovery-source').value = '{}';
    await f.click('discovery-import');
    assert.equal(clears, 1); assert.equal(posts, 0); assert.match(f.get('discovery-status').textContent, /先前的导入可能仍然存在/);
  }
});
