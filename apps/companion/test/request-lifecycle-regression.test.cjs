'use strict';
// Offline adversarial transports only; no backend, game or model calls.
const test=require('node:test'),assert=require('node:assert/strict');
const {CompanionRuntime}=require('../src/companion-runtime.cjs');
const {RealReaderClient}=require('../src/reader-clients.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('cancel before request microtask prevents transport and late running event',async()=>{
 let calls=0;const events=[];
 const runtime=new CompanionRuntime({realClient:{capabilities:()=>[],reply:async()=>{calls++;return {text:'late',metadata:{},cards:[]};}}});
 runtime.mode='real';runtime.on('event',e=>events.push(e));
 const sent=runtime.sendMessage({text:'已取消的问题'});runtime.cancelRequest(sent.requestId);
 await tick();
 assert.equal(calls,0);assert.equal(events.some(e=>e.type==='tool'&&e.tool.status==='running'),false);
 await runtime.close();
});
test('aborted native read releases only its own pending slot even if transport resolves late',async()=>{
 const pending=[];const client=new RealReaderClient({request:(_url,_body,options)=>new Promise(resolve=>pending.push({resolve,signal:options.signal}))});
 const first=new AbortController();const p1=client.offseason({signal:first.signal});
 const aborted=assert.rejects(p1,{name:'AbortError'});first.abort();
 const p2=client.offseason({});
 await tick();assert.equal(pending.length,2);
 pending[0].resolve({old:true});await aborted;
 await assert.rejects(client.offseason({}),/正在进行/);
 pending[1].resolve({new:true});assert.deepEqual(await p2,{new:true});
});
