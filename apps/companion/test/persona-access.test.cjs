'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createPersonaAccess } = require('../src/persona-access.cjs');
async function fixture(t) {
  const userData = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-persona-open-'));
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
