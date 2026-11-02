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
function createWindowsMatchSetup({ userData, installer, packaged, platform = process.platform, chooseGame, inspectSelectedGame = inspectGame,
  requestMatch, probeGame = () => detectGame(platform), onConfigured = async () => ({}), now = Date.now }) {
  let pending = null, selected = null, busy = false, waitingSince = null, lastInspection = null;
  const supported = platform === 'win32' && packaged;
  const exclusive = async action => { if (busy) throw Error('比赛组件操作正在进行，请稍候。'); busy = true; try { return await action(); } finally { busy = false; } };
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
    catch (error) { return { supported: true, state: 'deployment_error', error: error.message, code: error.code, dataConnected: false }; }
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
      if (!supported || !input || Object.keys(input).some(k => !['planId','confirm','migrateLoader','allowFirstRunDownload'].includes(k)) || input.confirm !== true || input.allowFirstRunDownload !== true || typeof input.migrateLoader !== 'boolean' || !pending || pending.planId !== input.planId) throw Error('请确认当前部署计划、首次启动联网下载及互操作生成说明。');
      const plan = pending; pending = null; lastInspection = null;
      const installed = await installer.deploy({ planId: plan.planId, confirmationToken: plan.confirmationToken, confirm: true, migrateLoader: input.migrateLoader });
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
