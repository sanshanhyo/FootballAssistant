'use strict';
const path = require('node:path');
const fs = require('node:fs');
const { DEFAULT_CHARACTER_ID, atomic, read, json, mkdir } = require('./character-library.cjs');
/** Main-process caller supplies known legacy paths, never renderer-controlled filenames.
 * Preserve the exact source bytes first; a completed marker makes retries idempotent.
 * History/memory SQLite migration belongs to CompanionStore, not JSON copying here.
 */
function migrateLegacyCharacter({ library, personaFile, settingsFile, verifiedSaveId }) {
  const directory = path.join(library.root, 'migrations', 'single-character-v1');
  mkdir(directory);
  const marker = path.join(directory, 'complete.json');
  if (fs.existsSync(marker)) return json(marker);
  const saved = {};
  for (const [name, file, limit] of [['persona.md', personaFile, 16384], ['settings.json', settingsFile, 2_000_000]]) {
    const backup = path.join(directory, name);
    if (fs.existsSync(backup)) saved[name] = read(backup, limit);
    else if (file) {
      try { const relative = path.relative(path.dirname(library.configuredRoot || library.root), path.resolve(file));
        if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) throw Error('Legacy source is outside configured application data');
        // Resolve only the trusted app-data boundary, retaining link checks inside it.
        saved[name] = read(path.join(path.dirname(library.root), relative), limit); atomic(backup, saved[name]); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  }
  const existing = json(path.join(library.root, 'overrides', DEFAULT_CHARACTER_ID, 'override.json'), {});
  const patch = {};
  if (saved['persona.md'] && existing.persona === undefined) patch.persona = new TextDecoder('utf-8', { fatal: true }).decode(saved['persona.md']);
  // Current v1 companion runtime stores provider choice in preferences, not voice credentials.
  let settings = {};
  if (saved['settings.json']) settings = JSON.parse(saved['settings.json']);
  const provider = settings.version === 1 ? settings.preferences?.ttsProvider : null;
  if (['system', 'edge', 'openai', 'azure', 'mock'].includes(provider) && existing.voice === undefined) patch.voice = { provider, voice_id: 'default' };
  // Do not infer a game save from sessionId/backendId. Only a verified external mapping may assign it.
  if (verifiedSaveId && settings.version === 1) {
    const current = library.readScope(verifiedSaveId, DEFAULT_CHARACTER_ID);
    if (!current.messages.length && !current.memories.length) library.writeScope(verifiedSaveId, DEFAULT_CHARACTER_ID, {
      messages: Array.isArray(settings.messages) ? settings.messages : [],
      memories: Array.isArray(settings.memories) ? settings.memories : [],
    });
  }
  if (Object.keys(patch).length) library.setOverrides(DEFAULT_CHARACTER_ID, patch);
  const result = { schema_version: 1, characterId: DEFAULT_CHARACTER_ID, complete: true, backups: Object.keys(saved), archivePath: saved['settings.json'] ? path.join(directory, 'settings.json') : null, assignedSaveId: verifiedSaveId || null };
  atomic(marker, JSON.stringify(result, null, 2)); return result;
}
module.exports = { migrateLegacyCharacter };
