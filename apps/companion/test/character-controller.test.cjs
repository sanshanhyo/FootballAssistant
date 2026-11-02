'use strict';
const test = require('node:test'); const assert = require('node:assert/strict');
const fs = require('node:fs'); const os = require('node:os'); const path = require('node:path');
const { CharacterLibrary } = require('../src/character-library.cjs'); const { CompanionRuntime } = require('../src/companion-runtime.cjs'); const { createCharacterController } = require('../src/character-controller.cjs');
async function fixture(t) { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fa-controller-')); const library = new CharacterLibrary({ root }); const runtime = new CompanionRuntime({ characterLibrary: library }); await runtime.init(); t.after(async () => { await runtime.close(); fs.rmSync(root, { recursive: true, force: true }); }); return { root, library, runtime, controller: createCharacterController({ library, runtime, chooseZip: async () => null, choosePortrait: async () => null }) }; }
test('settings edits active package persona through revision guard and advances generation', async t => {
  const f = await fixture(t), before = f.controller.get(); const epoch = f.runtime.epoch;
  const result = await f.controller.save({ characterId: before.characterId, revision: before.revision, patch: { persona: 'Edited only through settings', name: 'My Eckera' } });
  assert.equal(result.name, 'My Eckera'); assert.equal(f.runtime.characterContext().persona, 'Edited only through settings'); assert.ok(f.runtime.epoch > epoch);
  await assert.rejects(f.controller.save({ characterId: before.characterId, revision: before.revision, patch: { persona: 'Stale save' } }), /刷新/);
  assert.equal(f.library.resolve().persona, 'Edited only through settings');
  await assert.rejects(f.controller.save({ characterId: result.characterId, revision: result.revision, patch: { portraitPath: '/etc/passwd' } }));
});
test('native import/portrait cancellation has no side effects and archive exposes no unrelated legacy credentials', async t => {
  const f = await fixture(t); assert.deepEqual(await f.controller.importZip(), { cancelled: true }); assert.deepEqual(await f.controller.portrait('official.eckera'), { cancelled: true });
  const directory = path.join(f.root, 'migrations/single-character-v1'); fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'complete.json'), JSON.stringify({ complete: true }));
  fs.writeFileSync(path.join(directory, 'settings.json'), JSON.stringify({ messages: ['old'], memories: [], secret: 'MUST NOT BE EXPOSED' }));
  const result = f.controller.archive(); assert.equal(result.readOnly, true); assert.deepEqual(result.messages, ['old']); assert.equal(JSON.stringify(result).includes('MUST NOT BE EXPOSED'), false);
});
test('trusted packaged builtin resources do not require filesystem-directory ancestors inside app.asar', async t => {
  const f = await fixture(t); const original = fs.lstatSync;
  fs.lstatSync = function (target, ...args) { if (String(target).includes(path.join('src', 'assets', 'characters', 'official.eckera'))) throw Error('ASAR resources are virtual, not real directories'); return original.call(this, target, ...args); };
  try { assert.equal(f.library.resolve().characterId, 'official.eckera'); assert.ok(f.library.resolve().persona); }
  finally { fs.lstatSync = original; }
});
