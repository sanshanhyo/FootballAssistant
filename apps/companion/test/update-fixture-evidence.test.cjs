'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { assertEvidence } = require('./assert-update-fixture.cjs');
const { copyFixtureModules } = require('./update-native-fixture.cjs');

test('isolated updater fixture loads recovery with its transitive validation dependencies', async t => {
  const project = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'fa-fixture-modules-'));
  t.after(() => fs.rmSync(project, { recursive: true, force: true }));
  await copyFixtureModules(path.resolve(__dirname, '..'), project);
  const { createUpdateRecovery } = require(path.join(project, 'update-recovery.cjs'));
  const profile = path.join(project, 'profile');
  fs.mkdirSync(profile);
  fs.writeFileSync(path.join(profile, 'settings.json'), JSON.stringify({ version: 1, backend: { port: 17827 }, bridgePrivateRoot: '', backendEnvFile: '' }));
  const recovery = createUpdateRecovery({ userData: profile, currentVersion: '0.0.1-alpha.1' });
  assert.equal((await recovery.prepare({ targetVersion: '0.0.2-alpha.1' })).state, 'prepared');
});
test('fixture success requires actual upgrade evidence, never just process exit or passed flag', () => {
  assert.throws(() => assertEvidence({ passed: false, error: 'builder failure', events: '', requests: [] }));
  assert.throws(() => assertEvidence({ passed: true }));
  const data = { passed: true, actualNativeInstaller: true, actualDownload: true, actualRelaunch: true, settingsPreserved: true, healthAcknowledged: true, initialVersion: '0.0.1-alpha.1', targetVersion: '0.0.2-alpha.1', productionReadiness: false, authenticodeValidated: false, events: [{ step: 'launch', appVersion: '0.0.1-alpha.1' }, { step: 'launch', appVersion: '0.0.2-alpha.1', argvUpdated: true, recovery: 'awaiting_health' }, { step: 'target_healthy', appVersion: '0.0.2-alpha.1', settingsPreserved: true, recovery: 'healthy' }], requests: [{ method: 'GET', path: '/Fixture-0.0.2-alpha.1-Setup.exe' }] };
  assert.equal(assertEvidence(data), true);
  assert.throws(() => assertEvidence({ ...data, requests: [] }));
  assert.throws(() => assertEvidence({ ...data, events: data.events.slice(0, 2) }));
});
test('each fixture build gets unshared builder configuration and failures force nonzero exit', () => {
  const source = fs.readFileSync(path.join(__dirname, 'update-native-fixture.cjs'), 'utf8');
  assert.match(source, /structuredClone\(common\)/);
  assert.match(source, /console\.error\(error\.stack\); process\.exit\(1\)/);
});
