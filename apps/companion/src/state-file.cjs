'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const queues = new Map();
const revision = bytes => createHash('sha256').update(bytes).digest('hex');
async function readStateFile(file, limit = 2_000_000) {
  try {
    const stat = await fs.lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > limit) throw Error('State file must be a bounded regular file');
    const bytes = await fs.readFile(file);
    if (bytes.length > limit) throw Error('State file exceeds limit');
    return { bytes, revision: revision(bytes) };
  } catch (error) { if (error.code === 'ENOENT') return { bytes: null, revision: null }; throw error; }
}
function writeStateFile(file, value, expectedRevision) {
  if (Buffer.byteLength(value, 'utf8') > 2_000_000) return Promise.reject(Error('State file exceeds limit; existing data is unchanged'));
  const key = process.platform === 'win32' ? path.resolve(file).toLowerCase() : path.resolve(file);
  const operation = (queues.get(key) || Promise.resolve()).catch(() => {}).then(async () => {
    await fs.mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
    if ((await readStateFile(file)).revision !== expectedRevision) throw Error('State changed outside this instance; preserve both versions and reload');
    const temporary = `${file}.${randomUUID()}.tmp`;
    let handle;
    try {
      handle = await fs.open(temporary, 'wx', 0o600);
      await handle.writeFile(value); await handle.sync(); await handle.close(); handle = null;
      if ((await readStateFile(file)).revision !== expectedRevision) throw Error('State changed before replacement');
      await fs.rename(temporary, file);
      if (process.platform !== 'win32') {
        const dir = await fs.open(path.dirname(file), 'r'); try { await dir.sync(); } finally { await dir.close(); }
      }
      return revision(value);
    } finally { await handle?.close(); await fs.rm(temporary, { force: true }); }
  });
  queues.set(key, operation);
  operation.finally(() => { if (queues.get(key) === operation) queues.delete(key); }).catch(() => {});
  return operation;
}
module.exports = { readStateFile, writeStateFile };
