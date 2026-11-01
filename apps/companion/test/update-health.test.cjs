'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm');
const { rendererHealthy, rendererHealthScript } = require('../src/update-health.cjs');
test('update health requires a real successful IPC roundtrip, not just a preload object', async()=>{
  for (const [reply,expected] of [[{ok:true,value:{sessionId:'fixture',epoch:1}},true],[{ok:false,error:'denied'},false],[{ok:true,value:{}},false]]) {
    let calls=0;
    const context={document:{readyState:'complete',getElementById:()=>({})},window:{companion:{getState:async()=>{calls++;return reply;}}}};
    assert.equal(await rendererHealthy({executeJavaScript:script=>vm.runInNewContext(script,context)}),expected);
    assert.equal(calls,1);
  }
});
test('renderer failure or hung IPC cannot acknowledge healthy or hang startup',async()=>{
  assert.equal(await rendererHealthy({executeJavaScript:()=>Promise.reject(Error('renderer gone'))}),false);
  assert.equal(await rendererHealthy({executeJavaScript:()=>new Promise(()=>{})},5),false);
  assert.equal(await vm.runInNewContext(rendererHealthScript,{document:{readyState:'complete',getElementById:()=>({})},window:{companion:{}}}),false);
});
