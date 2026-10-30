'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createSpeech } = require('./tts.cjs');

const MAX_AUDIO_BYTES = 20 * 1024 * 1024;
const MAX_TEXT_LENGTH = 12_000;
const DEFAULT_TIMEOUT_MS = 45_000;
const MIME_EXTENSIONS = Object.freeze({
  'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'mp4',
  'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/flac': 'flac',
});

class SpeechError extends Error {
  constructor(code, message) { super(message); this.name = 'SpeechError'; this.code = code; }
}

function fail(code, message) { throw new SpeechError(code, message); }
function cleanString(value, max = 128) {
  return typeof value === 'string' && value.length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/u.test(value);
}
function operationMetadata(payload) {
  if (!payload || !cleanString(payload.operationId) || !cleanString(payload.conversationId)
      || !Number.isSafeInteger(payload.generation) || payload.generation < 0) {
    fail('invalid-request', '语音请求缺少有效的操作或会话标识。');
  }
  return { operationId: payload.operationId, generation: payload.generation, conversationId: payload.conversationId };
}
function validateEndpoint(value) {
  try {
    const url = new URL(value);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))
        || url.username || url.password || url.search || url.hash) return null;
    return url.href.replace(/\/$/u, '');
  } catch { return null; }
}
function escapeXml(text) {
  return text.replace(/[<>&"']/gu, character => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[character]));
}
function findEdgeExecutable(env, platform) {
  const explicit = env.FA_SPEECH_EDGE_PATH;
  const candidates = explicit
    ? (path.isAbsolute(explicit) ? [explicit] : [])
    : (env.PATH || '').split(path.delimiter).filter(Boolean)
      .map(directory => path.join(directory, platform === 'win32' ? 'edge-tts.exe' : 'edge-tts'));
  for (const candidate of candidates) {
    try {
      if (!fs.statSync(candidate).isFile()) continue;
      fs.accessSync(candidate, platform === 'win32' ? fs.constants.F_OK : fs.constants.X_OK);
      return fs.realpathSync(candidate);
    } catch { /* An absent optional executable is a capability state. */ }
  }
  return null;
}
function snapshotConfig(env, platform) {
  return {
    baseUrl: validateEndpoint(env.FA_SPEECH_OPENAI_BASE_URL || 'https://api.openai.com/v1'),
    apiKey: env.FA_SPEECH_OPENAI_API_KEY || '',
    sttModel: env.FA_SPEECH_STT_MODEL || '',
    ttsModel: env.FA_SPEECH_TTS_MODEL || '',
    ttsVoice: env.FA_SPEECH_TTS_VOICE || 'alloy',
    azureKey: env.FA_SPEECH_AZURE_KEY || '',
    azureRegion: env.FA_SPEECH_AZURE_REGION || '',
    azureVoice: env.FA_SPEECH_AZURE_VOICE || 'zh-CN-XiaoxiaoNeural',
    edgePath: findEdgeExecutable(env, platform),
    edgeVoice: env.FA_SPEECH_EDGE_VOICE || 'zh-CN-XiaoxiaoNeural',
  };
}
function audioBytes(value) {
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  fail('invalid-audio', '录音数据格式无效。');
}
function requireVoice(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/u.test(value)) fail('invalid-voice', '语音音色参数无效。');
  return value;
}
function discardBody(body) {
  try {
    // Cancellation is best effort: a provider's cleanup must not hide the original error.
    void Promise.resolve(body?.cancel?.()).catch(() => {});
  } catch { /* Some adapters throw synchronously from cancel(). */ }
}

async function readLimited(response, maximum, signal) {
  const declaredLength = Number(response.headers?.get?.('content-length'));
  if (Number.isFinite(declaredLength) && declaredLength > maximum) {
    discardBody(response.body);
    fail('response-too-large', '语音服务返回的数据过大。');
  }
  if (!response.body?.getReader) {
    const buffer = new Uint8Array(await response.arrayBuffer());
    if (signal.aborted) throw signal.reason;
    if (buffer.byteLength > maximum) fail('response-too-large', '语音服务返回的数据过大。');
    return buffer;
  }
  const reader = response.body.getReader();
  const chunks = []; let size = 0;
  const abortReader = () => discardBody(reader);
  signal.addEventListener('abort', abortReader, { once: true });
  try {
    while (true) {
      if (signal.aborted) throw signal.reason;
      const result = await reader.read();
      if (signal.aborted) throw signal.reason;
      if (result.done) break;
      size += result.value.byteLength;
      if (size > maximum) {
        discardBody(reader);
        fail('response-too-large', '语音服务返回的数据过大。');
      }
      chunks.push(result.value);
    }
  } finally {
    signal.removeEventListener('abort', abortReader);
    reader.releaseLock();
  }
  const output = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { output.set(chunk, offset); offset += chunk.byteLength; }
  return output;
}

function createSpeechService(options = {}) {
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const config = snapshotConfig(env, platform);
  const fetchImpl = options.fetch || globalThis.fetch;
  const spawnImpl = options.spawn || spawn;
  const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
  const active = new Map();
  let systemContext = null;
  let startingSystem = false;
  let disposed = false;
  const emit = value => { if (!disposed) options.onState?.(value); };
  const systemSpeech = createSpeech(value => {
    if (!systemContext || (startingSystem && value.state === 'stopped')) return;
    const context = systemContext;
    if (['finished', 'error', 'stopped'].includes(value.state)) systemContext = null;
    emit({ ...context, ...value, provider: 'system', synthetic: false });
  }, { platform, spawn: spawnImpl });

  function capabilities() {
    const openaiStt = Boolean(config.baseUrl && config.apiKey && config.sttModel);
    const openaiTts = Boolean(config.baseUrl && config.apiKey && config.ttsModel);
    const azure = Boolean(config.azureKey && /^[a-z0-9-]{1,60}$/u.test(config.azureRegion));
    const system = ['darwin', 'win32'].includes(platform);
    const capability = (id, label, configured, reason, synthetic = false) => ({ id, label, configured, available: configured, reason: configured ? null : reason, synthetic });
    return {
      stt: [
        capability('openai', 'OpenAI 兼容转写', openaiStt, '尚未配置转写服务、密钥或模型。'),
        capability('mock', '模拟转写', true, null, true),
      ],
      tts: [
        capability('system', '系统语音', system, '当前平台没有系统语音适配。'),
        capability('edge', 'Edge TTS', Boolean(config.edgePath), '未检测到 Edge TTS，请在主进程配置可执行文件。'),
        capability('openai', 'OpenAI 兼容语音', openaiTts, '尚未配置语音服务、密钥或模型。'),
        capability('azure', 'Azure 语音', azure, '尚未配置 Azure 语音密钥或区域。'),
        capability('mock', '模拟播报（无音频）', true, null, true),
      ],
      limits: { maxAudioBytes: MAX_AUDIO_BYTES, maxTextLength: MAX_TEXT_LENGTH, timeoutMs },
    };
  }
  function requireCapability(kind, provider) {
    const capability = capabilities()[kind].find(item => item.id === provider);
    if (!capability) fail('unsupported-provider', '不支持此语音服务。');
    if (!capability.available) fail('not-configured', capability.reason);
  }
  function cancel(operationId) {
    const record = active.get(operationId);
    const systemActive = systemContext?.operationId === operationId;
    if (record) {
      active.delete(operationId);
      record.controller.abort(new SpeechError('cancelled', '语音操作已取消。'));
    }
    if (systemActive) systemSpeech.stop();
    return { cancelled: Boolean(record || systemActive), operationId };
  }
  function stop() {
    for (const operationId of [...active.keys()]) cancel(operationId);
    systemSpeech.stop();
    return { stopped: true };
  }
  function metadata(payload, provider, limitations = []) {
    return {
      ...operationMetadata(payload), provider, source: { kind: 'speech', provider },
      sessionId: payload.conversationId, sampledAt: new Date().toISOString(),
      synthetic: provider === 'mock', partial: false, limitations,
    };
  }
  async function withOperation(kind, payload, work) {
    const context = operationMetadata(payload);
    if (disposed) fail('disposed', '语音服务已关闭。');
    cancel(context.operationId);
    const record = { controller: new AbortController(), kind };
    active.set(context.operationId, record);
    const timer = setTimeout(() => record.controller.abort(new SpeechError('timeout', '语音服务响应超时。')), timeoutMs);
    let abortListener;
    const aborted = new Promise((_, reject) => {
      abortListener = () => reject(record.controller.signal.reason);
      record.controller.signal.addEventListener('abort', abortListener, { once: true });
    });
    const ensureCurrent = () => {
      if (record.controller.signal.aborted) throw record.controller.signal.reason;
      if (active.get(context.operationId) !== record) fail('cancelled', '语音操作已取消。');
    };
    try {
      const result = await Promise.race([work(record.controller.signal), aborted]);
      ensureCurrent();
      return result;
    } catch (error) {
      if (record.controller.signal.aborted) throw record.controller.signal.reason;
      // Abort failed fetches as well as timed-out/cancelled operations so unread bodies close.
      record.controller.abort(new SpeechError('cancelled', '语音请求已终止。'));
      if (error instanceof SpeechError) throw error;
      fail('speech-failed', '语音服务暂时不可用，请检查配置或网络。');
    } finally {
      clearTimeout(timer);
      record.controller.signal.removeEventListener('abort', abortListener);
      if (active.get(context.operationId) === record) active.delete(context.operationId);
    }
  }
  async function request(url, options, maximum, signal, expectAudio = false) {
    const response = await fetchImpl(url, { ...options, redirect: 'error', signal });
    if (!response.ok) {
      discardBody(response.body);
      if ([401, 403].includes(response.status)) fail('authentication-failed', '语音服务身份验证失败，请检查配置。');
      if (response.status === 429) fail('rate-limited', '语音服务当前受到额度或频率限制。');
      fail('service-error', `语音服务请求失败（HTTP ${response.status}）。`);
    }
    const contentType = response.headers?.get?.('content-type')?.split(';')[0].trim().toLowerCase();
    if (expectAudio && contentType && !contentType.startsWith('audio/') && contentType !== 'application/octet-stream') {
      discardBody(response.body);
      fail('invalid-response', '语音服务没有返回音频。');
    }
    return readLimited(response, maximum, signal);
  }
  async function transcribe(payload) {
    const provider = payload?.provider;
    operationMetadata(payload);
    requireCapability('stt', provider);
    const bytes = audioBytes(payload.audio);
    const mimeType = typeof payload.mimeType === 'string' ? payload.mimeType.toLowerCase().split(';')[0].trim() : '';
    if (!MIME_EXTENSIONS[mimeType] || bytes.byteLength === 0 || bytes.byteLength > MAX_AUDIO_BYTES) {
      fail('invalid-audio', '录音为空、格式不受支持或超过 20 MB。');
    }
    if (payload.language && !/^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$/u.test(payload.language)) fail('invalid-language', '转写语言参数无效。');
    return withOperation('stt', payload, async signal => {
      if (provider === 'mock') return {
        ...metadata(payload, provider, ['这是模拟转写，未识别录音中的实际内容。']),
        text: '【模拟转写】这是一条语音输入示例，未识别实际录音。',
      };
      const form = new FormData();
      form.set('model', config.sttModel);
      form.set('file', new Blob([bytes], { type: mimeType }), `recording.${MIME_EXTENSIONS[mimeType]}`);
      if (payload.language) form.set('language', payload.language);
      const response = await request(`${config.baseUrl}/audio/transcriptions`, {
        method: 'POST', headers: { Authorization: `Bearer ${config.apiKey}` }, body: form,
      }, 64 * 1024, signal);
      let result;
      try { result = JSON.parse(new TextDecoder().decode(response)); } catch { fail('invalid-response', '转写服务没有返回有效文本。'); }
      if (typeof result.text !== 'string' || result.text.length > MAX_TEXT_LENGTH) fail('invalid-response', '转写服务没有返回有效文本。');
      return { ...metadata(payload, provider, ['机器转写可能存在识别错误，请在发送前检查。']), text: result.text };
    });
  }

  async function edgeAudio(text, voice, signal) {
    const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'football-speech-'));
    const input = path.join(directory, 'input.txt');
    const output = path.join(directory, 'speech.mp3');
    try {
      await fsp.writeFile(input, text, { encoding: 'utf8', mode: 0o600 });
      await new Promise((resolve, reject) => {
        if (signal.aborted) { reject(signal.reason); return; }
        const child = spawnImpl(config.edgePath, ['--file', input, '--voice', voice, '--write-media', output], {
          windowsHide: true, shell: false, stdio: ['ignore', 'ignore', 'ignore'],
        });
        let settled = false;
        const finish = error => {
          if (settled) return;
          settled = true;
          signal.removeEventListener('abort', abort);
          if (error) reject(error); else resolve();
        };
        const abort = () => { child.kill(); finish(signal.reason); };
        signal.addEventListener('abort', abort, { once: true });
        child.once('error', () => finish(new SpeechError('edge-failed', 'Edge TTS 启动失败。')));
        child.once('exit', code => finish(code === 0 ? null : new SpeechError('edge-failed', 'Edge TTS 合成失败。')));
        if (signal.aborted) abort();
      });
      if (signal.aborted) throw signal.reason;
      const stat = await fsp.stat(output);
      if (stat.size === 0 || stat.size > MAX_AUDIO_BYTES) fail('invalid-response', 'Edge TTS 音频为空或过大。');
      return new Uint8Array(await fsp.readFile(output));
    } finally { await fsp.rm(directory, { recursive: true, force: true }); }
  }
  async function speak(payload) {
    const provider = payload?.provider;
    operationMetadata(payload);
    requireCapability('tts', provider);
    if (typeof payload.text !== 'string' || !payload.text.trim() || payload.text.length > MAX_TEXT_LENGTH) fail('invalid-text', '朗读文本为空或过长。');
    for (const [operationId, record] of active) if (record.kind === 'tts') cancel(operationId);
    systemSpeech.stop();
    if (provider === 'system') {
      if (disposed) fail('disposed', '语音服务已关闭。');
      systemContext = metadata(payload, provider);
      startingSystem = true;
      try { systemSpeech.speak(payload.text); }
      catch (error) { systemContext = null; throw error; }
      finally { startingSystem = false; }
      return { ...metadata(payload, provider), playback: 'system' };
    }
    return withOperation('tts', payload, async signal => {
      if (provider === 'mock') return { ...metadata(payload, provider, ['模拟播报不生成音频。']), playback: 'none' };
      let bytes;
      if (provider === 'openai') {
        if (payload.text.length > 4096) fail('invalid-text', '此语音服务单次最多支持 4096 个字符。');
        bytes = await request(`${config.baseUrl}/audio/speech`, {
          method: 'POST', headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: config.ttsModel, input: payload.text, voice: requireVoice(payload.voice || config.ttsVoice), response_format: 'mp3' }),
        }, MAX_AUDIO_BYTES, signal, true);
      } else if (provider === 'azure') {
        const voice = requireVoice(payload.voice || config.azureVoice);
        const language = voice.match(/^[A-Za-z]{2,3}-[A-Za-z]{2,4}/u)?.[0];
        if (!language) fail('invalid-voice', 'Azure 音色需要包含语言和区域。');
        const ssml = `<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="${language}"><voice name="${voice}">${escapeXml(payload.text)}</voice></speak>`;
        bytes = await request(`https://${config.azureRegion}.tts.speech.microsoft.com/cognitiveservices/v1`, {
          method: 'POST', headers: {
            'Ocp-Apim-Subscription-Key': config.azureKey, 'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3', 'User-Agent': 'FootballAssistant-Companion',
          }, body: ssml,
        }, MAX_AUDIO_BYTES, signal, true);
      } else {
        bytes = await edgeAudio(payload.text, requireVoice(payload.voice || config.edgeVoice), signal);
      }
      if (bytes.byteLength === 0) fail('invalid-response', '语音服务没有返回音频。');
      return { ...metadata(payload, provider), playback: 'renderer', mimeType: 'audio/mpeg', audio: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
    });
  }
  function dispose() { stop(); disposed = true; }
  return { capabilities, transcribe, speak, cancel, stop, dispose };
}

module.exports = { createSpeechService, SpeechError, validateEndpoint, escapeXml, MAX_AUDIO_BYTES, MAX_TEXT_LENGTH };
