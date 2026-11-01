'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { createCredentialConfig, validateModelConfig } = require('../src/credentials.cjs');
const { allowsWindowIpc } = require('../src/companion-security.cjs');
const input = { provider: 'openai-compatible', baseUrl: 'https://example.test/v1', model: 'deepseek-v4.1-flash', apiKey: 'TEST-only-secret' };
function fixture(t, available = true) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'fa-creds-'));
  t.after(() => fs.rmSync(userData, { recursive: true, force: true }));
  const key = crypto.randomBytes(32);
  const safeStorage = {
    isEncryptionAvailable: () => available,
    encryptString: text => { const iv = crypto.randomBytes(16); const cipher = crypto.createCipheriv('aes-256-cbc', key, iv); return Buffer.concat([iv, cipher.update(text), cipher.final()]); },
    decryptString: data => { const cipher = crypto.createDecipheriv('aes-256-cbc', key, data.subarray(0, 16)); return Buffer.concat([cipher.update(data.subarray(16)), cipher.final()]).toString(); },
  };
  return { userData, safeStorage };
}
test('encrypted persistence: only backend receives key; public config and all files exclude plaintext', t => {
  const options = fixture(t); const store = createCredentialConfig(options);
  assert.equal(store.getPublicConfig().configured, false);
  const result = store.save(input);
  assert.equal(result.storage, 'encrypted'); assert.equal(result.hasApiKey, true);
  assert.equal(JSON.stringify(result).includes(input.apiKey), false);
  for (const file of fs.readdirSync(options.userData)) assert.equal(fs.readFileSync(path.join(options.userData, file), 'utf8').includes(input.apiKey), false);
  const restored = createCredentialConfig(options);
  assert.equal(restored.backendEnv().FOOTBALL_ASSISTANT_API_KEY, input.apiKey);
  assert.equal(Object.hasOwn(restored.getPublicConfig(), 'apiKey'), false);
});
test('unavailable safeStorage and Linux basic_text never persist plaintext or ciphertext', t => {
  for (const basic of [false, true]) {
    const options = fixture(t, basic);
    if (basic) options.safeStorage.getSelectedStorageBackend = () => 'basic_text';
    const store = createCredentialConfig(options);
    assert.equal(store.save(input).storage, 'session');
    assert.equal(store.backendEnv().FOOTBALL_ASSISTANT_API_KEY, input.apiKey);
    assert.equal(fs.existsSync(path.join(options.userData, 'credentials.enc.json')), false);
    assert.equal(createCredentialConfig(options).getPublicConfig().hasApiKey, false);
  }
});
test('destination changes clear old key; explicit removal survives restart', t => {
  const options = fixture(t); const store = createCredentialConfig(options); store.save(input);
  const { apiKey, ...publicInput } = input;
  assert.equal(store.save(publicInput).hasApiKey, true);
  assert.equal(store.save({ ...publicInput, baseUrl: 'https://other.test/v1' }).hasApiKey, false);
  store.save(input); store.save({ ...publicInput, removeKey: true });
  assert.equal(createCredentialConfig(options).getPublicConfig().hasApiKey, false);
});
test('strict validation rejects unknown fields and unsafe endpoint/key values without echoing secrets', () => {
  for (const patch of [{ unknown: 1 }, { baseUrl: 'http://example.test' }, { baseUrl: 'https://u:password@example.test' }, { baseUrl: 'https://example.test?key=secret' }, { model: '' }, { apiKey: 'bad\nsecret' }, { removeKey: 'yes' }, { removeKey: true }]) {
    assert.throws(() => validateModelConfig({ ...input, ...patch }), error => !error.message.includes('password') && !error.message.includes('bad\nsecret'));
  }
});
test('schema migration is backed up, future/unknown fields are not overwritten', t => {
  const options = fixture(t); const file = path.join(options.userData, 'model-config.json');
  const { apiKey, ...legacy } = input;
  fs.writeFileSync(file, JSON.stringify(legacy)); createCredentialConfig(options);
  assert.equal(JSON.parse(fs.readFileSync(file)).schema_version, 1);
  assert.deepEqual(JSON.parse(fs.readFileSync(`${file}.bak`)), legacy);
  for (const invalid of [{ ...legacy, schema_version: 2 }, { ...legacy, apiKey: 'secret' }]) {
    fs.writeFileSync(file, JSON.stringify(invalid)); assert.throws(() => createCredentialConfig(options));
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), invalid);
  }
});
test('credentials IPC is settings main-frame only, never pet-accessible', () => {
  for (const method of ['model-providers-get', 'model-models-list', 'model-models-cancel', 'model-config-get', 'model-config-save', 'persona-status', 'persona-open-file', 'persona-open-folder', 'update-open-release']) {
    const context = { role: 'settings', trustedMainFrame: true, currentUrl: 'file://settings', pageUrl: 'file://settings' };
    assert.equal(allowsWindowIpc(context, method), true);
    assert.equal(allowsWindowIpc({ ...context, role: 'pet' }, method), false);
    assert.equal(allowsWindowIpc({ ...context, trustedMainFrame: false }, method), false);
    assert.equal(allowsWindowIpc({ ...context, currentUrl: 'https://evil.test' }, method), false);
  }
});
test('UI uses masked input, no secret readback, and preloads expose only sanitized operations', () => {
  const src = name => fs.readFileSync(path.join(__dirname, '../src', name), 'utf8');
  assert.match(src('settings.html'), /id="model-api-key" type="password"/);
  assert.match(src('settings.js'), /\$\('model-api-key'\)\.value = ''/);
  assert.doesNotMatch(src('settings.js'), /value\.apiKey/);
  assert.doesNotMatch(src('preload.cjs'), /backendEnv/);
});
// Six-page UI secret lifecycle is exercised by settings-pages.test.cjs.
test('legacy nonstandard preset is custom and cannot reuse the old bound secret', t => {
  const options=fixture(t); const store=createCredentialConfig(options);
  store.save(input);
  const configFile=path.join(options.userData,'model-config.json');
  fs.writeFileSync(configFile,JSON.stringify({...store.getPublicConfig(),configured:undefined,hasApiKey:undefined,storage:undefined,secureStorageAvailable:undefined,provider:'opencode-go'}));
  fs.writeFileSync(path.join(options.userData,'credentials.enc.json'),JSON.stringify({schema_version:1,ciphertext:options.safeStorage.encryptString(JSON.stringify({...input,provider:'opencode-go'})).toString('base64')}));
  const restored=createCredentialConfig(options);
  assert.equal(restored.getPublicConfig().provider,'openai-compatible');
  assert.equal(restored.getPublicConfig().hasApiKey,false);
  assert.equal(restored.getPublicConfig().baseUrl,input.baseUrl);
});
