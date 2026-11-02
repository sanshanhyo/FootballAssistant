'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { CharacterLibrary, DEFAULT_CHARACTER_ID, scopeFor, validateManifest } = require('../src/character-library.cjs');
const { CharacterSession } = require('../src/character-session.cjs');
const { migrateLegacyCharacter } = require('../src/character-migration.cjs');
const png = fs.readFileSync(path.join(__dirname, '../src/assets/characters/official.eckera/default.png'));
function crc(bytes) { let c = 0xffffffff; for (const b of bytes) { c ^= b; for (let j = 0; j < 8; j++) c = (c >>> 1) ^ ((c & 1) ? 0xedb88320 : 0); } return (c ^ 0xffffffff) >>> 0; }
function zip(manifest, persona = 'Package persona') {
  const entries = [['manifest.json', Buffer.from(JSON.stringify(manifest))], ['persona.md', Buffer.from(persona)], ['assets/portrait.png', png]];
  const local = [], central = []; let offset = 0;
  for (const [name, bytes] of entries) {
    const n = Buffer.from(name), l = Buffer.alloc(30), c = Buffer.alloc(46);
    l.writeUInt32LE(0x04034b50); l.writeUInt16LE(20, 4); l.writeUInt32LE(crc(bytes), 14); l.writeUInt32LE(bytes.length, 18); l.writeUInt32LE(bytes.length, 22); l.writeUInt16LE(n.length, 26);
    c.writeUInt32LE(0x02014b50); c.writeUInt16LE(20, 4); c.writeUInt16LE(20, 6); c.writeUInt32LE(crc(bytes), 16); c.writeUInt32LE(bytes.length, 20); c.writeUInt32LE(bytes.length, 24); c.writeUInt16LE(n.length, 28); c.writeUInt32LE(offset, 42);
    local.push(l, n, bytes); central.push(c, n); offset += l.length + n.length + bytes.length;
  }
  const cd = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(3, 8); end.writeUInt16LE(3, 10); end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, cd, end]);
}
const manifest = (extra = {}) => ({ schema_version: 1, id: 'example.alex', version: '1.0.0', name: 'Alex', persona: 'persona.md', portrait: 'assets/portrait.png', voice: { provider: 'system', voice_id: 'default' }, ...extra });
function setup(t) { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fa-character-')); t.after(() => fs.rmSync(root, { recursive: true, force: true })); return { root, library: new CharacterLibrary({ root }) }; }
test('builtin always resolves including old identity and corrupted registry', t => {
  const { root, library } = setup(t);
  assert.equal(library.resolve().characterId, 'official.eckera'); assert.ok(library.resolve().persona.length > 30);
  assert.equal(library.resolve('builtin.eckera').characterId, DEFAULT_CHARACTER_ID);
  assert.equal(library.resolve('unknown.person').fallback, true);
  fs.writeFileSync(path.join(root, 'registry.json'), 'broken');
  assert.equal(library.list()[0].characterId, DEFAULT_CHARACTER_ID);
  assert.equal(new CharacterSession({ library }).activate('save-a').character.characterId, DEFAULT_CHARACTER_ID);
  assert.throws(() => library.uninstall(DEFAULT_CHARACTER_ID));
});
test('import, immutable version, update and per-character overrides', t => {
  const { library } = setup(t); library.importZip(zip(manifest()));
  assert.equal(library.resolve('example.alex').persona, 'Package persona');
  library.setOverrides('example.alex', { persona: 'My edited persona', voice: { provider: 'mock', voice_id: 'mine' }, portraitPng: png });
  library.importZip(zip(manifest({ version: '1.0.1', name: 'Updated' }), 'New package persona'));
  const result = library.resolve('example.alex'); assert.equal(result.persona, 'My edited persona'); assert.equal(result.name, 'Updated'); assert.equal(result.voice.voice_id, 'mine');
  assert.throws(() => library.importZip(zip(manifest({ version: '1.0.1' }), 'Replaced version')));
  library.resetOverrides('example.alex'); assert.equal(library.resolve('example.alex').persona, 'New package persona');
});
test('rejects executable, credentials, remote resource and reserved identity fields', () => {
  for (const value of [manifest({ script: 'run.js' }), manifest({ apiKey: 'secret' }), manifest({ portrait: 'https://evil/p.png' }), manifest({ id: 'builtin.hijack' }), manifest({ id: 'official.eckera' }), manifest({ voice: { provider: 'https://evil', voice_id: 'voice' } }), manifest({ voice: { provider: 'system', voice_id: 'v', token: 'secret' } }), manifest({ schema_version: 2 })]) assert.throws(() => validateManifest(value));
});
test('selections and history are save+character scoped; uninstall falls back without deleting history', t => {
  const { library } = setup(t); library.importZip(zip(manifest())); library.select('save-a', 'example.alex');
  assert.equal(library.selected('save-a').characterId, 'example.alex'); assert.equal(library.selected('save-b').characterId, DEFAULT_CHARACTER_ID);
  library.writeScope('save-a', 'example.alex', { messages: ['private'], memories: ['relationship'] });
  assert.deepEqual(library.readScope('save-a', DEFAULT_CHARACTER_ID).messages, []);
  assert.deepEqual(library.readScope('save-b', 'example.alex').memories, []);
  assert.notEqual(scopeFor('a/b', 'example.alex').key, scopeFor('a', 'b.example').key);
  library.uninstall('example.alex'); assert.equal(library.selected('save-a').characterId, DEFAULT_CHARACTER_ID);
  assert.deepEqual(library.readScope('save-a', 'example.alex').messages, ['private']);
});
test('switch cancels all output and invalidates old token; invalid selection preserves active session', t => {
  const { library } = setup(t); library.importZip(zip(manifest())); let stops = 0; let outputs = 0;
  const session = new CharacterSession({ library, cancel: [() => stops++, () => { throw Error('cancel failure'); }] });
  const first = session.activate('save-a'); const second = session.activate('save-a', 'example.alex');
  assert.equal(first.signal.aborted, true); assert.equal(session.guard(first, () => outputs++), false);
  assert.equal(session.guard(second, () => outputs++), true); assert.equal(outputs, 1); assert.equal(stops, 2);
  assert.throws(() => session.activate('save-a', 'unknown.person')); assert.equal(session.accepts(second), true);
  session.dispose(); assert.equal(session.accepts(second), false);
});
test('legacy migration backs up exact source, preserves edits, archives unknown save and is idempotent', t => {
  const { root, library } = setup(t); const personaFile = path.join(root, 'old-persona.md'), settingsFile = path.join(root, 'old-settings.json');
  fs.writeFileSync(personaFile, 'Existing custom persona'); const legacy = { version: 1, preferences: { ttsProvider: 'edge' }, memories: [{ text: 'private' }], messages: [{ text: 'old' }] }; fs.writeFileSync(settingsFile, JSON.stringify(legacy));
  const first = migrateLegacyCharacter({ library, personaFile, settingsFile });
  assert.equal(library.resolve().persona, 'Existing custom persona'); assert.equal(library.resolve().voice.provider, 'edge');
  assert.deepEqual(JSON.parse(fs.readFileSync(first.archivePath)), legacy); assert.equal(first.assignedSaveId, null);
  assert.deepEqual(library.readScope('new-save', DEFAULT_CHARACTER_ID).messages, []);
  library.setOverrides(DEFAULT_CHARACTER_ID, { persona: 'Later user edit' });
  fs.writeFileSync(personaFile, 'Changed outside'); assert.deepEqual(migrateLegacyCharacter({ library, personaFile, settingsFile }), first);
  assert.equal(library.resolve().persona, 'Later user edit');
});
test('verified legacy save can receive history, but no cross-save copies', t => {
  const { root, library } = setup(t); const settingsFile = path.join(root, 'old.json'); fs.writeFileSync(settingsFile, JSON.stringify({ version: 1, messages: ['old'], memories: ['old memory'] }));
  migrateLegacyCharacter({ library, settingsFile, verifiedSaveId: 'verified' });
  assert.deepEqual(library.readScope('verified', DEFAULT_CHARACTER_ID).messages, ['old']);
  assert.deepEqual(library.readScope('other', DEFAULT_CHARACTER_ID).messages, []);
});
test('rejects linked user roots and PNG overrides', t => {
  const { root, library } = setup(t); assert.throws(() => library.setOverrides(DEFAULT_CHARACTER_ID, { portraitPng: Buffer.from('not png') }));
  if (process.platform !== 'win32') { const linked = path.join(root, 'linked'); fs.symlinkSync(root, linked); assert.throws(() => new CharacterLibrary({ root: linked })); }
});
test('trusted root tolerates OS ancestor aliases but package and override links remain forbidden', t => {
  if (process.platform === 'win32') return;
  const outer = fs.mkdtempSync(path.join(os.tmpdir(), 'fa-os-alias-')); t.after(() => fs.rmSync(outer, { recursive: true, force: true }));
  const physical = path.join(outer, 'physical'); fs.mkdirSync(physical); const alias = path.join(outer, 'os-alias'); fs.symlinkSync(physical, alias);
  const root = path.join(alias, 'user-data', 'characters'); const library = new CharacterLibrary({ root });
  assert.equal(library.root, fs.realpathSync(root)); assert.equal(library.resolve().characterId, DEFAULT_CHARACTER_ID);
  const original = path.join(alias, 'user-data', 'old-persona.md'); fs.writeFileSync(original, 'Keep my legacy persona');
  migrateLegacyCharacter({ library, personaFile: original }); assert.equal(library.resolve().persona, 'Keep my legacy persona');
  const overrideFile = path.join(library.root, 'overrides', DEFAULT_CHARACTER_ID, 'override.json'); fs.unlinkSync(overrideFile); fs.symlinkSync(original, overrideFile);
  assert.equal(library.resolve().warnings.includes('override_unavailable'), true);
  assert.throws(() => library.setOverrides(DEFAULT_CHARACTER_ID, { persona: 'Do not follow inner link' }));
  assert.equal(fs.readFileSync(original, 'utf8'), 'Keep my legacy persona');
  const symlinkRoot = path.join(alias, 'linked-root'); fs.symlinkSync(library.root, symlinkRoot); assert.throws(() => new CharacterLibrary({ root: symlinkRoot }));
  const { readTrustedFile } = require('../src/character-library.cjs');
  const linkedFile = path.join(alias, 'linked-persona.md'); fs.symlinkSync(original, linkedFile); assert.throws(() => readTrustedFile(linkedFile, 16384));
});
