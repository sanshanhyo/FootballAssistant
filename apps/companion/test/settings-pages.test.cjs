'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/settings.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../src/settings.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../src/settings.css'), 'utf8');
class Element {
  constructor(tag='div') { this.tagName=tag.toUpperCase(); this.children=[]; this.value=''; this.textContent=''; this.disabled=false; this.hidden=false; this.checked=false; this.dataset={}; this.listeners={}; this.attributes={}; this.classList={toggle(){}}; this.style={setProperty(){}}; }
  append(...nodes) {this.children.push(...nodes);if(this.tagName==='SELECT' && !this.value && nodes[0])this.value=nodes[0].value;}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  get options(){return this.children;}
  get firstChild(){return this.children[0];}
  setAttribute(k,v){this.attributes[k]=v;}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,fn){(this.listeners[k] ||= []).push(fn);}
  async fire(k){for(const fn of this.listeners[k]||[])await fn({preventDefault(){}});}
  focus(){}
}
const flush=()=>new Promise(r=>setImmediate(r));
async function harness(overrides={}) {
  const elements=new Map();
  for(const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {const e=new Element(match[1]);e.id=match[2];e.hidden=/\bhidden\b/.test(match[0]);e.disabled=/\bdisabled\b/.test(match[0]);elements.set(e.id,e);}
  const nav=[...html.matchAll(/data-page="([^"]+)"/g)].map(m=>{const e=new Element('button');e.dataset.page=m[1];return e;});
  const pages=[...elements.values()].filter(e=>e.id.startsWith('page-') && e.id!=='page-title');
  const document={getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),documentElement:new Element('html'),querySelectorAll:s=>s==='[data-page]'?nav:s==='.settings-page'?pages:[]};
  const calls=[];let listener;let config={provider:'openai',baseUrl:'https://api.openai.com/v1',model:'one',hasApiKey:true,storage:'encrypted'};
  const state={epoch:1,sessionId:'test',mode:'real',synthetic:false,connection:{state:'unavailable'},preferences:{sttProvider:'local-whisper'},historyEnabled:true,proactivity:80,character:{displayName:'埃克拉',visual:{kind:'builtin-image'}}};
  const ok=value=>Promise.resolve({ok:true,value});
  const api={getState:()=>ok(state),subscribe:fn=>{listener=fn;return()=>{};},getModelProviders:()=>ok({providers:[{id:'openai',name:'OpenAI',baseUrl:'https://api.openai.com/v1'},{id:'deepseek',name:'DeepSeek',baseUrl:'https://api.deepseek.com'},{id:'openai-compatible',name:'Custom',custom:true}]}),getModelConfig:()=>ok(config),listModels:input=>{calls.push({list:input});return ok({models:[{id:'one',name:'One'},{id:'two',name:'Two'}]});},cancelModelList:()=>ok({}),saveModelConfig:input=>{calls.push({save:{...input}});config={...input,hasApiKey:true,storage:'encrypted'};return ok(config);},speechCapabilities:()=>ok({stt:[{id:'local-whisper',label:'Local',available:true},{id:'openai',label:'Cloud',available:false},{id:'mock',synthetic:true,available:true}]}),setPreferences:patch=>{state.preferences={...state.preferences,...patch};return ok(state);},setProactivity:n=>{state.proactivity=n;return ok(state);},updateStatus:()=>ok({currentVersion:'0.0.1',state:'idle'}),getCharacterIntroduction:()=>ok({content:'角色介绍正文'}),getAbout:()=>ok({version:'0.0.1'}),getPersona:()=>ok({content:'# Original',revision:'r1',status:'ready',canEdit:true,canOpen:true}),savePersona:input=>{calls.push({persona:input});return ok({...input,revision:'r2',status:'ready',canEdit:true,canOpen:true});},getHistory:()=>ok({enabled:true,messages:[]}),getMemories:()=>ok({entries:[]}),checkUpdate:()=>ok({currentVersion:'0.0.1',state:'network_error'}),...overrides};
  const storage=new Map(),events={};
  const window={CompanionAppearance:require('../src/appearance.js'),companion:api,CompanionUI:{EXPRESSIONS:{auto:'跟随交互',happy:'开心'},timestampLabel:()=>'',observationLabels:()=>[],belongsToSession:()=>true,valueLabel:field=>field.value},addEventListener:(k,fn)=>events[k]=fn,scrollTo(){},confirm:()=>true};
  const context={document,window,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},setTimeout:()=>0,clearTimeout(){},console};
  vm.runInNewContext(source,context);await flush();await flush();
  return {$:id=>elements.get(id),nav,calls,state,storage,document,api,event:value=>listener(value)};
}

