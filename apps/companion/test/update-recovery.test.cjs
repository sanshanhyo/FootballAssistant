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

test('upgrade checkpoints preserve allowlisted account, history, memories and persona without decrypting or touching live data',async t=>{
  const f=await fixture(t);await fs.mkdir(path.join(f.userData,'backend'));
  const originals={
    'companion-ui.json':JSON.stringify({version:1,historyEnabled:true,messages:[{id:'synthetic',text:'fixture history'}],memories:[{id:'fixture',text:'fixture memory'}]}),
    'model-config.json':JSON.stringify({schema_version:1,provider:'openai-compatible',baseUrl:'https://fixture.test/v1',model:'fixture-model'}),
    'credentials.enc.json':JSON.stringify({schema_version:1,ciphertext:Buffer.from('opaque synthetic ciphertext').toString('base64')}),
    'backend/persona.md':'# User-authored fixture persona\nKeep my words.\n',
  };
  for(const [name,bytes] of Object.entries(originals))await fs.writeFile(path.join(f.userData,name),bytes);
  await fs.writeFile(path.join(f.userData,'backend','live.sqlite'),'not a snapshot candidate');
  const prepared=await f.create().prepare({targetVersion});assert.equal(prepared.state,'prepared');assert.equal(prepared.snapshots.length,4);
  for(const entry of prepared.snapshots){assert.equal(await fs.readFile(path.join(path.dirname(prepared.journalPath),entry.backup),'utf8'),originals[entry.source]);}
  const after=f.create(targetVersion);await after.beginLaunch();await after.fail('synthetic startup failure');
  assert.equal((await f.create(targetVersion).beginLaunch()).state,'recovery_required');
  for(const [name,bytes] of Object.entries(originals))assert.equal(await fs.readFile(path.join(f.userData,name),'utf8'),bytes);
  assert.equal(prepared.snapshots.some(x=>x.source.includes('sqlite')),false);
  assert.ok(!JSON.stringify(prepared).includes('opaque synthetic'));
});
test('corrupted user-data checkpoint blocks automatic upgrades without restoring stale user files',async t=>{
  const f=await fixture(t);await fs.writeFile(path.join(f.userData,'companion-ui.json'),'{"version":1,"messages":[]}');
  const prepared=await f.create().prepare({targetVersion});await fs.writeFile(path.join(path.dirname(prepared.journalPath),prepared.snapshots[0].backup),'tampered');
  const newer='{"version":1,"messages":[{"id":"new"}]}';await fs.writeFile(path.join(f.userData,'companion-ui.json'),newer);
  assert.equal((await f.create(targetVersion).beginLaunch()).state,'recovery_required');assert.equal(await fs.readFile(path.join(f.userData,'companion-ui.json'),'utf8'),newer);
});
test('an outside persona edit during checkpoint blocks installation and preserves the editor content',async t=>{
  const f=await fixture(t);await fs.mkdir(path.join(f.userData,'backend'));
  const persona=path.join(f.userData,'backend','persona.md');await fs.writeFile(persona,'original synthetic persona');
  const open=fs.open.bind(fs);
  t.mock.method(fs,'open',async(...args)=>{
    const handle=await open(...args);
    if(path.basename(String(args[0])).startsWith('data-')){
      const write=handle.writeFile.bind(handle);handle.writeFile=async bytes=>{await write(bytes);await fs.writeFile(persona,'outside editor changed this');};
    }
    return handle;
  });
  assert.equal((await f.create().prepare({targetVersion})).state,'recovery_required');
  assert.equal(await fs.readFile(persona,'utf8'),'outside editor changed this');
});

test('legacy schema-one journal without snapshots completes its first upgraded launch', async t => {
  const f = await fixture(t);
  const prepared = await f.create().prepare({ targetVersion });
  const journal = JSON.parse(await fs.readFile(prepared.journalPath, 'utf8'));
  delete journal.snapshots;
  await fs.writeFile(prepared.journalPath, JSON.stringify(journal));
  const updated = f.create(targetVersion);
  assert.equal((await updated.beginLaunch()).state, 'awaiting_health');
  assert.equal((await updated.acknowledgeHealthy()).state, 'healthy');
  assert.equal((await f.create(targetVersion).beginLaunch()).state, 'healthy');
  assert.deepEqual(JSON.parse(await fs.readFile(prepared.backupPath, 'utf8')), settings);
});

