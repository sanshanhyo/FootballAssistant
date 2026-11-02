'use strict';
// Main-process onboarding for the bundled read-only producer. Never writes game files.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { loadSettings, validateSettings } = require('./bootstrap.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const PRODUCER_ID = 'footballassistant.offseason-reader';
const PROTOCOL = 'fa-offseason/0.1';
const GAME_HASH = 'bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f';
const hashFile = async file => {
  const handle = await fs.open(file, 'r');
  try { const hash = crypto.createHash('sha256'); for await (const chunk of handle.createReadStream({ autoClose: false })) hash.update(chunk); return hash.digest('hex'); }
  finally { await handle.close(); }
};
async function ordinary(file, limit = 256 * 1024 * 1024) {
  const stat = await fs.lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > limit) throw Error('读取组件必须是未链接的普通文件。');
  return stat;
}
async function safeChild(root, relative, limit = 256 * 1024 * 1024) {
  if (typeof relative !== 'string' || !relative || relative.includes('\\') || relative.includes(':') || path.posix.isAbsolute(relative) || relative.split('/').some(p => !p || p === '.' || p === '..')) throw Error('读取组件清单包含无效路径。');
  let cursor = root;
  for (const part of relative.split('/').slice(0, -1)) { cursor = path.join(cursor, part); const stat = await fs.lstat(cursor); if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('读取组件包含链接目录。'); }
  const file = path.join(root, ...relative.split('/')); await ordinary(file, limit); return file;
}
async function validateReaderPayload(resourcesPath) {
  const directory = path.join(resourcesPath, 'reader-windows-x64');
  const stat = await fs.lstat(directory); if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('读取组件目录无效。');
  const root = await fs.realpath(directory); await ordinary(path.join(root, 'manifest.json'), 2_000_000);
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'manifest.json'), 'utf8'));
  if (manifest.schema !== 1 || manifest.target !== 'win32-x64' || manifest.entrypoint !== 'OffseasonReaderCli.exe' || manifest.producerId !== PRODUCER_ID || manifest.protocol !== PROTOCOL || manifest.gamePluginSha256?.toLowerCase() !== GAME_HASH || !manifest.files || Array.isArray(manifest.files) || typeof manifest.files !== 'object') throw Error('读取组件版本或协议不匹配。');
  const entries = Object.entries(manifest.files); if (!entries.length || entries.length > 4096 || !manifest.files[manifest.entrypoint]) throw Error('读取组件清单不完整。');
  const names = new Set(); let total = 0;
  for (const [name, expected] of entries) {
    if (names.has(name.toLowerCase()) || !/^[a-f0-9]{64}$/.test(expected)) throw Error('读取组件清单无效。'); names.add(name.toLowerCase());
    const file = await safeChild(root, name); total += (await ordinary(file)).size;
    if (total > 1024 * 1024 * 1024 || await hashFile(file) !== expected) throw Error('读取组件校验失败，请重新安装完整测试包。');
  }
  // A .NET producer must not load an unlisted adjacent assembly or config.
  async function inventory(folder, prefix = '') {
    for (const entry of await fs.readdir(folder, { withFileTypes: true })) {
      const rel = prefix + entry.name;
      if (entry.isSymbolicLink()) throw Error('读取组件包含链接。');
      if (entry.isDirectory()) await inventory(path.join(folder, entry.name), rel + '/');
      else if (!entry.isFile() || (rel !== 'manifest.json' && !Object.hasOwn(manifest.files, rel))) throw Error('读取组件包含未列出的文件。');
    }
  }
  await inventory(root);
  return { executable: path.join(root, manifest.entrypoint), producerId: PRODUCER_ID, protocol: PROTOCOL, buildCommit: manifest.buildCommit || null, runtimeVersion: manifest.runtimeVersion || null };
}
async function inspectGame(executable) {
  if (typeof executable !== 'string' || !path.isAbsolute(executable) || path.basename(executable).toLowerCase() !== 'fm.exe') throw Error('请选择 Football Manager 27 的 fm.exe。');
  await ordinary(executable, 2 * 1024 * 1024 * 1024); const root = await fs.realpath(path.dirname(executable));
  const candidates = ['fm_Data/Plugins/x86_64/game_plugin.dll', 'fm_Data/Plugins/game_plugin.dll', 'game_plugin.dll'];
  let plugin = null;
  for (const name of candidates) { try { const file = await safeChild(root, name, 2 * 1024 * 1024 * 1024); plugin = file; break; } catch (error) { if (error.code !== 'ENOENT') throw error; } }
  if (!plugin || await hashFile(plugin) !== GAME_HASH) throw Error('当前游戏版本不在此读取器支持范围；不会读取未知版本或修改游戏。');
  const externalLoaders = [];
  for (const name of ['winhttp.dll', 'doorstop_config.ini', 'BepInEx']) { try { await fs.lstat(path.join(root, name)); externalLoaders.push(name); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
  return { gamePath: path.join(root, 'fm.exe'), gamePluginSha256: GAME_HASH, externalLoaders, gameFilesChanged: false };
}
async function discoverGames({ env = process.env, run = promisify(execFile) } = {}) {
  const steamRoots = new Set([env['ProgramFiles(x86)'], env.ProgramFiles].filter(Boolean).map(base => path.join(base, 'Steam')));
  try { const { stdout } = await run('reg.exe', ['query', 'HKCU\\Software\\Valve\\Steam', '/v', 'SteamPath'], { windowsHide: true, timeout: 3000, maxBuffer: 65536 }); const match = /SteamPath\s+REG_SZ\s+(.+)/i.exec(stdout); if (match) steamRoots.add(match[1].trim()); } catch { /* Native selection remains available. */ }
  const libraries = new Set(steamRoots);
  for (const root of steamRoots) {
    try { const file = path.join(root, 'steamapps', 'libraryfolders.vdf'); await ordinary(file, 1048576); const data = await fs.readFile(file, 'utf8'); for (const match of data.matchAll(/"path"\s+"([^"\r\n]{1,4096})"/g)) { const value = match[1].replace(/\\\\/g, '\\'); if (path.isAbsolute(value)) libraries.add(value); } } catch { /* Missing library manifests are not scanned recursively. */ }
  }
  const candidates = [];
  for (const root of libraries) { const file = path.join(root, 'steamapps', 'common', 'Football Manager 27', 'fm.exe'); try { await ordinary(file); candidates.push(file); } catch {} }
  return [...new Set(candidates)];
}
function createWindowsReaderSetup({ userData, resourcesPath, packaged, platform = process.platform, chooseGame, discover = discoverGames, inspect = inspectGame, validatePayload = validateReaderPayload, requestStatus, onConfigured = async () => ({}) }) {
  let busy = false, selected = null;
  async function status({ verify = false } = {}) {
    if (platform !== 'win32') return { supported: false, state: 'unsupported_platform', enabled: false, dataConnected: false };
    const settings = await loadSettings(userData); let payload;
    try { if (!packaged) throw Error('开发模式未配置内置读取器。'); payload = await validatePayload(resourcesPath); }
    catch (error) { return { supported: true, state: 'payload_unavailable', enabled: settings.windowsReaderEnabled === true, canEnable: false, dataConnected: false, error: error.message }; }
    const enabled = settings.windowsReaderEnabled === true;
    let backend = null; let backendError = null;
    if (requestStatus) { try { backend = await requestStatus(verify && enabled); } catch (error) { backendError = error.message; } }
    return { supported: true, state: !enabled ? 'not_enabled' : backendError ? 'backend_unavailable' : backend?.state || 'configured', enabled, canEnable: !enabled, payloadReady: true, producerId: payload.producerId, buildCommit: payload.buildCommit, dataConnected: backend?.state === 'fresh_partial', backend, backendError, gamePath: selected?.gamePath || settings.windowsReaderGamePath || '', externalLoaders: selected?.externalLoaders || [] };
  }
  async function exclusive(action) { if (busy) throw Error('正在检查或配置读取器，请稍候。'); busy = true; try { return await action(); } finally { busy = false; } }
  return {
    status,
    selectGame: () => exclusive(async () => { const file = await chooseGame(); if (!file) return { cancelled: true }; selected = null; selected = await inspect(file); return { ...await status(), ...selected }; }),
    inspect: () => exclusive(async () => { const value = await status(); if (!value.supported || !value.payloadReady) return value; const candidates = await discover(); if (!selected && candidates.length === 1) { try { selected = await inspect(candidates[0]); } catch (error) { return { ...value, state: 'unsupported_game', canEnable: false, candidates, error: error.message }; } } return { ...value, candidates, ...(selected || {}) }; }),
    enable: input => exclusive(async () => {
      if (!input || Object.keys(input).sort().join(',') !== 'enabled,readOnlyConsent' || typeof input.enabled !== 'boolean' || (input.enabled && input.readOnlyConsent !== true)) throw Error('请明确确认启用只读游戏读取。');
      if (platform !== 'win32' || !packaged) throw Error('此安装环境不支持内置 Windows 读取器。');
      const payload = input.enabled ? await validatePayload(resourcesPath) : null; const settings = await loadSettings(userData);
      if (input.enabled && !selected && settings.windowsReaderGamePath) selected = await inspect(settings.windowsReaderGamePath);
      if (input.enabled && !selected) { const candidates = await discover(); if (candidates.length !== 1) throw Error('请先选择本机 fm.exe。'); selected = await inspect(candidates[0]); }
      if (input.enabled) selected = await inspect(selected.gamePath);
      const file = path.join(userData, 'settings.json'), before = await readStateFile(file, 16384);
      const next = validateSettings({ ...settings, windowsReaderEnabled: input.enabled, windowsReaderGamePath: input.enabled ? selected.gamePath : settings.windowsReaderGamePath || '' });
      await writeStateFile(file, JSON.stringify(next, null, 2) + '\n', before.revision);
      const outcome = await onConfigured({ enabled: input.enabled, executable: input.enabled ? payload.executable : '' });
      return { ...await status(), ...outcome, gameFilesChanged: false };
    }),
  };
}
module.exports = { createWindowsReaderSetup, validateReaderPayload, inspectGame, discoverGames, PRODUCER_ID, PROTOCOL, GAME_HASH };
