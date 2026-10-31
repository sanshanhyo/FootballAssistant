'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
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
      value.canOpen = dirStat.isDirectory() && !dirStat.isSymbolicLink() && fileStat.isFile() && !fileStat.isSymbolicLink() && fileStat.size <= 16384 && canonicalFile === path.join(canonicalRoot, 'backend', 'persona.md');
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
  return { status, open };
}
module.exports = { createPersonaAccess };
