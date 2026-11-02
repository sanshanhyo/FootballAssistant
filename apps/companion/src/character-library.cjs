'use strict';
// Pure-data packages; only the main process may construct this service or supply its root.
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { parseCharacterZip, validatePng } = require('./character-installer.cjs');
const DEFAULT_CHARACTER_ID = 'official.eckera';
const BUILTIN_ROOT = path.join(__dirname, 'assets/characters/official.eckera');
const hash = value => createHash('sha256').update(value).digest('hex');
function normalizeCharacterId(id) {
  if (id === 'builtin.eckera') return DEFAULT_CHARACTER_ID;
  if (typeof id !== 'string' || !/^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$/.test(id) || id.length > 96) throw Error('Invalid character ID');
  return id;
}
function keys(value, allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !allowed.includes(key))) throw Error('Unsupported character fields');
}
function text(value, max = 16384) {
  if (typeof value !== 'string' || !value.trim() || value.includes('\0') || !value.isWellFormed() || Buffer.byteLength(value) > max) throw Error('Invalid character text');
  return value;
}
function validateVoice(voice) {
  if (voice === null) return null;
  keys(voice, ['provider', 'voice_id']);
  for (const key of ['provider', 'voice_id']) {
    if (typeof voice[key] !== 'string' || !/^[a-zA-Z0-9_.-]{1,128}$/.test(voice[key])) throw Error('Voice must use local provider and voice identifiers, not credentials or URLs');
  }
  return { provider: voice.provider, voice_id: voice.voice_id };
}
function validateManifest(value, { builtin = false } = {}) {
  keys(value, ['schema_version', 'id', 'version', 'name', 'persona', 'portrait', 'voice']);
  const id = normalizeCharacterId(value.id);
  if (value.id !== id || (!builtin && (id.startsWith('builtin.') || id.startsWith('official.')))) throw Error('Reserved character identity');
  if (value.schema_version !== 1 || !/^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(value.version)) throw Error('Unsupported character format or version');
  if (value.persona !== 'persona.md' || !(value.portrait === 'assets/portrait.png' || (builtin && value.portrait === 'default.png'))) throw Error('Unsupported package resource path');
  return { schema_version: 1, id, version: value.version, name: text(value.name, 160), persona: value.persona, portrait: value.portrait, voice: value.voice == null ? null : validateVoice(value.voice) };
}
function safeParents(target) {
  let current = path.resolve(target);
  while (true) {
    if (fs.existsSync(current)) {
      const stat = fs.lstatSync(current);
      if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('Unsafe character directory');
    }
    const next = path.dirname(current); if (next === current) break; current = next;
  }
}
function mkdir(directory) { safeParents(directory); fs.mkdirSync(directory, { recursive: true, mode: 0o700 }); safeParents(directory); }
function read(file, limit = 32 * 1024 * 1024) {
  safeParents(path.dirname(file));
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > limit) throw Error('Unsafe character file');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const opened = fs.fstatSync(fd);
    if (opened.ino !== stat.ino || opened.dev !== stat.dev) throw Error('Character file changed');
    const bytes = Buffer.alloc(Math.min(limit, stat.size) + 1); const length = fs.readSync(fd, bytes, 0, bytes.length, 0);
    if (length > limit) throw Error('Character file exceeds limit');
    return bytes.subarray(0, length);
  } finally { fs.closeSync(fd); }
}
function json(file, fallback) { try { return JSON.parse(read(file, 2_000_000)); } catch (error) { if (error.code === 'ENOENT' && fallback !== undefined) return fallback; throw error; } }
function atomic(file, bytes) {
  mkdir(path.dirname(file));
  if (fs.existsSync(file)) read(file);
  const tmp = `${file}.${randomUUID()}.tmp`;
  try { const fd = fs.openSync(tmp, 'wx', 0o600); try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); } fs.renameSync(tmp, file); }
  finally { fs.rmSync(tmp, { force: true }); }
}
function decode(bytes) { return text(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
function scopeFor(saveId, characterId) {
  text(saveId, 512);
  const id = normalizeCharacterId(characterId);
  return Object.freeze({ saveId, characterId: id, key: hash(JSON.stringify([saveId, id])), factsKey: hash(saveId) });
}
class CharacterLibrary {
  constructor({ root, builtinRoot = BUILTIN_ROOT }) {
    this.root = path.resolve(root); this.builtinRoot = builtinRoot;
    mkdir(this.root);
    this.registryFile = path.join(this.root, 'registry.json');
  }
  registry() {
    const value = json(this.registryFile, { schema_version: 1, installed: {}, selectedBySave: {} });
    keys(value, ['schema_version', 'installed', 'selectedBySave']);
    if (value.schema_version !== 1 || !value.installed || typeof value.installed !== 'object' || Array.isArray(value.installed) || !value.selectedBySave || typeof value.selectedBySave !== 'object' || Array.isArray(value.selectedBySave)) throw Error('Unsupported character registry');
    return value;
  }
  saveRegistry(value) { atomic(this.registryFile, JSON.stringify(value, null, 2)); }
  builtin() {
    const manifest = validateManifest(json(path.join(this.builtinRoot, 'manifest.json')), { builtin: true });
    if (manifest.id !== DEFAULT_CHARACTER_ID) throw Error('Invalid builtin identity');
    return { manifest, persona: decode(read(path.join(this.builtinRoot, manifest.persona), 16384)), portraitPath: path.join(this.builtinRoot, manifest.portrait) };
  }
  load(id) {
    id = normalizeCharacterId(id);
    if (id === DEFAULT_CHARACTER_ID) return this.builtin();
    const version = this.registry().installed[id];
    if (typeof version !== 'string' || !/^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(version)) throw Error('Character is not installed');
    const dir = path.join(this.root, 'packages', id, version);
    const manifest = validateManifest(json(path.join(dir, 'manifest.json')));
    if (manifest.id !== id || manifest.version !== version) throw Error('Package identity mismatch');
    const portraitPath = path.join(dir, manifest.portrait);
    validatePng(read(portraitPath, 16 * 1024 * 1024));
    return { manifest, persona: decode(read(path.join(dir, manifest.persona), 16384)), portraitPath };
  }
  resolve(requestedId = DEFAULT_CHARACTER_ID) {
    let id; let base; let fallback = false; const warnings = [];
    try { id = normalizeCharacterId(requestedId); base = this.load(id); }
    catch { id = DEFAULT_CHARACTER_ID; base = this.builtin(); fallback = true; warnings.push('character_unavailable'); }
    let override = {};
    try {
      override = json(path.join(this.root, 'overrides', id, 'override.json'), {});
      keys(override, ['name', 'persona', 'voice', 'portraitHash']);
      if (override.name !== undefined) text(override.name, 160);
      if (override.persona !== undefined) text(override.persona);
      if (override.voice !== undefined) validateVoice(override.voice);
      if (override.portraitHash !== undefined) {
        if (!/^[a-f0-9]{64}$/.test(override.portraitHash)) throw Error('Invalid portrait hash');
        const portrait = path.join(this.root, 'overrides', id, `${override.portraitHash}.png`);
        const bytes = read(portrait, 16 * 1024 * 1024); validatePng(bytes);
        if (hash(bytes) !== override.portraitHash) throw Error('Portrait changed');
        base.portraitPath = portrait;
      }
    } catch { override = {}; warnings.push('override_unavailable'); }
    return { characterId: id, requestedCharacterId: requestedId, version: base.manifest.version, name: override.name ?? base.manifest.name, persona: override.persona ?? base.persona, voice: override.voice === undefined ? base.manifest.voice : override.voice, portraitPath: base.portraitPath, fallback, warnings };
  }
  list() {
    let ids = []; try { ids = Object.keys(this.registry().installed); } catch { /* Builtin remains reachable with a corrupt registry. */ }
    return [DEFAULT_CHARACTER_ID, ...ids.filter(id => id !== DEFAULT_CHARACTER_ID)].map(id => this.resolve(id));
  }
  importZip(bytes) {
    const files = parseCharacterZip(bytes);
    const manifest = validateManifest(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(files.get('manifest.json'))));
    decode(files.get('persona.md')); validatePng(files.get('assets/portrait.png'));
    const registry = this.registry();
    const dir = path.join(this.root, 'packages', manifest.id, manifest.version);
    if (fs.existsSync(dir)) {
      for (const [name, data] of files) { if (name.endsWith('/')) continue; if (!read(path.join(dir, name)).equals(data)) throw Error('Version already installed with different content'); }
    } else {
      const stage = path.join(this.root, `.install-${randomUUID()}`); mkdir(stage);
      try {
        for (const [name, data] of files) { if (name.endsWith('/')) continue; const file = path.join(stage, name); mkdir(path.dirname(file)); fs.writeFileSync(file, data, { flag: 'wx', mode: 0o600 }); }
        mkdir(path.dirname(dir)); fs.renameSync(stage, dir);
      } finally { fs.rmSync(stage, { recursive: true, force: true }); }
    }
    // Explicit local import is the update operation. Previous versions and overrides are retained.
    registry.installed[manifest.id] = manifest.version; this.saveRegistry(registry);
    return this.resolve(manifest.id);
  }
  setOverrides(characterId, patch) {
    const id = normalizeCharacterId(characterId); this.load(id);
    keys(patch, ['name', 'persona', 'voice', 'portraitPng']);
    const file = path.join(this.root, 'overrides', id, 'override.json');
    const current = json(file, {});
    for (const key of ['name', 'persona', 'voice']) {
      if (patch[key] === undefined) continue;
      if (patch[key] === null && key !== 'voice') delete current[key];
      else current[key] = key === 'voice' ? validateVoice(patch[key]) : text(patch[key], key === 'name' ? 160 : 16384);
    }
    if (patch.portraitPng === null) delete current.portraitHash;
    else if (patch.portraitPng !== undefined) {
      if (!Buffer.isBuffer(patch.portraitPng)) throw Error('Portrait must be PNG bytes');
      validatePng(patch.portraitPng); const digest = hash(patch.portraitPng);
      atomic(path.join(path.dirname(file), `${digest}.png`), patch.portraitPng); current.portraitHash = digest;
    }
    atomic(file, JSON.stringify(current, null, 2)); return this.resolve(id);
  }
  resetOverrides(characterId) { const id = normalizeCharacterId(characterId); this.load(id); atomic(path.join(this.root, 'overrides', id, 'override.json'), '{}'); return this.resolve(id); }
  selected(saveId) { text(saveId, 512); try { return this.resolve(this.registry().selectedBySave[hash(saveId)] || DEFAULT_CHARACTER_ID); } catch { return this.resolve(DEFAULT_CHARACTER_ID); } }
  select(saveId, characterId) {
    text(saveId, 512); const result = this.resolve(characterId);
    if (result.fallback) throw Error('Selected character is unavailable');
    let registry;
    try { registry = this.registry(); } catch (error) {
      if (result.characterId !== DEFAULT_CHARACTER_ID) throw error;
      return { ...result, warnings: [...result.warnings, 'registry_unavailable_selection_not_saved'] };
    }
    registry.selectedBySave[hash(saveId)] = result.characterId; this.saveRegistry(registry); return result;
  }
  readScope(saveId, characterId) {
    const scope = scopeFor(saveId, characterId);
    const value = json(path.join(this.root, 'scopes', scope.key + '.json'), { schema_version: 1, scope, messages: [], memories: [] });
    if (value.schema_version !== 1 || value.scope?.key !== scope.key || value.scope?.saveId !== scope.saveId || value.scope?.characterId !== scope.characterId) throw Error('Stored character scope mismatch');
    return value;
  }
  writeScope(saveId, characterId, state) {
    const scope = scopeFor(saveId, characterId);
    keys(state, ['messages', 'memories']);
    if (!Array.isArray(state.messages) || !Array.isArray(state.memories)) throw Error('Invalid character history');
    const value = { schema_version: 1, scope, messages: state.messages, memories: state.memories };
    const bytes = JSON.stringify(value); if (Buffer.byteLength(bytes) > 2_000_000) throw Error('Character history exceeds limit');
    atomic(path.join(this.root, 'scopes', scope.key + '.json'), bytes); return value;
  }
  uninstall(characterId) {
    const id = normalizeCharacterId(characterId); if (id === DEFAULT_CHARACTER_ID) throw Error('Builtin Eckera cannot be removed');
    const registry = this.registry(); delete registry.installed[id];
    for (const key of Object.keys(registry.selectedBySave)) if (registry.selectedBySave[key] === id) registry.selectedBySave[key] = DEFAULT_CHARACTER_ID;
    this.saveRegistry(registry); // Keep versions, overrides and conversation data recoverable.
  }
}
module.exports = { CharacterLibrary, DEFAULT_CHARACTER_ID, normalizeCharacterId, validateManifest, validateVoice, scopeFor, atomic, read, json, mkdir };
