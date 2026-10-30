'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { DEFAULT_CHARACTER_ID, DEFAULT_CHARACTER, getBuiltinVisualResource, characterPresentation } = require('../src/character.cjs');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');

async function withFile(action) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'companion-character-'));
  try { await action(path.join(directory, 'state.json')); }
  finally { await fs.rm(directory, { recursive: true, force: true }); }
}

test('the sole built-in identity resolves its packaged PNG only through an inert resource key', async () => {
  assert.equal(DEFAULT_CHARACTER_ID, 'official.eckera');
  assert.equal(DEFAULT_CHARACTER.characterId, DEFAULT_CHARACTER_ID);
  assert.equal(DEFAULT_CHARACTER.displayName, '埃克拉');
  assert.equal(DEFAULT_CHARACTER.englishName, 'Eckera');
  assert.ok(Object.isFrozen(DEFAULT_CHARACTER));
  const visual = getBuiltinVisualResource(DEFAULT_CHARACTER.visualResource);
  assert.equal(visual.kind, 'builtin-image');
  const assetRoot = path.resolve(__dirname, '../src/assets/characters');
  const imageFile = path.resolve(__dirname, '../src', visual.source);
  assert.ok(imageFile.startsWith(`${assetRoot}${path.sep}`));
  assert.equal(path.extname(imageFile), '.png');
  const image = await fs.readFile(imageFile);
  assert.deepEqual([...image.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(Object.isFrozen(visual));
  for (const reference of ['file:///sensitive', '../../private', 'https://invalid.test/portrait', 'javascript:alert(1)', () => {}]) {
    assert.equal(getBuiltinVisualResource(reference), null);
  }
  const presentation = characterPresentation();
  assert.equal(presentation.characterId, DEFAULT_CHARACTER_ID);
  assert.equal(presentation.requestedCharacterId, DEFAULT_CHARACTER_ID);
  assert.equal(presentation.fallback, false);
  assert.equal(Object.hasOwn(presentation, 'tools'), false);
});

test('legacy v1 defaults to Eckera without startup writes and retains existing data and extension fields', async () => {
  await withFile(async file => {
    const message = { id: 'old-message', text: '保留原聊天', role: 'assistant', sessionId: 'old-session', metadata: { source: 'legacy' } };
    const memory = { id: 'old-memory', text: '用户明确保存的内容', source: 'user-confirmed', futureMemoryField: 'keep' };
    const saved = { version: 1, proactivity: 35, preferences: { expression: 'happy', sttProvider: 'mock', ttsProvider: 'azure', futurePreference: { retain: true } }, historyEnabled: true, messages: [message], memories: [memory], futureExtension: { retain: true } };
    const original = JSON.stringify(saved);
    await fs.writeFile(file, original);
    const runtime = new CompanionRuntime({ file });
    try {
      const state = await runtime.init();
      assert.equal(state.character.characterId, DEFAULT_CHARACTER_ID);
      assert.equal(state.character.fallback, false);
      assert.equal(state.proactivity, 35);
      assert.deepEqual(state.preferences, { expression: 'happy', sttProvider: 'mock', ttsProvider: 'azure' });
      assert.deepEqual(runtime.getHistory().messages, [message]);
      assert.deepEqual(runtime.getMemories().entries, [memory]);
      assert.equal(await fs.readFile(file, 'utf8'), original);
      runtime.setProactivity(36); await runtime.persist();
      const written = JSON.parse(await fs.readFile(file, 'utf8'));
      assert.equal(written.version, 1);
      assert.equal(written.characterId, DEFAULT_CHARACTER_ID);
      assert.deepEqual(written.preferences, saved.preferences);
      assert.deepEqual(written.futureExtension, saved.futureExtension);
      assert.deepEqual(written.messages, [message]); assert.deepEqual(written.memories, [memory]);
      const restored = new CompanionRuntime({ file });
      try { assert.equal((await restored.init()).character.characterId, DEFAULT_CHARACTER_ID); }
      finally { await restored.close(); }
    } finally { await runtime.close(); }
  });
});

test('unknown character IDs retain their saved selection while displaying a safe built-in fallback', async () => {
  for (const requestedCharacterId of ['third-party.future-character', `third-party.${'x'.repeat(201)}`, '../../not-an-asset-path']) await withFile(async file => {
    await fs.writeFile(file, JSON.stringify({ version: 1, characterId: requestedCharacterId, memories: [{ id: 'remember', text: '角色不可用也保留记忆' }] }));
    const runtime = new CompanionRuntime({ file });
    try {
      const state = await runtime.init();
      assert.equal(state.character.requestedCharacterId, requestedCharacterId);
      assert.equal(state.character.characterId, DEFAULT_CHARACTER_ID);
      assert.equal(state.character.fallback, true);
      assert.equal(state.character.visual, getBuiltinVisualResource(DEFAULT_CHARACTER.visualResource));
      assert.throws(() => runtime.setPreferences({ characterId: DEFAULT_CHARACTER_ID }), /偏好设置/);
      runtime.setPreferences({ expression: 'idle' }); await runtime.persist();
      const written = JSON.parse(await fs.readFile(file, 'utf8'));
      assert.equal(written.characterId, requestedCharacterId);
      assert.deepEqual(written.memories, [{ id: 'remember', text: '角色不可用也保留记忆' }]);
      const restored = new CompanionRuntime({ file });
      try { assert.equal((await restored.init()).character.requestedCharacterId, requestedCharacterId); }
      finally { await restored.close(); }
    } finally { await runtime.close(); }
  });
});

test('invalid character values use the safe default and unsupported storage versions cannot be overwritten', async () => {
  for (const input of [null, 3, {}, [], '', ' '.repeat(4)]) {
    assert.equal(characterPresentation(input).characterId, DEFAULT_CHARACTER_ID);
    assert.equal(characterPresentation(input).requestedCharacterId, DEFAULT_CHARACTER_ID);
    assert.equal(characterPresentation(input).fallback, false);
  }
  await withFile(async file => {
    const original = JSON.stringify({ version: 2, characterId: 'future.selected', futureData: ['must', 'survive'] });
    await fs.writeFile(file, original);
    const runtime = new CompanionRuntime({ file });
    try {
      const state = await runtime.init();
      assert.equal(state.character.characterId, DEFAULT_CHARACTER_ID);
      assert.match(state.storageWarning, /版本暂不支持/);
      runtime.setProactivity(20); await runtime.saveMemory({ text: '只在当前进程保留' });
      assert.equal(await fs.readFile(file, 'utf8'), original);
    } finally { await runtime.close(); }
  });
});