test('saved key is visibly masked on opening and saving an untouched blank input never submits the mask', async()=>{
 const h=await harness();
 assert.equal(h.$('model-api-key').placeholder,'••••••••');assert.equal(h.$('model-api-key').value,'');
 assert.equal(h.$('model-storage-note').textContent,'密钥已配置');
 await h.$('model-fetch').fire('click');await h.$('model-config-form').fire('submit');await flush();
 assert.equal(Object.hasOwn(h.calls.find(c=>c.save).save,'apiKey'),false);
 assert.equal(Object.hasOwn(h.calls.find(c=>c.list).list,'apiKey'),false);
 assert.equal(h.$('model-api-key').placeholder,'••••••••');
 const reopened=await harness();assert.equal(reopened.$('model-api-key').placeholder,'••••••••');
});

test('provider and custom destination changes do not display or delete another destination key', async()=>{
 const h=await harness();h.$('model-provider').value='deepseek';await h.$('model-provider').fire('change');
 assert.equal(h.$('model-api-key').placeholder,'输入 API Key');assert.equal(h.$('model-remove-key').disabled,true);
 await h.$('model-remove-key').fire('click');assert.equal(h.calls.some(c=>c.save),false);
 h.$('model-provider').value='openai';await h.$('model-provider').fire('change');
 assert.equal(h.$('model-api-key').placeholder,'••••••••');assert.equal(h.$('model-remove-key').disabled,false);
});

test('failed key replacement retains draft, old saved state and a retry; unrelated state updates do not erase it',async()=>{
 const h=await harness({saveModelConfig:()=>Promise.resolve({ok:false,error:'保存失败'})});
 h.$('model-api-key').value='TEST-replacement';await h.$('model-api-key').fire('input');await h.$('model-fetch').fire('click');
 await h.$('model-config-form').fire('submit');await flush();
 assert.equal(h.$('model-api-key').value,'TEST-replacement');assert.equal(h.$('model-save').disabled,false);
 assert.equal(h.$('model-storage-note').textContent,'新密钥待保存');
 h.event({type:'state',state:{...h.state,preferences:{expression:'happy'}}});
 assert.equal(h.$('model-api-key').value,'TEST-replacement');assert.equal(h.$('error').textContent,'保存失败');
});

test('duplicate in-flight saves are blocked and successful response does not erase a newer key draft',async()=>{
 let resolve,count=0;const h=await harness({saveModelConfig:()=>{count++;return new Promise(r=>resolve=r);}});
 h.$('model-api-key').value='TEST-first';await h.$('model-api-key').fire('input');await h.$('model-fetch').fire('click');
 await h.$('model-config-form').fire('submit');await h.$('model-config-form').fire('submit');assert.equal(count,1);
 h.$('model-api-key').value='TEST-newer';await h.$('model-api-key').fire('input');
 resolve({ok:true,value:{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'one',hasApiKey:true,storage:'encrypted'}});await flush();
 assert.equal(h.$('model-api-key').value,'TEST-newer');assert.equal(h.$('model-storage-note').textContent,'新密钥待保存');
});

test('late initial configuration read does not replace a provider or key the user already edited',async()=>{
 let resolve;const h=await harness({getModelConfig:()=>new Promise(r=>resolve=r)});
 h.$('model-provider').value='deepseek';await h.$('model-provider').fire('change');
 h.$('model-api-key').value='TEST-draft';await h.$('model-api-key').fire('input');
 resolve({ok:true,value:{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'one',hasApiKey:true,storage:'encrypted'}});await flush();
 assert.equal(h.$('model-provider').value,'deepseek');assert.equal(h.$('model-api-key').value,'TEST-draft');
 assert.equal(h.$('model-api-key').placeholder,'输入 API Key');
});

