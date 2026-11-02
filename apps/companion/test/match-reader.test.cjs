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
  const snapshot = { schema_version: 'fa-match-snapshot/0.1', producer: {id: 'footballassistant.match-reader', version: '0.1.0', protocol: 'fa-match-snapshot/0.1'}, process: {sessionId:'a'.repeat(64)}, instanceId:'b'.repeat(32), status: 'live', source: 'native_match_hook', synthetic: false, match_id: 'd'.repeat(32),
    captured_at: new Date(now).toISOString(), home_metadata: { Name: 'A' }, away_metadata: { Name: 'B' },
    home: { Goals: 0 }, away: { Goals: 0 }, period: 1, display_tick: 4 };
  const envelope = { status: 'experimental', reason: 'game_facts_not_verified', producerVerified: true, snapshot };
  const view = matchView(envelope, now);
  const tracker = new MatchChangeTracker();
  assert.equal(tracker.observe(view, true), null);
  assert.match(tracker.observe({ ...view, h: 1 }, true).text, /1 : 0/);
  assert.equal(tracker.observe({ ...view, h: 1 }, true), null);
  assert.equal(tracker.observe({ ...view, id: 'two', h: 2 }, true), null);
  assert.equal(matchView(envelope, now + 16000), null);
  assert.equal(matchView({...envelope, producerVerified:false}, now), null);
  assert.equal(tracker.observe({...view, sessionId:'c'.repeat(64), h:3}, true), null);
  assert.equal(matchView({ ...envelope, status: 'unavailable' }, now), null);
  assert.equal(tracker.observe(null, true), null);
  assert.equal(tracker.observe({ ...view, h: 3 }, true), null);
});

test('real score question consumes only verified-current match envelope; loading is not data', async () => {
  const { RealReaderClient } = require('../src/reader-clients.cjs');
  let envelope = {status:'unavailable', snapshot:null, readerStatus:{state:'hook_installed'}};
  const calls = [];
  const client = new RealReaderClient({request:async (url, body) => {calls.push([url,body]); return envelope;}});
  let result = await client.reply({message:'当前比分', conversationId:'fixture'});
  assert.equal(result.cards.length, 0);
  assert.match(result.text, /没有可用/);
  envelope = {status:'experimental', reason:'game_facts_not_verified', producerVerified:true,
    snapshot:{schema_version:'fa-match-snapshot/0.1', producer:{id:'footballassistant.match-reader',version:'0.1.0',protocol:'fa-match-snapshot/0.1'},
      process:{sessionId:'a'.repeat(64)},instanceId:'b'.repeat(32),match_id:'c'.repeat(32),status:'live',synthetic:false,source:'native_match_hook',
      captured_at:new Date().toISOString(),home_metadata:{Name:'Fixture A'},away_metadata:{Name:'Fixture B'},home:{Goals:1},away:{Goals:0},period:1}};
  result = await client.reply({message:'当前比分',conversationId:'fixture'});
  assert.equal(result.cards.length,1);
  assert.match(result.text,/Fixture A 1 : 0 Fixture B/);
  assert.ok(calls.every(([url,body]) => url === '/v1/reader/match' && body === undefined));
  envelope.producerVerified = false;
  result = await client.reply({message:'当前比分',conversationId:'fixture'});
  assert.equal(result.cards.length,0);
});
