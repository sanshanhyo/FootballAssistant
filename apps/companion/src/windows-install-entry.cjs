'use strict';
// Loaded only from main's earliest installer-command branch; creates no windows/backend.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { installWindowsReaders, installErrorMessage } = require('./windows-install-once.cjs');
function parseInstallArguments(argv) {
  const start = argv.indexOf('--fa-install-readers');
  if (start < 0) throw Error('缺少安装命令，请从正式安装程序启动。');
  const options = { gamePath: '', silent: false, resultFile: '' }, seen = new Set();
  for (let i = start + 1; i < argv.length; i++) {
    const flag = argv[i];
    if (seen.has(flag)) throw Error('安装参数重复，请重新启动安装程序。'); seen.add(flag);
    if (flag === '--silent') { options.silent = true; continue; }
    if (!['--game-path', '--result-file'].includes(flag) || i + 1 >= argv.length || argv[i + 1].startsWith('--')) throw Error('安装参数无效，请重新启动安装程序。');
    options[flag === '--game-path' ? 'gamePath' : 'resultFile'] = argv[++i];
  }
  if (!options.resultFile || !path.isAbsolute(options.resultFile) || /[\0\r\n]/.test(options.resultFile)) throw Error('缺少有效的临时结果文件路径，请重新启动安装程序。');
  return options;
}
async function openResult(file) {
  const temporaryRoot = await fs.realpath(os.tmpdir());
  let cursor = path.dirname(file);
  for (;;) {
    const stat = await fs.lstat(cursor);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('临时结果目录无效或包含链接，已停止安装。');
    const parent = path.dirname(cursor); if (parent === cursor) break; cursor = parent;
  }
  const parent = await fs.realpath(path.dirname(file));
  const relative = path.relative(temporaryRoot, parent);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw Error('安装结果文件必须位于当前用户的临时目录。');
  const target = path.join(parent, path.basename(file));
  let handle;
  try {
    const before = await fs.lstat(target);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > 65536) throw Error('临时结果文件不安全，已停止安装。');
    handle = await fs.open(target, 'r+');
    const opened = await handle.stat();
    if (opened.ino !== before.ino || opened.dev !== before.dev || opened.nlink !== 1) throw Error('临时结果文件已发生变化，已停止安装。');
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
      result = { code: 3, message: '请先退出 FootballAssistant 桌宠，再安装读取组件。', gamePath: options.gamePath, userData };
    } else {
      await app.whenReady();
      result = await installWindowsReaders({ userData, resourcesPath: process.resourcesPath, gamePath: options.gamePath,
        silent: options.silent, finalize: publish, confirmException: async exception => {
          if (options.silent) return false;
          const messages = {
            game_running: 'FM 仍在运行。请先保存游戏并自行退出 FM，再点“重试”。安装程序不会强制结束游戏。',
            loader_migration: '检测到旧加载器。是否备份并仅替换下面列出的文件？其它 Mod 和旧加载器指向的外部文件不会被删除。\n' + (exception.files || []).join('\n'),
            shared_config: '是否对已有 BepInEx 共享配置应用以下三项受限修改？清空 Unity 基库下载源、启用本机互操作文件更新、关闭 Unity 日志转发。其它设置和注释保持不变。\n' + (exception.fields || []).join('\n'),
          };
          const answer = await dialog.showMessageBox({ type: 'warning', title: 'FootballAssistant 安装',
            message: messages[exception.type] || '安装遇到需要确认的情况，请检查后继续。',
            buttons: [exception.type === 'game_running' ? '重试' : '确认', '取消'], defaultId: 1, cancelId: 1, noLink: true });
          return answer.response === 0;
        } });
    }
    if (result.code !== 0) await publish(result);
    return result.code;
  } catch (error) {
    result = { code: 4, message: installErrorMessage(error), gamePath: options?.gamePath || '', userData };
    if (handle) { try { const bytes = encodeResult(result); await handle.truncate(0); await handle.write(bytes, 0, bytes.length, 0); await handle.sync(); } catch {} }
    return result.code;
  } finally { await handle?.close(); if (lock) app.releaseSingleInstanceLock(); }
}
module.exports = { runWindowsInstallEntry, parseInstallArguments };
