'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { sources, discussionScene, selectScene, sourceFor } = require('../src/character-scene.js');
const user = (text, extra = {}) => ({ role: 'user', text, sessionId: 's', epoch: 1, ...extra });
const select = (messages, game = { state: 'running' }) => selectScene({ messages, game, sessionId: 's', epoch: 1 });

test('only an explicit successful negative process observation selects no-game', () => {
  assert.equal(select([], { state: 'not_detected' }), 'no-game');
  for (const game of [undefined, null, {}, { state: 'unknown' }, { state: 'unsupported' }, { state: 'running' }, { state: 'disconnected' }]) assert.equal(select([], game), 'default');
  assert.equal(select([user('转会')], { state: 'not_detected' }), 'no-game');
  assert.equal(select([user('转会')], { state: 'running' }), 'transfer');
  assert.equal(select([], { state: 'unknown' }), 'default');
});

test('capabilities and current discussion select static illustrations, ordinary chat resets', () => {
  for (const [capability, scene] of [['transfer_analysis', 'transfer'], ['tactical_analysis', 'tactics'], ['player_info', 'research']]) assert.equal(discussionScene('', capability), scene);
  for (const [text, scene] of [['聊聊转会', 'transfer'], ['transfer plans', 'transfer'], ['战术怎么选', 'tactics'], ['player research', 'research'], ['球员属性', 'research'], ['你好', 'default']]) assert.equal(select([user(text)]), scene);
  assert.equal(select([user('我的战术'), user('你好')]), 'default');
  assert.equal(discussionScene('战术', 'schedule_analysis'), 'default');
});

test('old sessions and assistant/proactive text cannot change current discussion', () => {
  assert.equal(select([user('战术', { sessionId: 'old' })]), 'default');
  assert.equal(select([user('战术', { epoch: 0 })]), 'default');
  assert.equal(select([user('你好'), user('转会成功了', { role: 'assistant' })]), 'default');
  assert.equal(select([user('调研', { metadata: { capability: 'player_info' } })]), 'research');
});

test('failed or unrecognized scene falls back to the existing default without arbitrary paths', () => {
  assert.equal(sourceFor('tactics', new Set(['tactics'])), sources.default);
  for (const value of ['../../secret', 'https://evil', 'constructor', null]) assert.equal(sourceFor(value), sources.default);
  assert.equal(sourceFor('transfer'), sources.transfer);
});

test('four packaged PNGs are unmodified static sources with matching dimensions', () => {
  let dimensions;
  for (const scene of ['no-game', 'transfer', 'tactics', 'research']) {
    const bytes = fs.readFileSync(path.resolve(__dirname, '../src', sources[scene]));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    const size = [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
    if (dimensions) assert.deepEqual(size, dimensions); else dimensions = size;
    assert.equal(bytes.includes(Buffer.from('acTL')), false, 'not an animated PNG');
  }
});
