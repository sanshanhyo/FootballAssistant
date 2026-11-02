'use strict';
// Main process only. Secrets use the existing OS-backed credential store in a separate namespace.
const path = require('node:path');
const { createCredentialConfig, validateModelConfig } = require('./credentials.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const DEFAULTS = Object.freeze({ enabled: false, networkConsent: false, provider: 'system', voice: '', speed: 1, volume: 1 });
const FIELDS = Object.keys(DEFAULTS);
function validate(input, persisted = false) {
  if (!input || Object.getPrototypeOf(input) !== Object.prototype) throw Error('语音设置格式无效。');
  const allowed = persisted ? ['schema_version', ...FIELDS] : [...FIELDS, 'baseUrl', 'model', 'apiKey', 'removeKey'];
  if (Object.keys(input).some(key => !allowed.includes(key)) || (persisted && input.schema_version !== 1)) throw Error('语音设置字段或版本无效。');
  const value = Object.fromEntries(FIELDS.map(key => [key, input[key] ?? DEFAULTS[key]]));
  if (typeof value.enabled !== 'boolean' || typeof value.networkConsent !== 'boolean' || !['system', 'edge', 'openai'].includes(value.provider)) throw Error('语音开关或服务无效。');
  if (typeof value.voice !== 'string' || (value.voice && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(value.voice))) throw Error('音色 ID 无效。');
  if (!Number.isFinite(value.speed) || value.speed < 0.5 || value.speed > 2 || !Number.isFinite(value.volume) || value.volume < 0 || value.volume > 1) throw Error('语速应为 0.5–2，音量应为 0–1。');
  if (value.enabled && value.provider !== 'system' && !value.networkConsent) throw Error('启用在线语音前，请明确同意将待朗读文字发送到所选服务。');
  return value;
}
async function createSpeechConfig({ userData, safeStorage }) {
  const directory = path.join(userData, 'tts');
  const file = path.join(directory, 'preferences.json');
  const stored = await readStateFile(file, 16384);
  let config = stored.bytes ? validate(JSON.parse(stored.bytes.toString('utf8')), true) : { ...DEFAULTS };
  let revision = stored.revision, saving = false;
  const credentials = createCredentialConfig({ userData: directory, safeStorage });
  function getPublicConfig() {
    const { baseUrl, model, hasApiKey, storage, secureStorageAvailable } = credentials.getPublicConfig();
    return { ...config, baseUrl, model, hasApiKey, storage, secureStorageAvailable };
  }
  async function save(input) {
    if (saving) throw Error('语音设置正在保存，请稍候。');
    const next = validate(input);
    const saved = credentials.getPublicConfig();
    const baseUrl = input.baseUrl ?? saved.baseUrl;
    const model = input.model ?? saved.model;
    const hasCredentialInput = Boolean(baseUrl || model || input.apiKey || (input.removeKey && saved.hasApiKey));
    let keyInput;
    if (hasCredentialInput) {
      keyInput = { provider: 'openai-compatible', baseUrl, model, ...(input.apiKey !== undefined ? { apiKey: input.apiKey } : {}), ...(input.removeKey !== undefined ? { removeKey: input.removeKey } : {}) };
      validateModelConfig(keyInput);
    } else if ((input.apiKey !== undefined && typeof input.apiKey !== 'string') || (input.removeKey !== undefined && typeof input.removeKey !== 'boolean')) throw Error('密钥设置无效。');
    if (next.enabled && next.provider === 'openai' && (!baseUrl || !model || !(input.apiKey || (saved.hasApiKey && !input.removeKey && baseUrl === saved.baseUrl)))) throw Error('请先填写语音专用 HTTPS 地址、模型和密钥。');
    saving = true;
    try {
      if ((await readStateFile(file, 16384)).revision !== revision) throw Error('语音设置已被其他实例修改，请重新打开设置。');
      // If persistence later fails, old consent/provider remains in force; never enable implicitly.
      if (keyInput) credentials.save(keyInput);
      revision = await writeStateFile(file, `${JSON.stringify({ schema_version: 1, ...next }, null, 2)}\n`, revision);
      config = next;
      return getPublicConfig();
    } finally { saving = false; }
  }
  function speechEnv() {
    const secret = credentials.backendEnv();
    const allowed = config.enabled && config.networkConsent && config.provider === 'openai';
    return {
      // Legacy service shares this key with STT; never enable recording upload with TTS consent.
      FA_SPEECH_STT_MODEL: '',
      FA_SPEECH_OPENAI_BASE_URL: allowed ? secret.FOOTBALL_ASSISTANT_BASE_URL : '',
      FA_SPEECH_OPENAI_API_KEY: allowed ? secret.FOOTBALL_ASSISTANT_API_KEY : '',
      FA_SPEECH_TTS_MODEL: allowed ? secret.FOOTBALL_ASSISTANT_MODEL : '',
      FA_SPEECH_TTS_VOICE: config.provider === 'openai' ? (config.voice || 'alloy') : '',
      FA_SPEECH_EDGE_VOICE: config.provider === 'edge' ? (config.voice || 'zh-CN-XiaoxiaoNeural') : '',
    };
  }
  function authorizeSpeak(payload) {
    if (!config.enabled) throw Error('语音朗读尚未启用。');
    if (config.provider !== 'system' && !config.networkConsent) throw Error('尚未同意发送待朗读文字到在线语音服务。');
    if (!payload || typeof payload !== 'object') throw Error('语音请求无效。');
    return { ...payload, provider: config.provider, voice: config.voice || undefined, speed: config.provider === 'system' ? 1 : config.speed, volume: config.provider === 'system' ? 1 : config.volume };
  }
  return { getPublicConfig, save, speechEnv, authorizeSpeak };
}
module.exports = { createSpeechConfig };
