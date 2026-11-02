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
test('reported questions use calendar or scoped confirmation and never accept blank replies', async () => {
  const scope = {save_id:'session:test',character_id:'official.eckera'};
  const paths=[];
  const client=new RealReaderClient({request:async(endpoint,body)=>{
    paths.push(endpoint);
    if(endpoint.includes('auto-calendar')) return {status:'unavailable',reply:'候选赛程未读取完整',character_context:scope};
    return {status:'partial',source_status:'partial_native_candidates',reply:'请确认候选球队',character_context:scope,context:{}};
  }});
  for(const message of ['我们下一场打谁','你推荐谁给我们门将','你推荐我们选择哪个门将呢']) {
    const result=await client.reply({message,characterContext:scope,conversationId:'reported'});
    assert.ok(result.text.trim());
  }
  assert.deepEqual(paths,['/v1/agent/auto-calendar-advice','/v1/chat','/v1/chat']);
  const malformed=new RealReaderClient({request:async()=>({character_context:scope,reply:'  '})});
  await assert.rejects(malformed.reply({message:'我们下一场打谁',characterContext:scope}),/未返回可显示/);
  const wrong=new RealReaderClient({request:async()=>({status:'partial',source_status:'partial_native_candidates',reply:'wrong scope',context:{}})});
  await assert.rejects(wrong.reply({message:'你推荐谁给我们门将',characterContext:scope}),/范围不匹配/);
});
test('empty successful and rejected requests produce visible failure replies, not empty success',async()=>{
 const {CompanionRuntime}=require('../src/companion-runtime.cjs');
 for(const reply of [async()=>({text:'  ',metadata:{},cards:[]}),async()=>{throw Error('角色回复范围不匹配。');}]) {
  const client={reply,capabilities:()=>[]};const runtime=new CompanionRuntime({realClient:client});runtime.mode='real';
  const done=new Promise(resolve=>runtime.on('event',e=>{if(e.type==='request'&&['completed','error'].includes(e.status))resolve(e);}));
  runtime.sendMessage({text:'你推荐谁给我们门将'});
  assert.equal((await done).status,'error');
  const answer=runtime.state().messages.find(m=>m.role==='assistant');
  assert.match(answer.text,/这次请求未完成/);assert.equal(answer.metadata.source,'error');assert.equal(answer.cards.length,0);
  await runtime.close();
 }
});
