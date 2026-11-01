'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { adviceCapability, RealReaderClient } = require('../src/reader-clients.cjs');

test('managed team acceptance question routes to current UI advice, never ordinary chat', async () => {
  const messages = ['现在我在执掌哪支球队', '我现在执教哪支球队？', '我们管理的是哪个俱乐部？',
    '我在哪个球队当主教练', '我的球队叫什么名字', '我目前是哪支队的主教练？',
    'Which team am I managing?', 'What club do we coach?', 'What is my team?'];
  const calls = [];
  const client = new RealReaderClient({ request: async (endpoint, body) => {
    calls.push({ endpoint, body });
    return { status: 'blocked', reply: '你执教哪支队，我还没确认准。', reasons: ['managed_team_identity_unverified'] };
  } });
  for (const message of messages) {
    const capability = adviceCapability(message);
    assert.equal(capability, 'player_info');
    await client.reply({ message, capability, adviceMode: 'ui_evidence' });
  }
  assert.ok(calls.every(call => call.endpoint === '/v1/agent/ui-advice'));
  assert.equal(adviceCapability('我想知道瓜迪奥拉执教哪支球队'), null);
  assert.equal(adviceCapability('什么是战术'), null);
  assert.equal(adviceCapability('哪支球队适合我执教'), null);
  assert.equal(adviceCapability('Which team should I manage?'), null);
  assert.notEqual(adviceCapability('我执教球队该用哪种战术'), 'player_info');
  assert.equal(adviceCapability('分析我的战术'), 'tactical_analysis');
});
