'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function harness(api) {
  const elements=[]; const make=tag=>{const e={tag,textContent:'',children:[],events:{},append(child){this.children.push(child);},setAttribute(){},addEventListener(name,fn){this.events[name]=fn;}};elements.push(e);return e;};
  const context={window:{},document:{createElement:make}};vm.runInNewContext(fs.readFileSync(require.resolve('../src/reader-onboarding-settings.js'),'utf8'),context);
  const root=make('section'),errors=[];const ui=context.window.FootballReaderOnboarding.bind({root,api,onError:e=>errors.push(e)});return {ui,root,errors,elements,button:text=>elements.find(e=>e.tag==='button'&&e.textContent===text)};
}
const ok=value=>({ok:true,value});
test('settings starts passive and only reads game after consent and explicit verify',async()=>{
  let verifies=0,saves=[];const h=harness({inspectReaderOnboarding:async()=>ok({supported:true,enabled:false,payloadReady:true,canEnable:true,state:'not_enabled'}),enableReader:async input=>{saves.push(input);return ok({supported:true,enabled:true,payloadReady:true,state:'configured'});},verifyReader:async()=>{verifies++;return ok({supported:true,enabled:true,state:'fresh_partial'});}});
  await h.ui.ready;assert.equal(verifies,0);assert.equal(h.button('启用读取').disabled,true);
  const consent=h.elements.find(e=>e.tag==='input');consent.checked=true;consent.events.change();assert.equal(h.button('启用读取').disabled,false);
  await h.button('启用读取').events.click();assert.equal(saves[0].readOnlyConsent,true);assert.equal(verifies,0);await h.button('检查连接').events.click();assert.equal(verifies,1);
  assert.ok(h.elements.some(e=>e.textContent==='已取得新鲜的部分游戏数据'));
});
test('disposed window rejects late replies and unavailable payload remains disableable',async()=>{
  let resolve;const h=harness({inspectReaderOnboarding:()=>new Promise(r=>{resolve=r;})});h.ui.dispose();resolve(ok({supported:true,state:'fresh_partial'}));await h.ui.ready;assert.equal(h.elements.some(e=>e.textContent==='已取得新鲜的部分游戏数据'),false);
  const active=harness({inspectReaderOnboarding:async()=>ok({supported:true,enabled:true,state:'payload_unavailable',canEnable:false})});await active.ui.ready;assert.equal(active.button('停用读取').disabled,false);
});
