'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createPersonaAccess } = require('../src/persona-access.cjs');
async function fixture(t) {
  const userData = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'fa-persona-open-')));
  t.after(() => fs.rm(userData, { recursive: true, force: true }));
  const directory = path.join(userData, 'backend'), file = path.join(directory, 'persona.md');
  await fs.mkdir(directory); await fs.writeFile(file, 'TEST persona unchanged');
  const opened = [];
  const raw = { path: file, status: 'ready', created: true, body: 'must not reach renderer', apiKey: 'must not reach renderer' };
  let managed = true;
  const access = createPersonaAccess({ userData, isManaged: () => managed, getMetadata: async () => raw, openPath: async value => { opened.push(value); return ''; } });
  return { access, raw, opened, file, directory, setManaged: value => { managed = value; } };
}
test('opens only fixed managed persona file/folder; metadata never returns body or secret', async t => {
  const f = await fixture(t); const result = await f.access.status();
  assert.equal(result.canOpen, true); assert.equal(Object.hasOwn(result, 'body'), false); assert.equal(Object.hasOwn(result, 'apiKey'), false);
  await f.access.open('file'); await f.access.open('folder');
  assert.deepEqual(f.opened, [f.file, f.directory]);
  assert.equal(await fs.readFile(f.file, 'utf8'), 'TEST persona unchanged');
  await assert.rejects(f.access.open('/tmp/arbitrary-script'));
});
test('external, fallback, missing and substituted metadata paths never open', async t => {
  const f = await fixture(t);
  f.setManaged(false); assert.equal((await f.access.status()).external, true); await assert.rejects(f.access.open('file'));
  f.setManaged(true); f.raw.status = 'fallback'; await assert.rejects(f.access.open('folder'));
  f.raw.status = 'ready'; f.raw.path = path.join(f.directory, 'other.md'); await assert.rejects(f.access.open('file'));
  f.raw.path = f.file; await fs.rm(f.file); await assert.rejects(f.access.open('file'));
  assert.deepEqual(f.opened, []);
});
test('symlink and oversized persona are rejected even when backend claims ready', async t => {
  const f = await fixture(t); const other = path.join(f.directory, 'other.md');
  await fs.writeFile(other, 'TEST'); await fs.rm(f.file);
  try {
    await fs.symlink(other, f.file);
    await assert.rejects(f.access.open('file'));
  } catch (error) {
    if (process.platform !== 'win32' || error.code !== 'EPERM') throw error;
    t.diagnostic('Windows symlink creation unavailable without developer mode; oversized-file case still checked.');
  }
  await fs.rm(f.file, { force: true }); await fs.writeFile(f.file, 'x'.repeat(16385));
  await assert.rejects(f.access.open('file')); assert.deepEqual(f.opened, []);
});
test('open action rechecks metadata rather than relying on previously rendered state', async t => {
  const f = await fixture(t); assert.equal((await f.access.status()).canOpen, true);
  f.raw.status = 'fallback'; await assert.rejects(f.access.open('file')); assert.deepEqual(f.opened, []);
});
test('editor reads current content and explicit save reloads without replacing defaults on read', async t => {
  const f = await fixture(t); const before = await f.access.read();
  assert.equal(before.content, 'TEST persona unchanged'); assert.equal(before.canEdit, true);
  assert.match(before.revision, /^[a-f0-9]{64}$/);
  const saved = await f.access.save({ content: 'TEST new style 中文', revision: before.revision });
  assert.equal(saved.content, 'TEST new style 中文'); assert.notEqual(saved.revision, before.revision);
  assert.equal(saved.reload, 'next_request');
  assert.equal(await fs.readFile(f.file, 'utf8'), 'TEST new style 中文');
  assert.deepEqual((await fs.readdir(f.directory)).sort(), ['persona.md']);
});
test('stale revision preserves external editor changes', async t => {
  const f = await fixture(t); const before = await f.access.read();
  await fs.writeFile(f.file, 'TEST external edit');
  await assert.rejects(f.access.save({ content: 'TEST stale draft', revision: before.revision }), /别处修改/);
  assert.equal(await fs.readFile(f.file, 'utf8'), 'TEST external edit');
});
test('only exact bounded UTF8 save schema is accepted', async t => {
  const f = await fixture(t); const before = await f.access.read();
  for (const content of ['', '  ', '\0', '\ud800', '汉'.repeat(6000), 'x'.repeat(16385), 1])
    await assert.rejects(f.access.save({ content, revision: before.revision }));
  await assert.rejects(f.access.save({content:'TEST',revision:before.revision,path:'/tmp/elsewhere'}));
  await assert.rejects(f.access.save({content:'TEST',revision:'bad'}));
  assert.equal(await fs.readFile(f.file, 'utf8'), before.content);
});
test('hardlinks are neither editable nor openable', async t => {
  const f = await fixture(t); await fs.link(f.file, path.join(f.directory, 'linked.md'));
  assert.equal((await f.access.read()).canEdit, false);
  await assert.rejects(f.access.open('file'));
  await assert.rejects(f.access.save({content:'TEST',revision:'a'.repeat(64)}));
});
test('external backend does not expose file contents or accept saves', async t => {
  const f = await fixture(t); f.setManaged(false);
  const value = await f.access.read(); assert.equal(value.content, null); assert.equal(value.canEdit, false);
  await assert.rejects(f.access.save({content:'TEST',revision:'a'.repeat(64)}));
  assert.equal(await fs.readFile(f.file, 'utf8'), 'TEST persona unchanged');
});
test('parallel saves cannot silently overwrite a newer app edit', async t => {
  const f = await fixture(t); const before = await f.access.read();
  const outcomes = await Promise.allSettled(['TEST A','TEST B'].map(content => f.access.save({content,revision:before.revision})));
  assert.equal(outcomes.filter(v=>v.status==='fulfilled').length,1);
  assert.equal(outcomes.filter(v=>v.status==='rejected').length,1);
  assert.deepEqual(await fs.readdir(f.directory), ['persona.md']);
});
test('invalid UTF8 is not repaired or overwritten during editor read', async t => {
  const f = await fixture(t); const bytes = Buffer.from([0xff,0xfe,0x41]); await fs.writeFile(f.file,bytes);
  await assert.rejects(f.access.read()); assert.deepEqual(await fs.readFile(f.file),bytes);
});
