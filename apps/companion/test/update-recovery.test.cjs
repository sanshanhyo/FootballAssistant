'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createUpdateRecovery } = require('../src/update-recovery.cjs');
const oldVersion = '0.0.1-alpha.1', targetVersion = '0.0.2-alpha.1';
const settings = { version: 1, backend: { port: 17827 }, bridgePrivateRoot: '', backendEnvFile: '' };
async function fixture(t) {
  const userData = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-recovery-'));
  t.after(() => fs.rm(userData, { recursive: true, force: true }));
  await fs.writeFile(path.join(userData, 'settings.json'), JSON.stringify(settings));
  return { userData, create: (currentVersion = oldVersion) => createUpdateRecovery({ userData, currentVersion }) };
}
test('prepare retains only explicit non-secret settings and previous version', async t => {
  const f = await fixture(t);
  await fs.writeFile(path.join(f.userData, 'model-credentials.json'), 'private-test-value');
  const state = await f.create().prepare({ targetVersion });
  assert.equal(state.state, 'prepared'); assert.equal(state.previousVersion, oldVersion);
  assert.deepEqual(JSON.parse(await fs.readFile(state.backupPath, 'utf8')), settings);
  assert.deepEqual((await fs.readdir(path.dirname(state.journalPath))).sort(), [path.basename(state.backupPath), 'journal.json'].sort());
});
test('target first launch requires backend/UI health acknowledgement; healthy record survives restart', async t => {
  const f = await fixture(t); await f.create().prepare({ targetVersion });
  const updated = f.create(targetVersion);
  assert.equal((await updated.beginLaunch()).state, 'awaiting_health');
  assert.equal((await updated.beginLaunch()).state, 'awaiting_health'); // idempotent per process
  assert.equal((await updated.acknowledgeHealthy()).state, 'healthy');
  assert.equal((await f.create(targetVersion).beginLaunch()).state, 'healthy');
});
test('unacknowledged first launch crash requests recovery and preserves newer settings', async t => {
  const f = await fixture(t); const prepared = await f.create().prepare({ targetVersion });
  await f.create(targetVersion).beginLaunch();
  const newer = { ...settings, backend: { port: 19999 } };
  await fs.writeFile(path.join(f.userData, 'settings.json'), JSON.stringify(newer));
  const failed = f.create(targetVersion);
  assert.equal((await failed.beginLaunch()).state, 'recovery_required');
  assert.equal((await failed.acknowledgeHealthy()).state, 'recovery_required');
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(f.userData, 'settings.json'), 'utf8')), newer);
  assert.deepEqual(JSON.parse(await fs.readFile(prepared.backupPath, 'utf8')), settings);
});
test('old version starting after preparation identifies installation failure', async t => {
  const f = await fixture(t); await f.create().prepare({ targetVersion });
  const state = await f.create().beginLaunch();
  assert.equal(state.state, 'recovery_required'); assert.match(state.reason, /Expected updated version/);
});
test('explicit startup failure is persisted and blocks another unattended update', async t => {
  const f = await fixture(t); await f.create().prepare({ targetVersion });
  const updated = f.create(targetVersion); await updated.beginLaunch();
  assert.equal((await updated.fail('Backend unavailable')).state, 'recovery_required');
  assert.equal((await updated.prepare({ targetVersion: '0.0.3-alpha.1' })).state, 'recovery_required');
  assert.equal((await f.create(targetVersion).beginLaunch()).reason, 'Backend unavailable');
});
test('corrupt journal is retained, fails closed, and is not overwritten by prepare/fail', async t => {
  const f = await fixture(t); const prepared = await f.create().prepare({ targetVersion });
  await fs.writeFile(prepared.journalPath, '{ corrupt');
  const updated = f.create(targetVersion);
  assert.equal((await updated.beginLaunch()).state, 'recovery_required');
  await updated.prepare({ targetVersion: '0.0.3-alpha.1' }); await updated.fail('another failure');
  assert.equal(await fs.readFile(prepared.journalPath, 'utf8'), '{ corrupt');
});
test('missing or changed settings backup fails closed', async t => {
  for (const remove of [true, false]) {
    const f = await fixture(t); const state = await f.create().prepare({ targetVersion });
    if (remove) await fs.rm(state.backupPath); else await fs.writeFile(state.backupPath, '{}');
    assert.equal((await f.create(targetVersion).beginLaunch()).state, 'recovery_required');
  }
});
test('unknown or secret-containing settings schema is never copied', async t => {
  for (const patch of [{ version: 2 }, { apiKey: 'not-a-real-key' }, { backend: { port: 17827, token: 'not-a-real-token' } }]) {
    const f = await fixture(t); await fs.writeFile(path.join(f.userData, 'settings.json'), JSON.stringify({ ...settings, ...patch }));
    const state = await f.create().prepare({ targetVersion });
    assert.equal(state.state, 'recovery_required');
    assert.deepEqual(await fs.readdir(path.join(f.userData, 'updates', 'recovery')), []);
  }
});
test('completed upgrades retain previous immutable backups on next preparation', async t => {
  const f = await fixture(t); const first = await f.create().prepare({ targetVersion });
  const updated = f.create(targetVersion); await updated.beginLaunch(); await updated.acknowledgeHealthy();
  const second = await updated.prepare({ targetVersion: '0.0.3-alpha.1' });
  assert.equal(second.state, 'prepared'); assert.notEqual(second.backupPath, first.backupPath);
  assert.deepEqual(await fs.readFile(first.backupPath), await fs.readFile(second.backupPath));
});
test('fresh launch is idle and stale/downgrade preparation does not alter settings', async t => {
  const f = await fixture(t); const updater = f.create();
  assert.equal((await updater.beginLaunch()).state, 'idle');
  assert.equal((await updater.prepare({ targetVersion: oldVersion })).state, 'recovery_required');
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(f.userData, 'settings.json'), 'utf8')), settings);
});
test('old executable after a healthy upgrade requires explicit compatibility recovery', async t => {
  const f = await fixture(t); await f.create().prepare({ targetVersion });
  const updated = f.create(targetVersion); await updated.beginLaunch(); await updated.acknowledgeHealthy();
  assert.equal((await f.create(oldVersion).beginLaunch()).state, 'recovery_required');
});
test('health acknowledgement cannot skip first-launch journal processing', async t => {
  const f = await fixture(t); await f.create().prepare({ targetVersion });
  await f.create(targetVersion).beginLaunch();
  const another = f.create(targetVersion);
  assert.equal((await another.acknowledgeHealthy()).state, 'awaiting_health');
  assert.equal((await another.beginLaunch()).state, 'recovery_required');
});
