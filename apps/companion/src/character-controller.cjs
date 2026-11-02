'use strict';
const path = require('node:path');
const { createHash } = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { readTrustedFile, json, DEFAULT_CHARACTER_ID } = require('./character-library.cjs');
const revision = value => createHash('sha256').update(JSON.stringify([value.characterId, value.version, value.name, value.persona, value.voice, value.portraitPath])).digest('hex');
function createCharacterController({ library, runtime, chooseZip, choosePortrait }) {
  const detail = id => {
    const value = library.resolve(id || runtime.characterId);
    return { ...value, portraitPath: undefined, portraitUrl: pathToFileURL(value.portraitPath).href, revision: revision(value), current: value.characterId === runtime.characterId };
  };
  return {
    list() { return { characters: library.list().map(value => ({ characterId: value.characterId, name: value.name, version: value.version, fallback: value.fallback })), activeId: runtime.characterId, scope: runtime.state().characterScope }; },
    get(id) { return detail(id); },
    async select(id) { await runtime.selectCharacter(id); return runtime.state(); },
    async importZip() { const file = await chooseZip(); if (!file) return { cancelled: true }; const installed = library.importZip(readTrustedFile(file, 16 * 1024 * 1024)); if (runtime.characterId === installed.characterId) await runtime.refreshCharacter(); return { cancelled: false, character: detail(installed.characterId) }; },
    async save(input) {
      if (!input || Object.keys(input).sort().join(',') !== 'characterId,patch,revision') throw Error('Invalid character edit');
      const before = detail(input.characterId);
      if (before.fallback || input.revision !== before.revision) throw Error('角色已改变，请刷新后再保存。');
      if (!input.patch || Object.keys(input.patch).some(key => !['name', 'persona', 'voice'].includes(key))) throw Error('Unsupported character edit');
      library.setOverrides(input.characterId, input.patch);
      if (runtime.characterId === input.characterId) await runtime.refreshCharacter();
      return detail(input.characterId);
    },
    async portrait(id) { const file = await choosePortrait(); if (!file) return { cancelled: true }; library.setOverrides(id, { portraitPng: readTrustedFile(file, 16 * 1024 * 1024) }); if (runtime.characterId === id) await runtime.refreshCharacter(); return { cancelled: false, character: detail(id) }; },
    async reset(id) { library.resetOverrides(id); if (runtime.characterId === id) await runtime.refreshCharacter(); return detail(id); },
    archive() {
      const directory = path.join(library.root, 'migrations', 'single-character-v1');
      const marker = json(path.join(directory, 'complete.json'), {});
      const saved = json(path.join(directory, 'settings.json'), {});
      return { characterId: DEFAULT_CHARACTER_ID, archived: marker.complete === true, messages: Array.isArray(saved.messages) ? saved.messages : [], memories: Array.isArray(saved.memories) ? saved.memories : [], readOnly: true };
    },
  };
}
module.exports = { createCharacterController };
