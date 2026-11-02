'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function harness(api) {
  const byId = new Map();
  class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; this.checked = false; }
    set id(value) { byId.set(value, this); this._id = value; } get id() { return this._id; }
    append(child) { child.parentElement = this; this.children.push(child); }
    setAttribute() {} addEventListener(name, callback) { this.listeners[name] = callback; }
    remove() { this.removed = true; }
  }
  const root = new Node('div'); root.ownerDocument = { createElement: tag => new Node(tag) };
  const context = { setTimeout, clearTimeout }; vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/speech-settings.js'), 'utf8'), context);
  const messages = [];
  return { root, byId, messages, ui: context.FootballSpeechSettings.bind({ root, api, onError: x => messages.push(x), onNotice: x => messages.push(x) }) };
}
const saved = { enabled: false, networkConsent: false, provider: 'edge', voice: '', speed: 1, volume: 1, baseUrl: '', model: '', hasApiKey: false, storage: 'none' };
test('only online choices; legacy local never opts in or saves on load', async () => {
  let saves = 0;
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: { ...saved, provider: 'system', enabled: true } }), saveSpeechConfig: async () => { saves++; } });
  await h.ui.ready;
  assert.deepEqual(h.byId.get('tts-provider').children.map(x => x.value), ['edge', 'openai']);
  assert.equal(h.byId.get('tts-enabled').checked, false);
  assert.equal(h.byId.has('tts-networkConsent'), false);
  assert.equal(saves, 0); h.ui.dispose();
});
test('autosave serializes edits without losing a newer key', async () => {
  const calls = [], resolvers = [];
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: { ...saved, provider: 'openai' } }), saveSpeechConfig: input => { calls.push({ ...input }); return new Promise(resolve => resolvers.push(resolve)); } });
  await h.ui.ready;
  const key = h.byId.get('tts-apiKey');
  key.value = 'fake-first'; key.listeners.input(); const first = h.ui.flush();
  key.value = 'fake-second'; key.listeners.input(); const second = h.ui.flush();
  assert.equal(calls.length, 1);
  resolvers.shift()({ ok: true, value: { ...saved, hasApiKey: true } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 2); assert.equal(calls[1].apiKey, 'fake-second');
  resolvers.shift()({ ok: true, value: { ...saved, hasApiKey: true } });
  await Promise.all([first, second]); assert.equal(key.value, ''); h.ui.dispose();
});
test('failed save retains key; destination edits reset consent and enabled', async () => {
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: { ...saved, provider: 'openai' } }), saveSpeechConfig: async () => ({ ok: false, error: 'do not echo secrets' }) });
  await h.ui.ready; const key = h.byId.get('tts-apiKey'); key.value = 'fake-only'; key.listeners.input();
  assert.equal(await h.ui.flush(), false); assert.equal(key.value, 'fake-only');
  h.byId.get('tts-enabled').checked = true;
  h.byId.get('tts-baseUrl').listeners.input();
  assert.equal(h.byId.has('tts-networkConsent'), false); assert.equal(h.byId.get('tts-enabled').checked, false);
  assert.deepEqual(h.messages, ['语音设置保存失败']); h.ui.dispose();
});
test('Edge saves the built-in voice without model, endpoint, or key input', async () => {
  let captured;
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: saved }), saveSpeechConfig: async input => { captured = { ...input }; return { ok: true, value: saved }; } });
  await h.ui.ready; h.byId.get('tts-speed').value = '1.25'; h.byId.get('tts-speed').listeners.input(); await h.ui.flush();
  assert.equal(captured.voice, 'zh-CN-XiaoxiaoNeural'); assert.equal(captured.speed, 1.25);
  for (const name of ['baseUrl', 'model', 'apiKey']) assert.equal(name in captured, false);
  h.ui.dispose();
});
test('explicit online switch grants consent; changing provider revokes it', async () => {
  const calls=[];
  const h=harness({getSpeechConfig:async()=>({ok:true,value:saved}),saveSpeechConfig:async input=>{calls.push({...input});return {ok:true,value:input};}});
  await h.ui.ready; const enabled=h.byId.get('tts-enabled');enabled.checked=true;enabled.listeners.change();await h.ui.flush();
  assert.equal(calls[0].enabled,true); assert.equal(calls[0].networkConsent,true);
  h.byId.get('tts-provider').value='openai';h.byId.get('tts-provider').listeners.change();await h.ui.flush();
  assert.equal(calls[1].enabled,false);assert.equal(calls[1].networkConsent,false);h.ui.dispose();
});
test('old destination response cannot clear current draft or show its key mask', async () => {
  const calls=[], resolvers=[];
  const h=harness({getSpeechConfig:async()=>({ok:true,value:{...saved,provider:'openai',baseUrl:'https://a.example/v1'}}),saveSpeechConfig:input=>{calls.push({...input});return new Promise(r=>resolvers.push(r));}});
  await h.ui.ready;const key=h.byId.get('tts-apiKey'),url=h.byId.get('tts-baseUrl');
  key.value='fake-only';key.listeners.input();const first=h.ui.flush();
  url.value='https://b.example/v1';url.listeners.input();
  resolvers.shift()({ok:true,value:{...saved,baseUrl:'https://a.example/v1',hasApiKey:true}});
  await new Promise(r=>setImmediate(r));
  assert.equal(calls[1].apiKey,'fake-only');assert.equal(key.placeholder,'');
  resolvers.shift()({ok:true,value:{...saved,baseUrl:url.value,hasApiKey:true}});await first;h.ui.dispose();
});
test('newer speech edits are saved after an older request fails, without retrying unchanged failure', async () => {
  const calls=[];let resolve;
  const h=harness({getSpeechConfig:async()=>({ok:true,value:saved}),saveSpeechConfig:input=>{calls.push({...input});return calls.length===1?new Promise(r=>resolve=r):Promise.resolve({ok:true,value:input});}});
  await h.ui.ready;const speed=h.byId.get('tts-speed');speed.value='1.1';speed.listeners.input();const first=h.ui.flush();
  speed.value='1.5';speed.listeners.input();const second=h.ui.flush();
  resolve({ok:false});assert.deepEqual(await Promise.all([first,second]),[true,true]);assert.equal(calls.length,2);assert.equal(calls[1].speed,1.5);h.ui.dispose();
});
