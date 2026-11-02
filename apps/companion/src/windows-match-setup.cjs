'use strict';
// Main-process coordination only. File deployment is owned by the transactional installer.
const fs = require('node:fs/promises');
const path = require('node:path');
const { loadSettings, validateSettings, detectGame } = require('./bootstrap.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const { inspectGame } = require('./windows-reader-setup.cjs');
async function trustedMatchPath(userData, value) {
  const root = await fs.realpath(userData);
  const expected = path.join(root, 'match-reader', 'active', 'match.json');
  if (typeof value !== 'string' || !path.isAbsolute(value) || path.basename(value) !== 'match.json' || path.join(await fs.realpath(path.dirname(value)), 'match.json') !== expected) throw Error('比赛输出路径与本机专用目录不一致。');
  return expected;
}
async function loaderProgress(gamePath) {
  if (!gamePath) return null;
  const log = path.join(path.dirname(gamePath), 'BepInEx', 'LogOutput.log');
  let handle;
  try {
    const stat = await fs.lstat(log);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || Date.now() - stat.mtimeMs > 600000) return null;
    handle = await fs.open(log, 'r');
    const buffer = Buffer.alloc(Math.min(stat.size, 65536));
    await handle.read(buffer, 0, buffer.length, Math.max(0, stat.size - buffer.length));
    const text = buffer.toString('utf8');
    const phase = /(?:generat.*interop|Cpp2IL|Il2CppInterop)/i.test(text) ? 'generating_interop' : /(?:download|Unity.*libraries)/i.test(text) ? 'downloading_unity' : 'loader_started';
    return { phase, updatedAt: new Date(stat.mtimeMs).toISOString(), errorRecorded: /\[Error\s*:|fatal|failed to download|failed to generate/i.test(text) };
  } catch { return null; } finally { await handle?.close(); }
}
function deploymentError(error) {
  const messages = { game_running: '请先退出 FM，再部署或回滚比赛组件。', game_state_unknown: '无法确认 FM 是否退出，未修改游戏。', unsupported_game_binary: '当前游戏版本不受支持，未修改游戏。', loader_conflict: '发现不兼容加载器或他人组件，不能覆盖。', migration_consent_required: '请单独确认备份并替换列出的旧加载器。', confirmation_required: '部署计划已失效或尚未确认，请重新生成计划。', plan_changed: '文件在确认后发生变化，请重新生成计划。', rollback_file_modified: '部署后的文件已被修改，回滚已停止，不会覆盖这些文件。', backup_integrity_failed: '备份校验失败，未覆盖游戏文件。', payload_integrity_failed: '内置组件校验失败，请安装完整软件包。', payload_identity_invalid: '内置组件版本不匹配，请安装完整软件包。', unsafe_file: '检测到不安全或被链接的文件，操作已停止。', unsafe_directory: '检测到不安全或被链接的目录，操作已停止。', recovery_required: '上次操作未完成，请先回滚恢复。', EACCES: '没有文件写入权限，未提升权限或绕过限制。', EPERM: '文件不可写或被占用，请退出游戏后检查权限。' };
  return Object.assign(Error(messages[error.code] || error.message || '比赛组件操作失败。'), { code: error.code });
}
function createWindowsMatchSetup({ userData, installer, packaged, platform = process.platform, chooseGame, inspectSelectedGame = inspectGame,
  requestMatch, probeGame = () => detectGame(platform), onConfigured = async () => ({}), now = Date.now }) {
  let pending = null, selected = null, busy = false, waitingSince = null, lastInspection = null;
  const supported = platform === 'win32' && packaged;
  const exclusive = async action => { if (busy) throw Error('比赛组件操作正在进行，请稍候。'); busy = true; try { return await action(); } catch (error) { throw deploymentError(error); } finally { busy = false; } };
  const publicValue = value => { const { confirmationToken, ...rest } = value || {}; return rest; };
  async function persist(enabled, gamePath, snapshotPath = '') {
    const file = path.join(userData, 'settings.json');
    const settings = await loadSettings(userData); const before = await readStateFile(file, 16384);
    const matchFile = enabled ? await trustedMatchPath(userData, snapshotPath) : '';
    const next = validateSettings({ ...settings, windowsMatchEnabled: enabled, windowsMatchGamePath: gamePath || settings.windowsMatchGamePath || '' });
    await writeStateFile(file, JSON.stringify(next, null, 2) + '\n', before.revision);
    return onConfigured({ enabled, matchFile });
  }
  async function status({ verify = false } = {}) {
    if (!supported) return { supported: false, state: 'unsupported_platform', dataConnected: false };
    const settings = await loadSettings(userData);
    let install;
    try {
      // Poll only current process-bound status; do not rehash a 400+ MiB game DLL every two seconds.
      install = verify && lastInspection ? lastInspection : await installer.inspect(selected || settings.windowsMatchGamePath || settings.windowsReaderGamePath || undefined);
      if (!verify) lastInspection = install;
    }
    catch (error) { return { supported: true, state: 'deployment_error', error: deploymentError(error).message, code: error.code, dataConnected: false }; }
    const result = { ...publicValue(install), supported: true, enabled: settings.windowsMatchEnabled === true, dataConnected: false };
    if (install.state !== 'deployed') return result;
    await trustedMatchPath(userData, install.snapshotPath);
    if (!result.enabled) return { ...result, state: 'deployed_unconfigured', canConnect: true };
    if (!verify) return { ...result, state: 'deployed', canVerify: true };
    const game = await probeGame();
    if (game?.state === 'not_detected' || game?.running === false || game === false) { waitingSince = null; return { ...result, state: 'waiting_game', canVerify: true }; }
    if (!(game?.state === 'running' || game?.running === true || game === true)) return { ...result, state: 'game_state_unknown', canVerify: true };
    waitingSince ??= now();
    let envelope;
    try { envelope = await requestMatch(); } catch (error) { return { ...result, state: 'backend_unavailable', error: error.message, canVerify: true }; }
    if (envelope?.producerVerified === true && envelope?.snapshot?.status === 'live') { waitingSince = null; return { ...result, state: 'live', dataConnected: true, readerStatus: envelope.readerStatus, canVerify: true }; }
    const reader = envelope?.readerStatus;
    if (reader) {
      if (reader.state === 'hook_timeout') return { ...result, state: 'hook_timeout', readerStatus: reader, canVerify: true };
      if (reader.state === 'stopped') return { ...result, state: 'plugin_stopped', readerStatus: reader, canVerify: true };
      if (reader.state === 'hook_installed') { waitingSince = null; return { ...result, state: 'loaded_waiting_match', readerStatus: reader, canVerify: true }; }
    }
    return { ...result, state: now() - waitingSince >= 180000 ? 'loading_timeout' : 'loading', readerStatus: reader || null, loaderProgress: await loaderProgress(install.gamePath), canVerify: true };
  }
  async function gamePath() {
    const settings = await loadSettings(userData);
    let candidate = selected || settings.windowsMatchGamePath || settings.windowsReaderGamePath;
    if (!candidate) candidate = await chooseGame();
    if (!candidate) return null;
    const checked = await inspectSelectedGame(candidate); selected = checked.gamePath; return selected;
  }
  return {
    status,
    select: () => exclusive(async () => { pending = null; lastInspection = null; if (!supported) throw Error('此平台没有可部署的 Windows 比赛组件。'); const candidate = await chooseGame(); if (!candidate) return { cancelled: true }; selected = (await inspectSelectedGame(candidate)).gamePath; pending = null; return { ...await status(), gamePath: selected }; }),
    plan: () => exclusive(async () => { pending = null; lastInspection = null; if (!supported) throw Error('此平台没有可部署的 Windows 比赛组件。'); const game = await gamePath(); if (!game) return { cancelled: true }; pending = await installer.plan(game); return { ...publicValue(pending), supported: true }; }),
    deploy: input => exclusive(async () => {
      if (!supported || !input || Object.keys(input).some(k => !['planId','confirm','migrateLoader','confirmOfflineGeneration','confirmSharedConfig'].includes(k)) || input.confirm !== true || input.confirmOfflineGeneration !== true || typeof input.migrateLoader !== 'boolean' || !pending || pending.planId !== input.planId) throw Error('请确认当前部署计划、本机离线互操作生成说明。');
      const plan = pending; pending = null; lastInspection = null;
      const installed = await installer.deploy({ planId: plan.planId, confirmationToken: plan.confirmationToken, confirm: true, migrateLoader: input.migrateLoader, confirmSharedConfig: input.confirmSharedConfig === true });
      const configured = await persist(true, installed.gamePath, installed.snapshotPath); waitingSince = null;
      return { ...await status(), ...configured, state: 'deployed', needsGameStart: true };
    }),
    connect: () => exclusive(async () => { const current = await status(); if (!supported || !['deployed','deployed_unconfigured'].includes(current.state)) throw Error('请先完成完整组件部署。'); const configured = await persist(true, current.gamePath, current.snapshotPath); return { ...await status(), ...configured }; }),
    verify: () => status({ verify: true }),
    retry: () => { waitingSince = null; return status({ verify: true }); },
    rollback: input => exclusive(async () => { if (!supported || !input || Object.keys(input).join(',') !== 'confirm' || input.confirm !== true) throw Error('请先确认回滚比赛组件。'); pending = null; lastInspection = null; const restored = await installer.rollback({ confirm: true }); const configured = await persist(false, ''); waitingSince = null; return { ...publicValue(restored), ...configured, supported: true, enabled: false, dataConnected: false }; }),
  };
}
module.exports = { createWindowsMatchSetup, trustedMatchPath, loaderProgress };
