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
  const context = {}; vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/speech-settings.js'), 'utf8'), context);
  const messages = [];
  return { root, byId, messages, ui: context.FootballSpeechSettings.bind({ root, api, onError: x => messages.push(x), onNotice: x => messages.push(x) }) };
}
const saved = { enabled: false, networkConsent: false, provider: 'edge', voice: '', speed: 1, volume: 1, baseUrl: '', model: '', hasApiKey: false, storage: 'none' };
test('speech UI clears consent when destination changes and prevents duplicate saves', async () => {
  let saves = 0, resolve;
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: saved }), saveSpeechConfig: () => { saves++; return new Promise(done => { resolve = done; }); } });
  await h.ui.ready;
  h.byId.get('tts-networkConsent').checked = true;
  h.byId.get('tts-provider').value = 'openai'; h.byId.get('tts-provider').listeners.change();
  assert.equal(h.byId.get('tts-networkConsent').checked, false);
  h.byId.get('tts-networkConsent').checked = true; h.byId.get('tts-baseUrl').listeners.input();
  assert.equal(h.byId.get('tts-networkConsent').checked, false);
  h.byId.get('tts-apiKey').value = 'fake-only';
  const form = h.root.children[0];
  const first = form.listeners.submit({ preventDefault() {} });
  await form.listeners.submit({ preventDefault() {} }); assert.equal(saves, 1);
  resolve({ ok: true, value: saved }); await first;
  assert.equal(h.byId.get('tts-apiKey').value, ''); h.ui.dispose();
});
test('closing settings during save clears password and suppresses late status updates', async () => {
  let resolve;
  const h = harness({ getSpeechConfig: async () => ({ ok: true, value: saved }), saveSpeechConfig: () => new Promise(done => { resolve = done; }) });
  await h.ui.ready; h.byId.get('tts-apiKey').value = 'fake-only';
  const pending = h.root.children[0].listeners.submit({ preventDefault() {} });
  h.ui.dispose(); assert.equal(h.byId.get('tts-apiKey').value, '');
  resolve({ ok: true, value: saved }); await pending;
  assert.equal(h.messages.length, 0); assert.equal(h.root.children[0].removed, true);
});
