'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { loadSettings, validateSettings } = require('./bootstrap.cjs');
function createBridgeSetup({ userData, resourcesPath, isPackaged, platform = process.platform, onConfigured = async () => {}, requestHealth = async () => null, run = promisify(execFile) }) {
  let busy = false;
  const binary = path.join(resourcesPath, 'backend', platform === 'win32' ? 'football-assistant-backend.exe' : 'football-assistant-backend');
  const payload = path.join(resourcesPath, 'bridge-macos-arm64');
  const unavailable = state => ({ state, canEnable: false, canRollback: false, dataConnected: false,
    message: state === 'unsupported_platform' ? '当前平台尚无已验证的普通用户游戏桥接部署；不会安装或修改游戏。' : '此版本未包含审计后的桥接组件，不能部署。' });
  async function invoke(action, extra = []) {
    if (platform !== 'darwin') return unavailable('unsupported_platform');
    if (!isPackaged) return unavailable('packaged_backend_required');
    let stdout;
    const ordinary = new Set(['PATH', 'HOME', 'USER', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'SystemRoot']);
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => ordinary.has(key)));
    try { ({ stdout } = await run(binary, ['--bridge-setup', action, '--data-dir', userData, '--payload-dir', payload, ...extra],
      { cwd: userData, windowsHide: true, timeout: action === 'deploy' ? 180000 : 30000, maxBuffer: 262144, env: { ...env, FOOTBALL_ASSISTANT_DESKTOP: '1' } })); }
    catch { throw new Error('桥接检查或部署失败；未启动或停止游戏，请检查本机兼容性与组件。'); }
    let value;
    try { value = JSON.parse(stdout); } catch { throw new Error('桥接部署服务返回无效结果；未启用桥接。'); }
    if (!value || typeof value.state !== 'string') throw new Error('桥接部署结果无效。');
    return { ...value, dataConnected: false };
  }
  async function configure(privateRoot) {
    const settings = await loadSettings(userData);
    validateSettings({ ...settings, bridgePrivateRoot: privateRoot });
    const temporary = path.join(userData, `settings.bridge-${require('node:crypto').randomUUID()}.tmp`);
    try {
      await fs.writeFile(temporary, JSON.stringify({ ...settings, bridgePrivateRoot: privateRoot }, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
      await fs.rename(temporary, path.join(userData, 'settings.json'));
    } finally { await fs.rm(temporary, { force: true }); }
    return await onConfigured(privateRoot);
  }
  async function exclusive(action) {
    if (busy) throw new Error('桥接操作正在进行，请稍后再试。');
    busy = true;
    try { return await action(); } finally { busy = false; }
  }
  return {
    inspect: async () => {
      const result = await invoke('inspect');
      if (result.state === 'disabled') {
        const settings = await loadSettings(userData);
        return { ...result, canRollback: Boolean(settings.bridgePrivateRoot), state: settings.bridgePrivateRoot ? 'rollback_pending' : 'disabled' };
      }
      return result;
    },
    plan: gamePath => exclusive(async () => {
      if (typeof gamePath !== 'string' || !path.isAbsolute(gamePath) || !gamePath.toLowerCase().endsWith('.app')) throw new Error('请选择本机 Football Manager 游戏 App。');
      return invoke('plan', ['--game-path', gamePath]);
    }),
    deploy: input => exclusive(async () => {
      if (!input || input.enable !== true || input.allowShadowSigning !== true || input.allowJit !== true || !/^[a-f0-9]{32}$/.test(input.planId || '')) throw new Error('请确认私有副本部署、仅副本签名及 JIT 权限三项说明。');
      const result = await invoke('deploy', ['--plan-id', input.planId, '--consent-shadow-signing-and-jit']);
      if (result.state === 'deployed') {
        const expected = path.join(userData, 'bridge', 'instances', input.planId);
        if (result.privateRoot !== expected) throw new Error('私有桥接目录与已批准计划不一致。');
        const restart = await configure(expected);
        let backendReady = false;
        try { const health = await requestHealth(); backendReady = Boolean(health && typeof health.modelConfigured === 'boolean'); } catch { /* not connected */ }
        return { ...result, ...restart, canRollback: true, health: { backendReady, dataConnected: false }, message: '私有副本已配置；后台健康不代表游戏数据连接。游戏未启动，尚未收到桥接数据。' };
      }
      return result;
    }),
    rollback: () => exclusive(async () => {
      const result = await invoke('rollback');
      if (result.state === 'disabled') { const restart = await configure(''); return { ...result, ...restart, canRollback: false }; }
      return result;
    }),
  };
}
module.exports = { createBridgeSetup };
