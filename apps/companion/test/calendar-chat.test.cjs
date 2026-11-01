'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RealReaderClient } = require('../src/reader-clients.cjs');

test('explicit club and dates route to agent with partial context', async () => {
  const calls = [];
  const client = new RealReaderClient({ request: async (endpoint, body, options) => {
    calls.push({endpoint, body, options});
    return {status:'partial', reply:'基于部分候选', conversation_id:'c', context:{status:'partial', selected_club_uid:42, start:'2026-02-01', end:'2026-03-02', observed_at:'2026-02-01T00:00:00Z', unloaded:1, unknown:2}};
  } });
  const result = await client.reply({message:'请看俱乐部UID 42 的赛程，2026-02-01 至 2026-03-02',conversationId:'c',capability:'schedule_analysis'});
  assert.equal(calls.length,1); assert.equal(calls[0].endpoint,'/v1/agent/calendar-advice');
  assert.equal(calls[0].body.club_uid,42); assert.equal(calls[0].body.start,'2026-02-01');
  assert.equal(result.text,'基于部分候选'); assert.equal(result.metadata.partial,true);
  assert.equal(result.metadata.selectedClubUid,42); assert.match(result.metadata.limitations.join(' '),/不完整/);
});

test('invalid or ambiguous explicit selections never invoke the model', async () => {
  const client = new RealReaderClient({request: async () => {throw Error('unexpected request')}});
  for (const message of ['俱乐部UID 0 的赛程 2026-02-01 至 2026-02-02','俱乐部UID 42x 的赛程 2026-02-01 至 2026-02-02','俱乐部UID 42 的赛程 2026-02-01','俱乐部UID 42 的赛程 2026-02-01 至 2026-03-03','俱乐部UID 42 俱乐部UID 43 的赛程 2026-02-01 至 2026-02-02']) {
    const result = await client.reply({message}); assert.match(result.text,/请明确/); assert.equal(result.metadata.partial,true);
  }
});

test('ordinary chat and unspecified club retain previous routing', async () => {
  const calls = [];
  const client = new RealReaderClient({request: async (endpoint, body) => { calls.push(endpoint); if (endpoint === '/v1/chat') return {reply:'hello',conversation_id:'x'}; return {reply:'not ready',readiness:{production_ready:false,reasons:[]},missing_requirements:[]}; }});
  assert.equal((await client.reply({message:'你好'})).text,'hello');
  await client.reply({message:'我的赛程怎么样',capability:'schedule_analysis'});
  assert.deepEqual(calls,['/v1/chat','/v1/agent/business-advice']);
});

test('unavailable or mismatched result is never shown as calendar advice', async () => {
  for (const result of [{status:'unavailable',reply:'fake'}, {status:'partial',reply:'fake',context:{status:'partial',selected_club_uid:99,start:'2026-02-01',end:'2026-02-02'}}]) {
    const client = new RealReaderClient({request:async()=>result});
    const reply = await client.reply({message:'club UID 42 schedule 2026-02-01 to 2026-02-02'});
    assert.match(reply.text,/不可用/); assert.equal(reply.metadata.partial,true);
  }
});


test('natural upcoming fixtures asks server to resolve candidate and preserves partial', async () => {
  const calls = [];
  const client = new RealReaderClient({request:async (endpoint,body) => { calls.push({endpoint,body}); return {
    status:'partial', reply:'候选赛程可能不完整', selection:{club_uid:42,club_name:'示例球队',selection:'named_candidate',start:'2026-02-07',end:'2026-03-08'},
    context:{status:'partial',selected_club_uid:42,start:'2026-02-07',end:'2026-03-08',observed_at:'2026-02-07T00:00:00Z',unloaded:1,unknown:0} }; }});
  const reply = await client.reply({message:'示例球队接下来有哪些比赛',capability:'schedule_analysis'});
  assert.equal(calls[0].endpoint,'/v1/agent/auto-calendar-advice');
  assert.deepEqual(calls[0].body,{message:'示例球队接下来有哪些比赛',conversation_id:null});
  assert.equal(reply.metadata.partial,true); assert.match(reply.metadata.limitations.join(' '),/不完整/);
});

test('natural routing never fabricates unknown or mismatched club', async () => {
  for (const data of [{status:'unavailable',reply:'未确认球队候选'}, {status:'partial',reply:'fake',selection:{club_uid:42,selection:'named_candidate',start:'2026-02-01',end:'2026-02-10'},context:{status:'partial',selected_club_uid:43,start:'2026-02-01',end:'2026-02-10'}}]) {
    const client = new RealReaderClient({request:async()=>data});
    const reply = await client.reply({message:'示例球队接下来有哪些比赛'});
    assert.notEqual(reply.text,'fake'); assert.equal(reply.metadata.partial,true);
  }
});
