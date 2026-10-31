'use strict';
// Desktop owns only the backend it spawned, never the game or an existing service.
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { request } = require('./backend.cjs');
const DEFAULT_SETTINGS = Object.freeze({ version: 1, backend: { port: 17827 }, bridgePrivateRoot: '', backendEnvFile: '' });
function validateSettings(value) {
  if (!value || value.version !== 1 || !Number.isInteger(value.backend?.port) || value.backend.port < 1 || value.backend.port > 65535) throw new Error('settings.json 版本或后端端口无效；文件未被覆盖。');
  for (const key of ['bridgePrivateRoot', 'backendEnvFile']) if (typeof value[key] !== 'string' || (value[key] && !path.isAbsolute(value[key]))) throw new Error('配置路径必须为绝对路径。');
  // No credentials accepted in this non-secret configuration.
  if (Object.keys(value).some(key => !['version', 'backend', 'bridgePrivateRoot', 'backendEnvFile'].includes(key)) || Object.keys(value.backend).some(key => key !== 'port')) throw new Error('settings.json 包含不支持的字段；密钥不可写入此文件。');
  return value;
}
async function loadSettings(userData) {
  await fs.mkdir(userData, { recursive: true, mode: 0o700 });
  const file = path.join(userData, 'settings.json');
  try { await fs.writeFile(file, JSON.stringify(DEFAULT_SETTINGS, null, 2) + '\n', { flag: 'wx', mode: 0o600 }); }
  catch (error) { if (error.code !== 'EEXIST') throw error; }
  const info = await fs.lstat(file);
  if (!info.isFile() || info.size > 16384) throw new Error('settings.json 必须为普通小型文件。');
  return validateSettings(JSON.parse(await fs.readFile(file, 'utf8')));
}
async function detectGame(platform = process.platform, run = promisify(execFile)) {
  if (!['darwin', 'win32'].includes(platform)) return { state: 'unknown', dataConnected: false, note: '当前平台不支持游戏进程检测。' };
  try {
    const result = platform === 'win32'
      ? await run('tasklist.exe', ['/FO', 'CSV', '/NH'], { windowsHide: true, timeout: 3000, maxBuffer: 1048576 })
      : await run('/bin/ps', ['-A', '-o', 'comm='], { timeout: 3000, maxBuffer: 1048576 });
    const found = platform === 'win32' ? /^"(?:fm|fm27|Football Manager(?: 27)?)\.exe",/im.test(result.stdout)
      : result.stdout.split('\n').some(line => /^(?:fm|fm27|Football Manager(?: 27)?)$/i.test(path.basename(line.trim())));
    return { state: found ? 'running' : 'not_detected', dataConnected: false, note: '进程检测不代表游戏数据已连接。' };
  } catch { return { state: 'unknown', dataConnected: false, note: '无法检测游戏进程；不会启动或修改游戏。' }; }
}
class BackendSupervisor {
  constructor({ userData, resourcesPath, packaged, runtimeFile, external = false, settings, backendEnv = {}, spawnProcess = spawn, probe = request, timeoutMs = 30000 }) {
    Object.assign(this, { userData, resourcesPath, packaged, runtimeFile, external, settings, backendEnv, spawnProcess, probe, timeoutMs });
    this.child = null; this.stopping = false; this.status = { state: 'idle', owned: false };
  }
  async healthy() {
    try { const status = await this.probe(this.runtimeFile, '/v1/status', undefined, { timeoutMs: 1000 }); return Boolean(status && typeof status === 'object' && typeof status.modelConfigured === 'boolean'); }
    catch { return false; }
  }
  async start() {
    if (await this.healthy()) return (this.status = { state: 'ready', owned: false });
    if (this.external) return (this.status = { state: 'unavailable', owned: false, message: '指定的外部后端不可连接；请检查原服务。不会启动替代服务。' });
    if (!this.packaged) return (this.status = { state: 'unavailable', owned: false, message: '开发模式未内置后端；请启动开发服务。' });
    const binary = path.join(this.resourcesPath, 'backend', process.platform === 'win32' ? 'football-assistant-backend.exe' : 'football-assistant-backend');
    try { await fs.access(binary); } catch { return (this.status = { state: 'missing', owned: false, message: '安装包缺少内置后端，请使用完整安装包。' }); }
    const dataDir = path.join(this.userData, 'backend');
    await fs.mkdir(dataDir, { recursive: true, mode: 0o700 });
    const env = { ...process.env, ...this.backendEnv, FOOTBALL_ASSISTANT_DATA_DIR: dataDir, FOOTBALL_ASSISTANT_RUNTIME_FILE: this.runtimeFile,
      FOOTBALL_ASSISTANT_PORT: String(this.settings.backend.port), FOOTBALL_ASSISTANT_DESKTOP: '1' };
    // Optional explicit existing local configuration: never discover, copy or log it.
    delete env.FOOTBALL_ASSISTANT_ENV_FILE; delete env.FOOTBALL_ASSISTANT_PRIVATE_ROOT;
    if (this.settings.backendEnvFile) env.FOOTBALL_ASSISTANT_ENV_FILE = this.settings.backendEnvFile;
    if (this.settings.bridgePrivateRoot) env.FOOTBALL_ASSISTANT_PRIVATE_ROOT = this.settings.bridgePrivateRoot;
    const child = this.spawnProcess(binary, [], { cwd: dataDir, env, windowsHide: true, stdio: 'ignore' });
    this.child = child; this.status = { state: 'starting', owned: true };
    let exited = false;
    child.once('error', () => { exited = true; this.status = { state: 'failed', owned: true, message: '内置后端无法启动。' }; });
    child.once('exit', () => { exited = true; if (!this.stopping) this.status = { state: 'stopped', owned: true, message: '内置后端已退出。' }; });
    const deadline = Date.now() + this.timeoutMs;
    while (!exited && !this.stopping && Date.now() < deadline) {
      if (await this.healthy()) return (this.status = { state: 'ready', owned: true });
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    await this.stop();
    return (this.status = { state: 'failed', owned: false, message: '内置后端未能就绪；可能端口已占用。未停止其他进程。' });
  }
  async stop() {
    this.stopping = true;
    const child = this.child; this.child = null;
    if (!child || child.exitCode !== null || child.signalCode) return;
    await new Promise(resolve => {
      let timer;
      const done = () => { clearTimeout(timer); resolve(); };
      child.once('exit', done);
      child.kill('SIGTERM');
      timer = setTimeout(() => { if (child.exitCode === null && !child.signalCode) child.kill('SIGKILL'); resolve(); }, 3000);
    });
  }
}
module.exports = { DEFAULT_SETTINGS, validateSettings, loadSettings, detectGame, BackendSupervisor };
