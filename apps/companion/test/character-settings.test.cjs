'use strict';
const test = require('node:test'); const assert = require('node:assert/strict'); const vm = require('node:vm'); const fs = require('node:fs'); const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/character-settings.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
class Element { constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.value = ''; this.textContent = ''; this.disabled = false; } append(child) { this.children.push(child); } replaceChildren() { this.children = []; } setAttribute() {} addEventListener(name, listener) { this.events[name] = listener; } fire(name) { return this.events[name]?.({ preventDefault() {} }); } }
async function fixture(overrides = {}) {
  const elements = [], calls = [], errors = []; const root = new Element('div');
  const value = { characterId: 'official.eckera', name: 'Eckera', persona: 'Original', voice: null, portraitUrl: 'file:///trusted/portrait.png', version: '1.0.0', revision: 'first', current: true };
  const ok = value => Promise.resolve({ ok: true, value });
  const api = { listCharacters: () => ok({ activeId: value.characterId, characters: [value] }), getCharacter: () => ok(value), selectCharacter: id => { calls.push(['select', id]); return ok({ epoch: 2 }); }, saveCharacter: input => { calls.push(['save', input]); return ok({ ...value, ...input.patch, revision: 'second' }); }, importCharacter: (...args) => { calls.push(['import', ...args]); return ok({ cancelled: true }); }, chooseCharacterPortrait: (...args) => { calls.push(['portrait', ...args]); return ok({ cancelled: true }); }, getCharacterArchive: () => ok({ messages: [], memories: [] }), ...overrides };
  const window = { confirm: () => true, addEventListener() {}, removeEventListener() {} };
  vm.runInNewContext(source, { window, document: { createElement: tag => { const e = new Element(tag); elements.push(e); return e; } }, console });
  const view = window.FootballCharacterSettings.bind({ root, api, onError: message => { if (message) errors.push(message); } }); await flush(); await flush();
  return { view, calls, errors, elements, button: name => elements.find(e => e.tag === 'button' && e.textContent === name), input: name => elements.find(e => e.tag === 'label' && e.textContent === name).children[0] };
}
test('character editor saves selected identity and loaded revision, and tracks unsaved close guard', async () => {
  const f = await fixture(); const text = f.input('人设（最多 16 KiB）'); text.value = 'New persona'; text.fire('input'); assert.equal(f.view.hasUnsavedChanges(), true);
  f.button('保存覆写').fire('click'); await flush();
  const payload = f.calls.find(call => call[0] === 'save')[1]; assert.equal(payload.characterId, 'official.eckera'); assert.equal(payload.revision, 'first'); assert.equal(payload.patch.persona, 'New persona');
  assert.equal(f.view.hasUnsavedChanges(), false); assert.deepEqual(f.errors, []);
});
test('native dialogs never receive renderer-chosen filesystem paths and canceled imports retain editor', async () => {
  const f = await fixture(); f.button('导入 ZIP 角色包').fire('click'); await flush(); f.button('选择 PNG 立绘').fire('click'); await flush();
  assert.deepEqual(f.calls.find(call => call[0] === 'import'), ['import']); assert.deepEqual(f.calls.find(call => call[0] === 'portrait'), ['portrait', 'official.eckera']); assert.equal(f.input('人设（最多 16 KiB）').value, 'Original');
});
test('failed save preserves draft and in-flight operation disables editable fields', async () => {
  let resolve; const f = await fixture({ saveCharacter: () => new Promise(r => { resolve = r; }) }); const text = f.input('人设（最多 16 KiB）'); text.value = 'Keep this'; text.fire('input');
  f.button('保存覆写').fire('click'); assert.equal(text.disabled, true); resolve({ ok: false, error: 'Conflict' }); await flush();
  assert.equal(text.disabled, false); assert.equal(text.value, 'Keep this'); assert.equal(f.view.hasUnsavedChanges(), true); assert.deepEqual(f.errors, ['Conflict']);
});
