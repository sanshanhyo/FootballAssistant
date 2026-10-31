'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { verifyManifest, trustedReleaseUrl, compareVersions } = require('../src/update-security.cjs');
const { createUpdateController } = require('../src/update-controller.cjs');
const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
const pem = publicKey.export({ type: 'spki', format: 'pem' });
const root = 'https://github.com/sanshanhyo/FootballAssistant/releases/download/0.2.0-alpha.1/';
const bytes = Buffer.from('test package');
const context = { currentVersion: '0.1.0', platform: 'darwin', arch: 'arm64', configSchema: 1, backendProtocol: 1, bridgeProtocol: 1 };
function manifest(patch = {}) { return { schema: 1, channel: 'alpha', version: '0.2.0-alpha.1', expiresAt: '2099-01-01T00:00:00Z', configSchemas: [1], backendProtocol: 1, bridgeProtocol: 1, artifacts: [{ platform: 'darwin', arch: 'arm64', format: 'zip', url: `${root}app.zip`, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), size: bytes.length }], ...patch }; }
function sign(value) { const payload = JSON.stringify(value); return { payload, signature: crypto.sign(null, Buffer.from(payload), privateKey).toString('base64') }; }
test('strict semver ordering and HTTPS repository allowlist', () => {
  assert.equal(compareVersions('0.2.0-alpha.10', '0.2.0-alpha.2'), 1);
  assert.equal(compareVersions('0.2.0', '0.2.0-alpha.10'), 1);
  for (const url of ['http://github.com/sanshanhyo/FootballAssistant/releases/download/v/a.zip', `${root}app.zip?evil=1`, 'https://github.com/evil/repo/releases/download/v/a.zip', `${root}%2e%2e`]) assert.throws(() => trustedReleaseUrl(url));
});
test('signature, downgrade, expiry, platform and protocol gates fail closed', () => {
  assert.equal(verifyManifest(sign(manifest()), pem, context).version, '0.2.0-alpha.1');
  const tampered = sign(manifest()); tampered.payload += ' ';
  assert.throws(() => verifyManifest(tampered, pem, context), /signature/);
  for (const patch of [{ version: '0.0.9' }, { expiresAt: '2000-01-01' }, { artifacts: [] }, { configSchemas: [2] }, { backendProtocol: 2 }, { bridgeProtocol: 2 }]) assert.throws(() => verifyManifest(sign(manifest(patch)), pem, context));
  assert.throws(() => verifyManifest(sign(manifest()), pem, { ...context, backendProtocol: undefined }));
});
async function fixture(t, body = bytes, envelope = sign(manifest())) {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'football-update-'));
  t.after(() => fs.rm(cacheDir, { recursive: true, force: true }));
  let calls = 0;
  const controller = createUpdateController({ ...context, publicKey: pem, cacheDir, feedUrl: `${root}alpha-update.json`, fetchImpl: async url => { calls++; return new Response(url.endsWith('alpha-update.json') ? JSON.stringify(envelope) : body); } });
  return { controller, cacheDir, calls: () => calls };
}
test('detects, downloads and validates package without replacing or quitting app', async t => {
  const { controller, calls } = await fixture(t);
  assert.equal((await controller.check()).state, 'update_available');
  assert.equal((await controller.download()).state, 'downloaded');
  assert.deepEqual(await fs.readFile(controller.status.downloadedPath), bytes);
  await controller.check(); assert.equal(calls(), 2);
  assert.equal(controller.status.installMode, 'manual');
});
test('corrupt/oversized downloads are removed; retry remains possible', async t => {
  for (const body of [Buffer.from('bad'), Buffer.alloc(bytes.length), Buffer.alloc(bytes.length + 1)]) {
    const { controller, cacheDir } = await fixture(t, body);
    await controller.check(); assert.equal((await controller.download()).state, 'error');
    assert.deepEqual(await fs.readdir(cacheDir), []);
  }
});
test('current signed version reports up-to-date, deduplicates checks', async t => {
  const { controller, calls } = await fixture(t, bytes, sign(manifest({ version: '0.1.0' })));
  await Promise.all([controller.check(), controller.check()]);
  assert.equal(controller.status.state, 'up_to_date'); assert.equal(calls(), 1);
});
test('rejects redirect outside exact GitHub asset host', async () => {
  const controller = createUpdateController({ ...context, publicKey: pem, feedUrl: `${root}alpha-update.json`, fetchImpl: async () => new Response(null, { status: 302, headers: { location: 'https://evil.example/a' } }) });
  assert.equal((await controller.check()).state, 'error');
  assert.match(controller.status.reason, /redirect/);
});
function release(tag, patch = {}) { return { draft: false, prerelease: true, tag_name: tag, ...patch }; }
test('unsigned fallback checks fixed public repo without token, never downloads', async () => {
  const calls = [];
  const controller = createUpdateController({ ...context, fetchImpl: async (url, opts) => { calls.push({ url, opts }); return Response.json([release('v0.2.0-alpha.2'), release('0.2.0-alpha.10'), release('9.0.0-alpha.1', { draft: true }), release('v8.0.0'), release('v7.0.0-beta.1')]); } });
  const status = await controller.check();
  assert.equal(status.state, 'update_available'); assert.equal(status.availableVersion, '0.2.0-alpha.10');
  assert.equal(status.source, 'github-releases'); assert.equal(status.signedDownloadAvailable, false);
  assert.equal(status.releaseUrl, 'https://github.com/sanshanhyo/FootballAssistant/releases/tag/0.2.0-alpha.10');
  assert.equal((await controller.download()).state, 'manual_required');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://api.github.com/repos/sanshanhyo/FootballAssistant/releases?per_page=100&page=1');
  assert.equal(calls[0].opts.redirect, 'error'); assert.equal(calls[0].opts.headers.Authorization, undefined);
});
test('public fallback distinguishes no release, up-to-date and network errors', async () => {
  for (const [body, expected] of [[[], 'no_release'], [[release('0.0.9-alpha.1')], 'up_to_date']]) {
    const controller = createUpdateController({ ...context, fetchImpl: async () => Response.json(body) });
    assert.equal((await controller.check()).state, expected);
  }
  for (const code of [404, 403, 429, 500]) {
    const controller = createUpdateController({ ...context, fetchImpl: async () => new Response('', { status: code }) });
    assert.equal((await controller.check()).state, 'network_error');
  }
});
test('background public check runs without signing configuration and never fetches assets', async () => {
  let finish; const done = new Promise(resolve => { finish = resolve; }); let calls = 0;
  const controller = createUpdateController({ ...context, fetchImpl: async () => { calls++; return Response.json([release('0.2.0-alpha.1')]); }, onStatus: status => { if (status.state === 'update_available') finish(); } });
  controller.start(); await done; controller.stop();
  assert.equal(calls, 1); assert.equal(controller.status.state, 'update_available');
});
test('signed controller delegates to installed gate rather than manual artifact download', async () => {
  let staged = null, requests = 0;
  const envelope = sign(manifest());
  const controller = createUpdateController({ ...context, publicKey: pem, feedUrl: `${root}alpha-update.json`,
    installedUpdater: { status: { automaticInstallEnabled: true }, stage: async value => { staged = value; return { state: 'ready_for_safe_exit', reason: 'staged' }; } },
    fetchImpl: async () => { requests++; return Response.json(envelope); } });
  assert.equal(controller.status.automaticInstallEnabled, true);
  assert.equal(controller.status.installMode, 'idle-restart');
  await controller.check(); assert.equal((await controller.download()).state, 'ready_for_safe_exit');
  assert.deepEqual(staged, envelope); assert.equal(requests, 1);
});
test('unpublished signed channel reports no_release, never silently downloads unsigned assets', async () => {
  let calls = 0;
  const controller = createUpdateController({ ...context, publicKey: pem, feedUrl: `${root}alpha-update.json`, fetchImpl: async () => { calls++; return new Response('', { status: 404 }); } });
  assert.equal((await controller.check()).state, 'no_release'); assert.equal(calls, 1);
});
test('production contains only approved public Ed25519 trust and a fixed official feed', () => {
  const trust = require('../src/update-trust.cjs');
  const key = crypto.createPublicKey(trust.productionTrust.publicKey);
  assert.equal(key.asymmetricKeyType, 'ed25519');
  assert.equal(crypto.createHash('sha256').update(key.export({ type: 'spki', format: 'der' })).digest('hex'), '9e686e777a355634920d5dbf6e63bc282dfc8622ff480a75803b9040538bccfb');
  assert.equal(trust.productionTrust.trustPolicy, 'ed25519-pinned');
  assert.equal(trustedReleaseUrl(trust.feedUrl), 'https://github.com/sanshanhyo/FootballAssistant/releases/download/alpha-channel/alpha-update.json');
});