test('future settings, conversation and journal schemas retain their exact original bytes', async t => {
  for (const source of ['settings.json', 'companion-ui.json', 'updates/recovery/journal.json']) {
    const f = await fixture(t);
    const file = path.join(f.userData, source);
    await fs.mkdir(path.dirname(file), { recursive: true });
    const original = Buffer.from(source.endsWith('journal.json')
      ? '{ "schema": 99, "futureField": "keep journal" }\n'
      : '{ "version": 99, "futureField": "keep user data" }\n');
    await fs.writeFile(file, original);
    const updater = f.create();
    if (source.endsWith('journal.json')) assert.equal((await updater.beginLaunch()).state, 'recovery_required');
    assert.equal((await updater.prepare({ targetVersion })).state, 'recovery_required');
    await updater.fail('synthetic failure');
    await updater.acknowledgeHealthy();
    assert.deepEqual(await fs.readFile(file), original, source);
  }
});

test('A to B to C upgrades retain each immutable checkpoint and current user data', async t => {
  const f = await fixture(t);
  const thirdVersion = '0.0.3-alpha.1';
  await fs.mkdir(path.join(f.userData, 'backend'));
  const versions = ['A', 'B', 'C'].map(label => ({
    'companion-ui.json': JSON.stringify({ version: 1, messages: [{ id: label, text: `history ${label}` }], memories: [{ id: label, text: `memory ${label}` }] }),
    'backend/persona.md': `User-authored persona ${label}\n`,
  }));
  const write = async data => { for (const [name, bytes] of Object.entries(data)) await fs.writeFile(path.join(f.userData, name), bytes); };
  const checkSnapshot = async (state, data) => {
    assert.equal(state.snapshots.length, 2);
    for (const entry of state.snapshots) assert.equal(await fs.readFile(path.join(path.dirname(state.journalPath), entry.backup), 'utf8'), data[entry.source]);
  };
  await write(versions[0]);
  const first = await f.create().prepare({ targetVersion });
  assert.equal(first.state, 'prepared');
  const second = f.create(targetVersion);
  assert.equal((await second.beginLaunch()).state, 'awaiting_health');
  assert.equal((await second.acknowledgeHealthy()).state, 'healthy');
  await write(versions[1]);
  const next = await second.prepare({ targetVersion: thirdVersion });
  assert.equal(next.state, 'prepared');
  assert.equal(next.previousVersion, targetVersion);
  assert.notEqual(next.transaction, first.transaction);
  const third = f.create(thirdVersion);
  assert.equal((await third.beginLaunch()).state, 'awaiting_health');
  await write(versions[2]);
  assert.equal((await third.acknowledgeHealthy()).state, 'healthy');
  assert.equal((await f.create(thirdVersion).beginLaunch()).state, 'healthy');
  await checkSnapshot(first, versions[0]);
  await checkSnapshot(next, versions[1]);
  for (const [name, bytes] of Object.entries(versions[2])) assert.equal(await fs.readFile(path.join(f.userData, name), 'utf8'), bytes);
});

test('failed upgraded launch never restores old history or persona over newer edits', async t => {
  const f = await fixture(t);
  await fs.mkdir(path.join(f.userData, 'backend'));
  const original = {
    'companion-ui.json': '{"version":1,"messages":[{"id":"before-update"}],"memories":[]}',
    'backend/persona.md': 'My original synthetic persona\n',
  };
  const newer = {
    'companion-ui.json': '{"version":1,"messages":[{"id":"before-update"},{"id":"after-update"}],"memories":[{"id":"new-memory"}]}',
    'backend/persona.md': 'My newly edited synthetic persona\n',
  };
  for (const [name, bytes] of Object.entries(original)) await fs.writeFile(path.join(f.userData, name), bytes);
  const prepared = await f.create().prepare({ targetVersion });
  assert.equal(prepared.state, 'prepared');
  assert.equal((await f.create(targetVersion).beginLaunch()).state, 'awaiting_health');
  for (const [name, bytes] of Object.entries(newer)) await fs.writeFile(path.join(f.userData, name), bytes);
  // The previous process crashed without acknowledging health.
  const restarted = f.create(targetVersion);
  assert.equal((await restarted.beginLaunch()).state, 'recovery_required');
  assert.equal((await restarted.acknowledgeHealthy()).state, 'recovery_required');
  assert.equal((await restarted.prepare({ targetVersion: '0.0.3-alpha.1' })).state, 'recovery_required');
  await restarted.fail('synthetic repeated failure');
  for (const [name, bytes] of Object.entries(newer)) assert.equal(await fs.readFile(path.join(f.userData, name), 'utf8'), bytes);
  for (const entry of prepared.snapshots) assert.equal(await fs.readFile(path.join(path.dirname(prepared.journalPath), entry.backup), 'utf8'), original[entry.source]);
});
