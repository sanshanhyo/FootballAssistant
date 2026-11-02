'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { offseasonEndpoint, isOffseasonEndpoint, offseasonIntent, offseasonReply } = require('../src/offseason-calendar.cjs');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const current = () => new Date().toISOString();
function fixture() {
  const observedAt = current();
  return { producerVerified:true, status:'partial', snapshot:{schema:'fa-offseason/0.1',status:'partial',synthetic:false,state:'fresh_partial',capturedAt:observedAt,
    producer:{id:'footballassistant.offseason-reader',version:'0.1.0',protocol:'fa-offseason/0.1'},
    process:{pid:123,startedAt:observedAt,sessionId:'a'.repeat(64)},binary:{module:'game_plugin.dll',matched:true,sha256:'bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f'},
    date:{status:'experimental',date:'2026-07-13',observedAt},
    managerCandidates:{status:'experimental_candidates_incomplete',candidates:[{uid:11,name:'Synthetic manager',clubUid:42,clubName:'Synthetic club'}]},
    player:{observedAt,value:{status:'experimental',uid:123,displayName:'Synthetic player',details:{reflexesRaw:60,handlingRaw:0,anticipationRaw:55,jumpingRaw:75,heightCm:180,dateOfBirth:'2000-02-29'},contract:{status:'experimental',startDate:'2026-01-01',endDate:'2027-01-01',wageRaw:999}}},
    team:{status:'experimental_candidates_incomplete',observedAt,players:[{uid:123,name:'Synthetic player',clubUid:42,teamUid:41,linkStatus:'exact_types'}]}}};
}
test('canonical bounded selectors never allow arbitrary paths, repeated or extra query fields',()=>{
  assert.equal(offseasonEndpoint(),'/v1/reader/offseason?club_uid=0&person_uid=0');
  assert.equal(isOffseasonEndpoint(offseasonEndpoint(42,123)),true);
  for(const args of [[-1,0],[0,-1],[4294967295,0],[0,2147483648],[NaN,0],['42',0]]) assert.throws(()=>offseasonEndpoint(...args));
  for(const endpoint of ['/v1/reader/offseason','/v1/reader/offseason?club_uid=042&person_uid=0',offseasonEndpoint()+'&x=1',offseasonEndpoint()+'#x',offseasonEndpoint()+'&person_uid=1']) assert.equal(isOffseasonEndpoint(endpoint),false);
});
test('intent asks for UID rather than resolving names or inferring managed-team identity',()=>{
  assert.deepEqual(offseasonIntent('读取球员 UID: 123 的属性'),{personUid:123,clubUid:0,kind:'player'});
  assert.equal(offseasonIntent('看看我的球队').clubUid,0);
  assert.equal(offseasonIntent('当前游戏日期').kind,'date');
  for(const q of ['球员 UID -1','球员 UID 0','球员 UID 2147483648','球员 UID 1 UID','球员 UID 1 球员 UID 2','球员 UID 12abc','球员 UID 1.2','查看张三的属性']) {
    assert.ok(offseasonIntent(q)?.error,q);
  }
  assert.equal(offseasonIntent('什么是战术'),null); assert.equal(offseasonIntent('俱乐部 UID 42 的赛程'),null);
});
test('explicit real queries fetch native readback only, no model POST and no UI fallback',async()=>{
  const calls=[], client=new RealReaderClient({request:async(url,body,options)=>{calls.push({url,body,options});return fixture();}});
  const got=await client.reply({message:'读取球员 UID:123',conversationId:'conversation'});
  assert.equal(calls[0].url,offseasonEndpoint(0,123));assert.equal(calls[0].body,undefined);assert.equal(calls[0].options.timeoutMs,45000);
  assert.match(got.text,/部分实验/);assert.equal(got.cards.length,1);
  assert.equal(got.cards[0].fields.find(x=>x.label==='手控球').value,null);
  assert.equal(JSON.stringify(got).includes('999'),false);
  const before=calls.length;const missing=await client.reply({message:'查看张三的属性'});assert.match(missing.text,/UID/);assert.equal(calls.length,before);
});
test('fresh date and candidate responses retain experimental/partial limits',()=>{
  const date=offseasonReply(fixture(),{kind:'date'},'c');assert.match(date.text,/2026-07-13/);
  const candidates=offseasonReply(fixture(),{kind:'team',clubUid:42},'c');assert.match(candidates.text,/不代表/);assert.equal(candidates.cards[0].fields.length,2);
  const empty=fixture();empty.snapshot.managerCandidates.candidates=[];empty.snapshot.team.players=[];
  assert.equal(offseasonReply(empty,{kind:'team',clubUid:42},'c').cards.length,0);
});
test('stale/unknown/synthetic/wrong producer and wrong player identity fail closed',()=>{
  const mutations=[e=>e.producerVerified=false,e=>e.snapshot.synthetic=true,e=>e.snapshot.capturedAt='2000-01-01T00:00:00Z',e=>e.snapshot.process=null,e=>e.snapshot.binary.matched=false,e=>e.snapshot.producer.protocol=1,e=>e.snapshot.player.value.uid=999,e=>e.snapshot.player.observedAt='2000-01-01T00:00:00Z'];
  for(const mutate of mutations){const e=fixture();mutate(e);assert.deepEqual(offseasonReply(e,{kind:'player',personUid:123},'c').cards,[]);}
});
test('read concurrency is bounded and explicit verify is distinct from passive onboarding status',async()=>{
  let finish;const calls=[];const client=new RealReaderClient({request:(url,_body,options)=>{calls.push({url,options});return new Promise(resolve=>finish=resolve);}});
  const first=client.offseason();await assert.rejects(client.offseason(),/正在进行/);await assert.rejects(client.onboardingStatus({verify:true}),/正在进行/);
  finish({status:'unavailable'});await first;
  const verify=client.onboardingStatus({verify:true});assert.equal(calls.at(-1).url,'/v1/reader/onboarding-status?verify=true');finish({});await verify;
  const passive=client.onboardingStatus();assert.equal(calls.at(-1).url,'/v1/reader/onboarding-status');finish({});await passive;
});
test('transport accepts only fixed new read/verify routes, enforces GET and auth, forwards abort',async t=>{
  const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
  const {request}=require('../src/backend.cjs');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'offseason-transport-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const file=path.join(dir,'runtime.json');await fs.writeFile(file,JSON.stringify({base_url:'http://127.0.0.1:1234',token:'synthetic-test-secret'}));
  const calls=[],fetch=async(url,options)=>{calls.push({url,options});return{ok:true,status:200,text:async()=>JSON.stringify({status:'unavailable'})};};
  for(const endpoint of [offseasonEndpoint(),'/v1/reader/onboarding-status','/v1/reader/onboarding-status?verify=true']) await request(file,endpoint,undefined,{fetch});
  assert.ok(calls.every(call=>call.options.method==='GET' && call.options.headers.Authorization==='Bearer synthetic-test-secret'));
  for(const endpoint of [offseasonEndpoint()+'&person_uid=1',offseasonEndpoint()+'#fragment','/v1/reader/onboarding-status?verify=false','/v1/reader/onboarding-status?verify=true&path=anything']) await assert.rejects(request(file,endpoint,undefined,{fetch}),/请求方法/);
  await assert.rejects(request(file,offseasonEndpoint(),{}, {fetch}),/请求方法/);
  await assert.rejects(request(file,offseasonEndpoint(),undefined,{fetch,method:'DELETE'}),/请求方法/);
  const controller=new AbortController();controller.abort();await assert.rejects(request(file,offseasonEndpoint(),undefined,{fetch,signal:controller.signal}),{name:'AbortError'});
  assert.equal(calls.length,3);
});
