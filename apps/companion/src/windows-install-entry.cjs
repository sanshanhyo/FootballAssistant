'use strict';
// Loaded only from main's earliest installer-command branch; creates no windows/backend.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { installWindowsReaders } = require('./windows-install-once.cjs');
function parseInstallArguments(argv) {
  const start = argv.indexOf('--fa-install-readers');
  if (start < 0) throw Error('Missing installer command.');
  const options = { gamePath: '', silent: false, resultFile: '' }, seen = new Set();
  for (let i = start + 1; i < argv.length; i++) {
    const flag = argv[i];
    if (seen.has(flag)) throw Error('Duplicate installer argument.'); seen.add(flag);
    if (flag === '--silent') { options.silent = true; continue; }
    if (!['--game-path', '--result-file'].includes(flag) || i + 1 >= argv.length || argv[i + 1].startsWith('--')) throw Error('Invalid installer arguments.');
    options[flag === '--game-path' ? 'gamePath' : 'resultFile'] = argv[++i];
  }
  if (!options.resultFile || !path.isAbsolute(options.resultFile) || /[\0\r\n]/.test(options.resultFile)) throw Error('An absolute temporary result-file is required.');
  return options;
}
async function openResult(file) {
  const temporaryRoot = await fs.realpath(os.tmpdir());
  let cursor = path.dirname(file);
  for (;;) {
    const stat = await fs.lstat(cursor);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('Result directory is linked or invalid.');
    const parent = path.dirname(cursor); if (parent === cursor) break; cursor = parent;
  }
  const parent = await fs.realpath(path.dirname(file));
  const relative = path.relative(temporaryRoot, parent);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Result file must be inside the current user temporary directory.');
  const target = path.join(parent, path.basename(file));
  let handle;
  try {
    const before = await fs.lstat(target);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > 65536) throw Error('Unsafe result file.');
    handle = await fs.open(target, 'r+');
    const opened = await handle.stat();
    if (opened.ino !== before.ino || opened.dev !== before.dev || opened.nlink !== 1) throw Error('Result file changed.');
  } catch (error) { if (error.code !== 'ENOENT') { await handle?.close(); throw error; } handle = await fs.open(target, 'wx+', 0o600); }
  return handle;
}
function encodeResult(result) {
  const clean = value => String(value ?? '').replace(/[\0\r\n]/g, ' ').slice(0, 4096);
  return Buffer.from('\ufeff[result]\r\n' + ['code', 'message', 'gamePath', 'userData'].map(key => `${key}=${clean(result[key])}\r\n`).join(''), 'utf16le');
}
async function runWindowsInstallEntry({ app, dialog, argv = process.argv }) {
  let handle, lock = false, options, result;
  const userData = app.getPath('userData'); // Never supplied by argv, registry, NSIS or caller settings.
  try {
    options = parseInstallArguments(argv);
    handle = await openResult(options.resultFile);
    const publish = async value => { const bytes = encodeResult(value); await handle.truncate(0); await handle.write(bytes, 0, bytes.length, 0); await handle.sync(); };
    lock = app.requestSingleInstanceLock();
    if (!lock) {
      result = { code: 3, message: 'Close FootballAssistant before installing readers.', gamePath: options.gamePath, userData };
    } else {
      await app.whenReady();
      result = await installWindowsReaders({ userData, resourcesPath: process.resourcesPath, gamePath: options.gamePath,
        silent: options.silent, finalize: publish, confirmException: async exception => {
          if (options.silent) return false;
          const messages = {
            game_running: 'Please close FM yourself, then choose Retry. The installer will not terminate the game.',
            loader_migration: 'Back up and replace only these existing loader files? Other mods and external loader targets will not be deleted.\n' + (exception.files || []).join('\n'),
            shared_config: 'Apply these three no-download settings to the existing shared BepInEx configuration? All other settings and comments are preserved.\n' + (exception.fields || []).join('\n'),
          };
          const answer = await dialog.showMessageBox({ type: 'warning', title: 'FootballAssistant installation',
            message: messages[exception.type] || 'Installation needs review.',
            buttons: [exception.type === 'game_running' ? 'Retry' : 'Confirm', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true });
          return answer.response === 0;
        } });
    }
    if (result.code !== 0) await publish(result);
    return result.code;
  } catch (error) {
    result = { code: 4, message: error.message, gamePath: options?.gamePath || '', userData };
    if (handle) { try { const bytes = encodeResult(result); await handle.truncate(0); await handle.write(bytes, 0, bytes.length, 0); await handle.sync(); } catch {} }
    return result.code;
  } finally { await handle?.close(); if (lock) app.releaseSingleInstanceLock(); }
}
module.exports = { runWindowsInstallEntry, parseInstallArguments };
