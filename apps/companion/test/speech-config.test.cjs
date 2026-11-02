'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createSpeechConfig } = require('../src/speech-config.cjs');
const defaults = { enabled: false, networkConsent: false, provider: 'system', voice: '', speed: 1, volume: 1 };
const online = { ...defaults, enabled: true, networkConsent: true, provider: 'openai', baseUrl: 'https://example.invalid/v1', model: 'speech-model', apiKey: 'fake-only-secret' };
const safeStorage = { isEncryptionAvailable: () => true, getSelectedStorageBackend: () => 'test', encryptString: text => Buffer.from(text.split('').reverse().join('')), decryptString: bytes => bytes.toString().split('').reverse().join('') };
async function setup(t, safe = safeStorage) {
  const userData = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-speech-config-'));
  t.after(() => fs.rm(userData, { recursive: true, force: true }));
  return { userData, config: await createSpeechConfig({ userData, safeStorage: safe }) };
}
test('TTS is off by default; main gate rejects bypass and never inherits chat secrets', async t => {
  const { config } = await setup(t);
  assert.equal(config.getPublicConfig().enabled, false);
  assert.equal(config.speechEnv().FA_SPEECH_OPENAI_API_KEY, '');
  assert.throws(() => config.authorizeSpeak({ provider: 'edge', text: 'x' }), /尚未启用/);
  await assert.rejects(config.save({ ...defaults, enabled: true, provider: 'edge' }), /同意/);
  await config.save({ ...defaults, enabled: true, networkConsent: true, provider: 'edge', voice: 'zh-CN-XiaoxiaoNeural', speed: 0.75, volume: 0.4 });
  const input = config.authorizeSpeak({ provider: 'openai', voice: 'attacker', speed: 99, volume: 99, operationId: 'x', text: 'x' });
  assert.equal(input.provider, 'edge'); assert.equal(input.speed, 0.75); assert.equal(input.volume, 0.4);
});
test('credentials are encrypted in isolated TTS directory, redacted publicly, and bound to endpoint', async t => {
  const { config, userData } = await setup(t);
  const value = await config.save(online);
  assert.equal(value.storage, 'encrypted'); assert.equal(value.hasApiKey, true);
  assert.equal(JSON.stringify(value).includes(online.apiKey), false);
  for (const file of await fs.readdir(path.join(userData, 'tts'))) assert.equal((await fs.readFile(path.join(userData, 'tts', file), 'utf8')).includes(online.apiKey), false);
  assert.equal(config.speechEnv().FA_SPEECH_OPENAI_API_KEY, online.apiKey);
  const again = await createSpeechConfig({ userData, safeStorage });
  assert.equal(again.speechEnv().FA_SPEECH_OPENAI_API_KEY, online.apiKey);
  await assert.rejects(again.save({ ...online, apiKey: '', baseUrl: 'https://other.invalid/v1' }), /密钥/);
  await again.save({ ...online, apiKey: '', enabled: false, baseUrl: 'https://other.invalid/v1' });
  assert.equal(again.getPublicConfig().hasApiKey, false);
  assert.equal(again.speechEnv().FA_SPEECH_OPENAI_API_KEY, '');
});
test('basic_text stores keys only for the session and removal clears them', async t => {
  const insecure = { ...safeStorage, getSelectedStorageBackend: () => 'basic_text' };
  const { config, userData } = await setup(t, insecure);
  assert.equal((await config.save(online)).storage, 'session');
  await assert.rejects(fs.access(path.join(userData, 'tts', 'credentials.enc.json')), { code: 'ENOENT' });
  const next = await createSpeechConfig({ userData, safeStorage: insecure });
  assert.equal(next.getPublicConfig().hasApiKey, false);
  assert.equal(next.speechEnv().FA_SPEECH_OPENAI_API_KEY, '');
  await config.save({ ...online, enabled: false, apiKey: '', removeKey: true });
  assert.equal(config.getPublicConfig().hasApiKey, false);
});
test('invalid preferences, insecure endpoints and persisted secrets are rejected', async t => {
  const { config, userData } = await setup(t);
  for (const input of [{ ...defaults, speed: NaN }, { ...defaults, volume: 2 }, { ...defaults, voice: '<xml>' }, { ...defaults, secret: 'x' }, { ...online, baseUrl: 'http://example.invalid' }]) await assert.rejects(config.save(input));
  await fs.writeFile(path.join(userData, 'tts', 'preferences.json'), JSON.stringify({ schema_version: 1, ...defaults, apiKey: 'forbidden' }));
  await assert.rejects(createSpeechConfig({ userData, safeStorage }), /字段/);
});
test('duplicate concurrent save cannot race consent or credentials', async t => {
  const { config } = await setup(t);
  const first = config.save(defaults);
  await assert.rejects(config.save({ ...defaults, enabled: true }), /正在保存/);
  await first;
  assert.equal(config.getPublicConfig().enabled, false);
});