test('explicit removal never submits a typed replacement and clears configured mask only on success',async()=>{
 let received;const h=await harness({saveModelConfig:input=>{received={...input};return Promise.resolve({ok:true,value:{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'one',hasApiKey:false,storage:'none'}});}});
 h.$('model-api-key').value='TEST-not-to-save';await h.$('model-api-key').fire('input');
 await h.$('model-remove-key').fire('click');await flush();
 assert.equal(received.removeKey,true);assert.equal(Object.hasOwn(received,'apiKey'),false);
 assert.equal(h.$('model-api-key').value,'');assert.equal(h.$('model-api-key').placeholder,'输入 API Key');
 assert.equal(h.$('model-storage-note').textContent,'未配置密钥');
});
test('six navigation pages expose Alpha 0.0.2 character library; diagnostic DOM removed',()=>{
  assert.equal((html.match(/class="settings-page"/g)||[]).length,6);
  assert.equal((html.match(/data-page="/g)||[]).length,6);
  assert.match(html,/data-page="companion"/);
  assert.match(html,/id="page-companion"[^>]+hidden>/);
  assert.match(html,/id="character-library"/);
  for(const forbidden of ['COMPANION','sidebar-footer','class="brand"','class="muted"','<small>','Windows 手动诊断导入','bridge-setup-card','模拟数据演示','page-description','discovery-settings.js','bridge-settings.js'])assert.ok(!html.includes(forbidden),forbidden);
  assert.match(html,/<select id="model-name"/);assert.doesNotMatch(html,/<input id="model-name"/);
  assert.match(css,/\.about-nav\{margin-top:auto\}/);
});

test('Alpha 0.0.2 opens character library while retaining legacy persona data and memory pages',async()=>{
 for(const id of ['character-library','tts-settings','persona-content','history-list','memory-list']) assert.ok(html.includes(`id="${id}"`));
 const h=await harness();assert.equal(h.nav.some(x=>x.dataset.page==='companion'),true);
 assert.equal(h.$('page-companion').hidden,true);
 await h.nav.find(x=>x.dataset.page==='companion').fire('click');
 assert.equal(h.$('page-connection').hidden,true);assert.equal(h.$('page-companion').hidden,false);
 assert.equal(h.$('page-title').textContent,'角色库');
});
test('unavailable backend remains visibly disconnected and unknown never becomes healthy',async()=>{const h=await harness();assert.equal(h.$('connection-status').textContent,'后台未连接');h.event({type:'state',state:{...h.state,connection:{state:'pending'}}});assert.equal(h.$('connection-status').textContent,'连接未确认');});
test('preset URL hidden, custom URL shown, provider changes clear draft key and model list',async()=>{const h=await harness();assert.equal(h.$('custom-url-row').hidden,true);h.$('model-api-key').value='secret';h.$('model-provider').value='openai-compatible';await h.$('model-provider').fire('change');assert.equal(h.$('custom-url-row').hidden,false);assert.equal(h.$('model-api-key').value,'');assert.equal(h.$('model-save').disabled,true);});
test('fetched model choices are required; edits invalidate and cancellation cannot render stale models',async()=>{let resolve;const h=await harness({listModels:()=>new Promise(r=>resolve=r)});const request=h.$('model-fetch').fire('click');h.$('model-api-key').value='changed';await h.$('model-api-key').fire('input');resolve({ok:true,value:{models:[{id:'stale'}]}});await request;assert.equal(h.$('model-save').disabled,true);assert.equal(h.$('model-name').options.some(o=>o.value==='stale'),false);});
test('successful provider model fetch unlocks save and submits exact choice',async()=>{const h=await harness();await h.$('model-fetch').fire('click');assert.equal(h.$('model-save').disabled,false);h.$('model-name').value='two';await h.$('model-config-form').fire('submit');await flush();assert.equal(h.calls.find(c=>c.save).save.model,'two');assert.equal(h.$('notice').textContent,'已保存');});
test('model fetch failures are visible and never enable save',async()=>{const h=await harness({listModels:()=>Promise.resolve({ok:false,error:'认证失败'})});await h.$('model-fetch').fire('click');assert.equal(h.$('error').textContent,'认证失败');assert.equal(h.$('model-save').disabled,true);});
test('speech list excludes mock and selected unavailable service remains truthful',async()=>{const h=await harness();assert.equal(h.$('stt-provider').options.some(o=>o.value==='mock'),false);h.$('stt-provider').value='openai';await h.$('stt-provider').fire('change');assert.equal(h.$('stt-note').textContent,'未就绪');});
test('persona editor sends revision and retains edited content on conflict',async()=>{const h=await harness({savePersona:()=>Promise.resolve({ok:false,error:'文件已修改'})});await h.$('persona-refresh').fire('click');assert.equal(h.$('persona-content').value,'# Original');h.$('persona-content').value='# User edit';await h.$('persona-content').fire('input');await h.$('persona-save').fire('click');assert.equal(h.$('persona-content').value,'# User edit');assert.equal(h.$('error').textContent,'文件已修改');assert.equal(h.$('persona-status').textContent,'未保存');});
test('persona save uses loaded revision',async()=>{const h=await harness();await h.$('persona-refresh').fire('click');h.$('persona-content').value='# New';await h.$('persona-content').fire('input');await h.$('persona-save').fire('click');assert.equal(h.calls.find(c=>c.persona).persona.revision,'r1');assert.equal(h.$('persona-status').textContent,'已读取');});
test('appearance controls persist and apply font, size and theme',async()=>{const h=await harness();h.$('font-family').value='serif';h.$('font-size').value='18';h.$('dark-mode').checked=false;await h.$('dark-mode').fire('change');const saved=JSON.parse(h.storage.get('football-assistant.appearance.v1'));assert.equal(saved.fontFamily,'serif');assert.equal(saved.fontSize,18);assert.equal(h.document.documentElement.dataset.theme,'light');});

test('light motion switch persists without replacing the default handwritten bubble font',async()=>{
  const h=await harness();h.$('light-motion').checked=false;await h.$('light-motion').fire('change');
  assert.deepEqual(JSON.parse(h.storage.get('football-assistant.appearance.v1')),{lightMotion:false});
  h.$('light-motion').checked=true;await h.$('light-motion').fire('change');
  assert.deepEqual(JSON.parse(h.storage.get('football-assistant.appearance.v1')),{lightMotion:true});
});
test('about check-update network failure is not reported as up to date',async()=>{const h=await harness();await h.$('update-check').fire('click');assert.equal(h.$('update-status').textContent,'连接失败');});
test('persona refresh discards confirmed stale draft, but never overwrites newer typing',async()=>{const h=await harness();await h.$('persona-refresh').fire('click');h.$('persona-content').value='# Draft';await h.$('persona-content').fire('input');await h.$('persona-refresh').fire('click');assert.equal(h.$('persona-content').value,'# Original');let resolve;h.api.getPersona=()=>new Promise(r=>resolve=r);const request=h.$('persona-refresh').fire('click');h.$('persona-content').value='# Typed during request';await h.$('persona-content').fire('input');resolve({ok:true,value:{content:'# Server',revision:'r3',canEdit:true,canOpen:true,status:'ready'}});await request;assert.equal(h.$('persona-content').value,'# Typed during request');});
test('late save response preserves a newer provider/key draft',async()=>{let resolve;const h=await harness({saveModelConfig:()=>new Promise(r=>resolve=r)});await h.$('model-fetch').fire('click');await h.$('model-config-form').fire('submit');h.$('model-provider').value='deepseek';await h.$('model-provider').fire('change');h.$('model-api-key').value='new draft secret';await h.$('model-api-key').fire('input');resolve({ok:true,value:{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'one',hasApiKey:true,storage:'encrypted'}});await flush();assert.equal(h.$('model-provider').value,'deepseek');assert.equal(h.$('model-api-key').value,'new draft secret');assert.equal(h.$('model-save').disabled,true);});

test('save masks the committed key and reports session-only storage without secret readback', async()=>{
 let h,received;h=await harness({saveModelConfig:input=>{received={...input};assert.equal(h.$('model-api-key').value,'test-secret');return Promise.resolve({ok:true,value:{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'two',hasApiKey:true,storage:'session',restartRequired:true}});}});
 h.$('model-api-key').value='test-secret';await h.$('model-fetch').fire('click');h.$('model-name').value='two';await h.$('model-config-form').fire('submit');await flush();
 assert.deepEqual(received,{provider:'openai',baseUrl:'https://api.openai.com/v1',model:'two',apiKey:'test-secret'});assert.equal(h.$('model-api-key').value,'');assert.match(h.$('model-storage-note').textContent,/仅本次/);assert.match(h.$('notice').textContent,/待重启/);
});
test('bubble duration persists, validates integer bounds, and survives unrelated appearance edits',async()=>{
  const h=await harness();assert.equal(h.$('bubble-duration-mode').value,'auto');assert.equal(h.$('bubble-duration-row').hidden,true);
  h.$('bubble-duration-mode').value='fixed';await h.$('bubble-duration-mode').fire('change');assert.equal(h.$('bubble-duration-row').hidden,false);
  h.$('bubble-duration-seconds').value='60';await h.$('bubble-duration-seconds').fire('change');
  const read=()=>JSON.parse(h.storage.get('football-assistant.appearance.v1'));
  assert.equal(read().bubbleDurationSeconds,60);assert.equal(read().fontFamily,undefined);
  for (const invalid of ['','1','61','2.5','NaN']) {h.$('bubble-duration-seconds').value=invalid;await h.$('bubble-duration-seconds').fire('change');assert.equal(read().bubbleDurationSeconds,60);assert.match(h.$('error').textContent,/2–60/);}
  h.$('font-size').value='18';await h.$('font-size').fire('change');assert.equal(read().bubbleDurationSeconds,60);assert.equal(read().bubbleDurationMode,'fixed');
  h.$('bubble-duration-mode').value='auto';await h.$('bubble-duration-mode').fire('change');assert.equal(read().bubbleDurationMode,'auto');assert.equal(h.$('bubble-duration-row').hidden,true);
});
