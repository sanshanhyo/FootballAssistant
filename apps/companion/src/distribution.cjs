'use strict';
const fs = require('node:fs');
const path = require('node:path');
// Installer-created marker identifies channel only. It cannot grant update trust.
function distribution({ platform = process.platform, packaged, executable, env = process.env }) {
  if (platform !== 'win32' || !packaged) return 'unknown';
  if (env.PORTABLE_EXECUTABLE_FILE || env.PORTABLE_EXECUTABLE_DIR) return 'portable';
  try {
    const marker = path.join(path.dirname(executable), 'installation.json');
    const info = fs.lstatSync(marker);
    if (!info.isFile() || info.isSymbolicLink() || info.size > 256) return 'unknown';
    const value = JSON.parse(fs.readFileSync(marker, 'utf8'));
    return value.schema === 1 && value.distribution === 'nsis' && Object.keys(value).length === 2 ? 'nsis' : 'unknown';
  } catch { return 'unknown'; }
}
module.exports = { distribution };
