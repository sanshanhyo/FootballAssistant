'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');
const { createInstalledUpdater } = require('../src/update-installed.cjs');
const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
const pem = publicKey.export({ type: 'spki', format: 'pem' });
const context = { platform: 'win32', distribution: 'nsis', arch: 'x64', currentVersion: '0.0.1-alpha.1', configSchema: 1, backendProtocol: 1, bridgeProtocol: 1 };
const content = Buffer.from('mock installer, not executable');
const payload = { schema: 1, channel: 'alpha', version: '0.0.2-alpha.1', expiresAt: '2099-01-01T00:00:00Z', configSchemas: [1], backendProtocol: 1, bridgeProtocol: 1, artifacts: [{ platform: 'win32', arch: 'x64', format: 'exe', installerType: 'nsis', size: content.length, sha256: crypto.createHash('sha256').update(content).digest('hex'), url: 'https://github.com/sanshanhyo/FootballAssistant/releases/download/0.0.2-alpha.1/setup.exe' }] };
function signed(data = payload) { const payload = JSON.stringify(data); return { payload, signature: crypto.sign(null, Buffer.from(payload), privateKey).toString('base64') }; }
async function fixture(t, overrides = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'installed-update-')); t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'setup.exe'); await fs.writeFile(file, content);
  let installs = 0, downloads = 0, signatures = 0, safe = true;
  const native = new EventEmitter();
  native.checkForUpdates = async () => ({ updateInfo: { version: payload.version } });
  native.downloadUpdate = async () => { downloads++; return [file]; };
  native.quitAndInstall = (silent, restart) => { assert.equal(silent, true); assert.equal(restart, false); installs++; };
  const updater = createInstalledUpdater({ ...context, productionTrust: { publicKey: pem, certificateThumbprints: ['A'.repeat(40)] }, nativeFactory: () => native, verifySignature: async () => { signatures++; }, isSafeToInstall: () => safe, ...overrides });
  return { updater, native, file, setSafe: x => { safe = x; }, counts: () => ({ installs, downloads, signatures }) };
}
test('missing trust, Mac, portable and unknown never instantiate native updater', async () => {
  for (const patch of [{ productionTrust: undefined }, { platform: 'darwin' }, { distribution: 'portable' }, { distribution: 'unknown' }]) {
    let called = false;
    const updater = createInstalledUpdater({ ...context, productionTrust: { publicKey: pem, certificateThumbprints: ['A'.repeat(40)] }, ...patch, nativeFactory: () => { called = true; throw Error('unexpected'); } });
    assert.equal((await updater.stage(signed())).state, 'manual_required');
    assert.equal((await updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'manual_required');
    assert.equal(called, false); assert.equal(updater.status.automaticInstallEnabled, false);
  }
});
test('matching signed installer stages; no auto quit hook; safe normal exit installs once', async t => {
  const f = await fixture(t);
  assert.equal((await f.updater.stage(signed())).state, 'ready_for_safe_exit');
  assert.equal(f.native.autoInstallOnAppQuit, false); assert.equal(f.native.autoDownload, false); assert.equal(f.native.allowDowngrade, false);
  assert.equal(f.counts().installs, 0);
  assert.equal((await f.updater.applyOnSafeExit()).state, 'deferred');
  f.setSafe(false);
  assert.equal((await f.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'deferred');
  f.setSafe(true);
  assert.equal((await f.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'installing');
  await f.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false });
  assert.deepEqual(f.counts(), { installs: 1, downloads: 1, signatures: 2 });
});
test('metadata mismatch and non-NSIS signed artifact block before download', async t => {
  const f = await fixture(t); f.native.checkForUpdates = async () => ({ updateInfo: { version: '9.0.0' } });
  assert.equal((await f.updater.stage(signed())).state, 'blocked'); assert.equal(f.counts().downloads, 0);
  const other = { ...payload, artifacts: [{ ...payload.artifacts[0], installerType: 'portable' }] };
  assert.equal((await f.updater.stage(signed(other))).state, 'blocked'); assert.equal(f.counts().downloads, 0);
});
test('untrusted signature or modified cached bytes never install', async t => {
  const bad = await fixture(t, { verifySignature: async () => { throw new Error('Untrusted publisher'); } });
  assert.equal((await bad.updater.stage(signed())).state, 'blocked'); assert.equal(bad.counts().installs, 0);
  const f = await fixture(t); await f.updater.stage(signed()); await fs.writeFile(f.file, Buffer.alloc(content.length));
  assert.equal((await f.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'blocked');
  assert.equal(f.counts().installs, 0);
});
test('stop and active work detected after verification prevent dispatch', async t => {
  const f = await fixture(t); await f.updater.stage(signed()); f.updater.stop();
  assert.equal((await f.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'manual_required'); assert.equal(f.counts().installs, 0);
  let count = 0;
  const race = await fixture(t, { isSafeToInstall: () => ++count === 1 }); await race.updater.stage(signed());
  assert.equal((await race.updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false })).state, 'deferred'); assert.equal(race.counts().installs, 0);
});
