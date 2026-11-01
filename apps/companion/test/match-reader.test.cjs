'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { matchView, displayAttribute, MatchChangeTracker } = require('../src/match-reader.cjs');

test('attribute conversion preserves raw values and rejects unknown reads', () => {
  assert.deepEqual([60, 55, 55, 75].map(displayAttribute), [
    { raw: 60, display: 12 }, { raw: 55, display: 11 },
    { raw: 55, display: 11 }, { raw: 75, display: 15 },
  ]);
  assert.deepEqual(displayAttribute(13), { raw: 13, display: 3 });
  assert.deepEqual(displayAttribute(0), { raw: 0, display: null });
  assert.equal(displayAttribute(101).display, null);
  assert.equal(displayAttribute(null).display, null);
});

test('fresh match score changes notify once, stale and new sessions do not', () => {
  const now = Date.now();
  const snapshot = { status: 'live', source: 'native_match_hook', synthetic: false, match_id: 'one',
    captured_at: new Date(now).toISOString(), home_metadata: { Name: 'A' }, away_metadata: { Name: 'B' },
    home: { Goals: 0 }, away: { Goals: 0 }, period: 1, display_tick: 4 };
  const envelope = { status: 'experimental', reason: 'native_producer_not_verified', snapshot };
  const view = matchView(envelope, now);
  const tracker = new MatchChangeTracker();
  assert.equal(tracker.observe(view, true), null);
  assert.match(tracker.observe({ ...view, h: 1 }, true).text, /1 : 0/);
  assert.equal(tracker.observe({ ...view, h: 1 }, true), null);
  assert.equal(tracker.observe({ ...view, id: 'two', h: 2 }, true), null);
  assert.equal(matchView(envelope, now + 16000), null);
  assert.equal(matchView({ ...envelope, status: 'unavailable' }, now), null);
  assert.equal(tracker.observe(null, true), null);
  assert.equal(tracker.observe({ ...view, h: 3 }, true), null);
});
