'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { constants } = require('node:fs');
const { createHash, randomUUID } = require('node:crypto');
const MAX_BYTES = 16384;
const revision = bytes => createHash('sha256').update(bytes).digest('hex');
const ordinary = info => info.isFile() && !info.isSymbolicLink() && info.nlink === 1;
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;
function validateText(content) {
  if (typeof content !== 'string' || !content.trim() || content.includes('\0') || !content.isWellFormed() || Buffer.byteLength(content, 'utf8') > MAX_BYTES)
    throw Error('人设须为非空 UTF-8 文本，且不超过 16 KiB。');
  return Buffer.from(content, 'utf8');
}
// No renderer-provided paths. The authenticated API contributes metadata only.
function createPersonaAccess({ userData, isManaged, getMetadata, openPath }) {
  const directory = path.join(userData, 'backend');
  const file = path.join(directory, 'persona.md');
  async function status() {
    const raw = await getMetadata();
    const value = {
      path: typeof raw?.path === 'string' && raw.path.length <= 8192 ? raw.path : null,
      status: raw?.status === 'ready' ? 'ready' : 'fallback',
      reason: typeof raw?.reason === 'string' ? raw.reason.slice(0, 160) : null,
      created: raw?.created === true, using_default: raw?.using_default === true,
      max_bytes: 16384, encoding: 'UTF-8', reload: 'next_request',
      external: !isManaged(), canOpen: false,
    };
    if (value.external || value.status !== 'ready' || value.path !== file) return value;
    try {
      const [dirStat, fileStat, canonicalRoot, canonicalFile] = await Promise.all([fs.lstat(directory), fs.lstat(file), fs.realpath(userData), fs.realpath(file)]);
      value.canOpen = dirStat.isDirectory() && !dirStat.isSymbolicLink() && ordinary(fileStat) && fileStat.size <= 16384 && canonicalFile === path.join(canonicalRoot, 'backend', 'persona.md');
    } catch { value.canOpen = false; }
    return value;
  }
  async function open(kind) {
    if (!['file', 'folder'].includes(kind)) throw Error('不支持的人设打开操作。');
    const current = await status();
    if (!current.canOpen) throw Error('无法安全打开此人设路径；外部服务请在后端所在机器编辑。');
    const error = await openPath(kind === 'file' ? file : directory);
    if (error) throw Error('系统未能打开人设文件或文件夹，请检查默认文本编辑器。');
    return { opened: true };
  }
  // Serialize app-originated saves; outside-editor changes are detected by content revision
  // immediately before atomic replacement. No renderer filename/path is ever accepted.
  let saving = false;
  async function safeParents() {
    let cursor = directory;
    while (true) {
      const info = await fs.lstat(cursor);
      if (!info.isDirectory() || info.isSymbolicLink()) throw Error('人设目录不安全。');
      const parent = path.dirname(cursor); if (parent === cursor) break; cursor = parent;
    }
    const real = await fs.realpath(file);
    if (real !== path.join(await fs.realpath(userData), 'backend', 'persona.md')) throw Error('人设路径已改变。');
  }
  async function snapshot() {
    const current = await status();
    if (!current.canOpen) throw Error('当前人设文件不能在此编辑。');
    await safeParents();
    const before = await fs.lstat(file);
    if (!ordinary(before) || before.size > MAX_BYTES) throw Error('人设文件不安全。');
    const handle = await fs.open(file, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    try {
      const opened = await handle.stat();
      if (!ordinary(opened) || !sameFile(before, opened)) throw Error('人设文件已改变，请刷新。');
      const bytes = Buffer.alloc(MAX_BYTES + 1);
      const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
      const payload = bytes.subarray(0, bytesRead);
      await safeParents();
      const after = await fs.lstat(file);
      if (!ordinary(after) || !sameFile(opened, after) || after.size !== bytesRead || bytesRead > MAX_BYTES)
        throw Error('人设文件已改变或超出限制，请刷新。');
      const content = new TextDecoder('utf-8', { fatal: true }).decode(payload);
      validateText(content);
      return { current, content, revision: revision(payload), identity: after };
    } finally { await handle.close(); }
  }
  async function read() {
    const current = await status();
    if (!current.canOpen) return { ...current, content: null, revision: null, canEdit: false };
    const value = await snapshot();
    return { ...value.current, content: value.content, revision: value.revision, canEdit: true };
  }
  async function save(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input) ||
        Object.keys(input).sort().join(',') !== 'content,revision' ||
        typeof input.revision !== 'string' || !/^[a-f0-9]{64}$/.test(input.revision)) throw Error('无效的人设保存请求。');
    const bytes = validateText(input.content);
    if (saving) throw Error('正在保存人设，请稍后刷新。');
    saving = true;
    const temporary = path.join(directory, `.persona-${randomUUID()}.tmp`);
    try {
      const original = await snapshot();
      if (original.revision !== input.revision) throw Error('人设已在别处修改，请刷新后再保存。');
      const handle = await fs.open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW || 0), 0o600);
      try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
      const latest = await snapshot();
      if (latest.revision !== input.revision || !sameFile(original.identity, latest.identity))
        throw Error('人设已在别处修改，请刷新后再保存。');
      await fs.rename(temporary, file);
      return await read();
    } finally { await fs.rm(temporary, { force: true }).catch(() => {}); saving = false; }
  }
  return { status, open, read, save };
}
module.exports = { createPersonaAccess };
