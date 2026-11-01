'use strict';
// Main-process only. Never expose backendEnv or decrypted material through IPC.
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID, createHash } = require('node:crypto');
const { destination, PROVIDERS } = require('./model-providers.cjs');
const DEFAULTS = Object.freeze({ schema_version: 1, provider: 'opencode-go', baseUrl: '', model: '' });
function validate(input, { persisted = false } = {}) {
  if (!input || Object.getPrototypeOf(input) !== Object.prototype) throw Error('模型配置格式无效。');
  const allowed = persisted ? ['schema_version', 'provider', 'baseUrl', 'model'] : ['provider', 'baseUrl', 'model', 'apiKey', 'removeKey'];
  if (Object.keys(input).some(key => !allowed.includes(key))) throw Error('模型配置包含未知字段。');
  if (persisted && input.schema_version !== undefined && input.schema_version !== 1) throw Error('模型配置版本不受支持。');
  if (!PROVIDERS.some(item => item.id === input.provider && !item.disabled)) throw Error('请选择支持的模型服务类型。');
  for (const key of ['baseUrl', 'model']) if (typeof input[key] !== 'string' || input[key].length > 2048 || /[\x00-\x1f\x7f]/.test(input[key])) throw Error('模型地址或名称无效。');
  let baseUrl = input.baseUrl.trim().replace(/\/+$/, '');
  if (!persisted) baseUrl = destination(input.provider, baseUrl).baseUrl;
  if (baseUrl) {
    let url; try { url = new URL(baseUrl); } catch { throw Error('请输入有效的模型服务 URL。'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw Error('模型服务须使用 HTTPS，不能包含账号、密码、查询参数或片段。');
  }
  if (!persisted && !input.model.trim()) throw Error('请输入模型名称。');
  if (input.apiKey !== undefined && (typeof input.apiKey !== 'string' || input.apiKey.length > 8192 || /[\x00-\x20\x7f]/.test(input.apiKey))) throw Error('API Key 格式无效，请勿包含空白。');
  if (input.removeKey !== undefined && typeof input.removeKey !== 'boolean') throw Error('清除密钥选项无效。');
  if (typeof input.apiKey === 'string' && /^[•●*]{4,}$/.test(input.apiKey)) throw Error('请输入新密钥，不能保存遮罩占位符。');
  if (input.removeKey && input.apiKey) throw Error('不能同时保存和清除密钥。');
  if (input.apiKey && !baseUrl) throw Error('保存密钥前请填写服务地址。');
  const preset = PROVIDERS.find(item => item.id === input.provider);
  const provider = persisted && !preset.custom && baseUrl && baseUrl !== preset.baseUrl ? 'openai-compatible' : input.provider;
  return { schema_version: 1, provider, baseUrl, model: input.model.trim() };
}
function atomicWrite(file, value, backup = false) {
  const temp = `${file}.${randomUUID()}.tmp`;
  let handle;
  try {
    handle = fs.openSync(temp, 'wx', 0o600);
    fs.writeFileSync(handle, `${JSON.stringify(value, null, 2)}\n`); fs.fsyncSync(handle); fs.closeSync(handle); handle = undefined;
    if (backup && fs.existsSync(file)) fs.copyFileSync(file, `${file}.bak`);
    fs.renameSync(temp, file);
  } finally { if (handle !== undefined) fs.closeSync(handle); fs.rmSync(temp, { force: true }); }
}
function createCredentialConfig({ userData, safeStorage }) {
  fs.mkdirSync(userData, { recursive: true, mode: 0o700 });
  const configFile = path.join(userData, 'model-config.json');
  const secretFile = path.join(userData, 'credentials.enc.json');
  const secure = () => {
    try { return safeStorage?.isEncryptionAvailable() === true && safeStorage.getSelectedStorageBackend?.() !== 'basic_text'; } catch { return false; }
  };
  let config = { ...DEFAULTS }, apiKey = '', storage = 'none';
  if (fs.existsSync(configFile)) {
    try {
      const original = JSON.parse(fs.readFileSync(configFile, 'utf8'));
      config = validate(original, { persisted: true });
      if (original.schema_version === undefined) atomicWrite(configFile, config, true);
    } catch { throw Error('本机模型配置无法读取；原文件已保留，请检查配置版本。'); }
  } else atomicWrite(configFile, config);
  if (secure() && fs.existsSync(secretFile)) {
    try {
      const record = JSON.parse(fs.readFileSync(secretFile, 'utf8'));
      if (record.schema_version !== 1 || typeof record.ciphertext !== 'string') throw Error();
      const decoded = JSON.parse(safeStorage.decryptString(Buffer.from(record.ciphertext, 'base64')));
      // Bind credentials to the selected destination: never reuse keys across providers/endpoints.
      if (decoded.provider === config.provider && decoded.baseUrl === config.baseUrl && typeof decoded.apiKey === 'string') { apiKey = decoded.apiKey; storage = 'encrypted'; }
    } catch { /* OS account/keychain changed: require explicit re-entry, never leak decrypt errors. */ }
  }
  const getPublicConfig = () => ({ ...config, configured: Boolean(config.baseUrl), hasApiKey: Boolean(apiKey), storage, secureStorageAvailable: secure() });
  const fileRevision = file => fs.existsSync(file) ? createHash('sha256').update(fs.readFileSync(file)).digest('hex') : null;
  let configRevision = fileRevision(configFile), secretRevision = fileRevision(secretFile);
  function save(input) {
    const next = validate(input);
    if (fileRevision(configFile) !== configRevision || fileRevision(secretFile) !== secretRevision) throw Error('Configuration changed outside this instance; restart before saving');
    let nextKey = input.removeKey ? '' : input.apiKey || ((next.baseUrl === config.baseUrl && next.provider === config.provider) ? apiKey : '');
    let nextStorage = 'none';
    let encrypted;
    if (nextKey && secure()) {
      try { encrypted = { schema_version: 1, ciphertext: safeStorage.encryptString(JSON.stringify({ provider: next.provider, baseUrl: next.baseUrl, apiKey: nextKey })).toString('base64') }; }
      catch { throw Error('系统安全存储失败，配置未保存。请解锁系统钥匙串后重试。'); }
      nextStorage = 'encrypted';
    } else if (nextKey) nextStorage = 'session';
    // A crash between writes can only make the key unavailable, never send it to another host.
    const previousSecret = fs.existsSync(secretFile) ? JSON.parse(fs.readFileSync(secretFile, 'utf8')) : null;
    if (encrypted) atomicWrite(secretFile, encrypted);
    else fs.rmSync(secretFile, { force: true });
    const writtenSecretRevision = fileRevision(secretFile);
    try { atomicWrite(configFile, next, true); }
    catch (error) {
      // Roll back a reported save failure, without overwriting another writer's key.
      if (fileRevision(secretFile) === writtenSecretRevision) {
        if (previousSecret) atomicWrite(secretFile, previousSecret);
        else fs.rmSync(secretFile, { force: true });
        secretRevision = fileRevision(secretFile);
      }
      throw error;
    }
    configRevision = fileRevision(configFile); secretRevision = fileRevision(secretFile);
    config = next; apiKey = nextKey; storage = nextStorage;
    return getPublicConfig();
  }
  return { getPublicConfig, save, backendEnv: () => ({ FOOTBALL_ASSISTANT_BASE_URL: config.baseUrl, FOOTBALL_ASSISTANT_MODEL: config.model, FOOTBALL_ASSISTANT_API_KEY: apiKey }) };
}
module.exports = { createCredentialConfig, validateModelConfig: validate };
