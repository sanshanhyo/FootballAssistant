'use strict';
// Synthetic current-capture fixtures only; no game or model/provider traffic.
const test = require('node:test');
const assert = require('node:assert/strict');
const { UiChangeTracker } = require('../src/ui-changes.cjs');

function trackerFixture(kind = 'tactics', cooldownMs = 60_000) {
  let now = Date.parse('2026-10-31T09:00:00Z'); let event = 0;
  const tracker = new UiChangeTracker({ now: () => now, cooldownMs });
  const sample = (hash = 'a', patch = {}) => {
    now += 3000; event++;
    return { status: 'ready', kind, source: 'ui', synthetic: false, partial: true, production_ready: false,
      session_id: 'TEST-game-session', event_id: `TEST-event-${event}`, captured_at: new Date(now).toISOString(),
      display_sha256: hash.repeat(64), scope_sha256: 'd'.repeat(64), ...patch };
  };
  const observe = (hash, patch, options) => tracker.observe(sample(hash, patch), options);
  const baseline = (hash = 'a', patch = {}) => { assert.equal(observe(hash, patch), null); assert.equal(observe(hash, patch), null); };
  return { tracker, sample, observe, baseline, advance: ms => { now += ms; }, time: () => now };
}

test('stable display changes require two fresh distinct captures, never model or game-event claims', () => {
  for (const kind of ['schedule', 'tactics', 'current_page_attributes']) {
    const f = trackerFixture(kind); f.baseline();
    assert.equal(f.observe('b'), null);
    const notice = f.observe('b');
    assert.ok(notice && typeof notice.text === 'string');
    assert.deepEqual(notice.cards, []);
    assert.match(notice.text, /显示|UI|采样/);
    if (kind === 'current_page_attributes') {
      assert.match(notice.text, /当前显示的属性数据已更新/);
      assert.match(notice.text, /身份.*未知|身份.*未|未.*身份/);
      assert.doesNotMatch(notice.text, /球员能力变化|能力提升|能力下降/);
    }
    assert.equal(f.observe('b'), null);
    assert.equal(f.observe('b'), null);
  }
});

test('repeated events and repeated timestamps cannot provide the second confirmation', () => {
  const f = trackerFixture(); f.baseline();
  const first = f.sample('b'); assert.equal(f.tracker.observe(first), null);
  assert.equal(f.tracker.observe(first), null);
  assert.equal(f.tracker.observe({ ...first, event_id: 'TEST-other-event-same-time' }), null);
  assert.ok(f.observe('b'));
});

test('initial reading and context changes establish a baseline without a game-event notice', () => {
  for (const patch of [
    { kind: 'schedule' }, { scope_sha256: 'e'.repeat(64) }, { session_id: 'TEST-new-game-session' },
  ]) {
    const f = trackerFixture(); f.baseline();
    assert.equal(f.observe('b', patch), null);
    assert.equal(f.observe('b', patch), null);
    assert.equal(f.observe('b', patch), null);
  }
});

test('unavailable, stale, synthetic and malformed evidence clears comparison instead of guessing', () => {
  const invalid = [
    { status: 'unavailable' }, { source: 'save' }, { synthetic: true }, { production_ready: true },
    { partial: false }, { kind: 'injury' }, { display_sha256: 'bad' }, { scope_sha256: 'bad' },
    { session_id: '' }, { event_id: '' }, { captured_at: 'invalid' },
    { captured_at: '2000-01-01T00:00:00Z' }, { captured_at: '2099-01-01T00:00:00Z' },
  ];
  for (const patch of invalid) {
    const f = trackerFixture(); f.baseline(); assert.equal(f.observe('b'), null);
    assert.equal(f.observe('b', patch), null);
    assert.equal(f.observe('b'), null);
    assert.equal(f.observe('b'), null);
  }
});

test('cooldown suppresses changes without queuing a delayed stale alert', () => {
  const f = trackerFixture(); f.baseline(); f.observe('b'); assert.ok(f.observe('b'));
  assert.equal(f.observe('c'), null); assert.equal(f.observe('c'), null);
  for (let i = 0; i < 21; i++) assert.equal(f.observe('c'), null);
  assert.equal(f.observe('c'), null); assert.equal(f.observe('c'), null);
  assert.equal(f.observe('f'), null); assert.ok(f.observe('f'));
});

test('previously observed fingerprints do not repeat after cooldown or a display oscillation', () => {
  const f = trackerFixture(); f.baseline(); f.observe('b'); assert.ok(f.observe('b'));
  for (let i = 0; i < 21; i++) assert.equal(f.observe('b'), null);
  assert.equal(f.observe('a'), null); assert.equal(f.observe('a'), null);
  for (let i = 0; i < 21; i++) assert.equal(f.observe('a'), null);
  assert.equal(f.observe('b'), null); assert.equal(f.observe('b'), null);
});

test('muting or explicit reset discards candidate and requires a new stable baseline', () => {
  for (const action of ['mute', 'reset']) {
    const f = trackerFixture(); f.baseline(); f.observe('b');
    if (action === 'mute') assert.equal(f.observe('b', {}, { enabled: false }), null);
    else f.tracker.reset();
    assert.equal(f.observe('b'), null); assert.equal(f.observe('b'), null);
  }
});

test('local notice never echoes raw payload, identities or arbitrary strings', () => {
  const f = trackerFixture('current_page_attributes'); f.baseline();
  const poison = { raw_texts: 'TEST SECRET', display: 'TEST SECRET', player_name: 'TEST SECRET',
    field_provenance: { ui_path: 'TEST SECRET' }, reply: 'TEST SECRET' };
  f.observe('b', poison); const notice = f.observe('b', poison);
  assert.ok(notice); assert.equal(JSON.stringify(notice).includes('TEST SECRET'), false);
});


test('unobserved freshness gaps rebuild baseline instead of reporting a historical change', () => {
  const f = trackerFixture(); f.baseline();
  f.advance(16_000);
  assert.equal(f.observe('b'), null); assert.equal(f.observe('b'), null);
});

test('late old-session captures cannot undo a newer context or complete its candidate', () => {
  const f = trackerFixture(); f.baseline();
  const old = f.sample('b');
  f.baseline('c', { session_id: 'TEST-new-session' });
  assert.equal(f.tracker.observe(old), null);
  assert.equal(f.observe('f', { session_id: 'TEST-new-session' }), null);
  assert.ok(f.observe('f', { session_id: 'TEST-new-session' }));
});

test('duplicate suppression retains only a bounded recent fingerprint history', () => {
  const f = trackerFixture('tactics', 0); f.baseline();
  for (let i = 1; i <= 40; i++) {
    const patch = { display_sha256: i.toString(16).padStart(64, '0') };
    assert.equal(f.observe('a', patch), null); assert.ok(f.observe('a', patch));
  }
  assert.ok(f.tracker.seen.length <= 32);
});
