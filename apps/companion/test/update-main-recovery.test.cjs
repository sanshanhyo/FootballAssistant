'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Execute the production main recovery function with controlled process/service
// collaborators, without booting Electron or touching any real backend process.
const source = fs.readFileSync(path.join(__dirname, '../src/main.cjs'), 'utf8');
const recoveryFunction = source.slice(source.indexOf('async function recoverFailedUpdate(error) {'), source.indexOf('async function main() {'));
const prepareFunction = source.slice(source.indexOf('async function prepareUpdateRestart({ targetVersion }) {'), source.indexOf('async function recoverFailedUpdate(error) {'));

test('update checkpoint follows UI flush and owned helper stop; failed flush never snapshots', async () => {
  for (const failFlush of [false, true]) {
    const events=[];
    const context={detectGame:async()=>({state:'not_detected'}),updateSafeNow:()=>true,lastGameClearAt:0,updateQuiescing:false,updateBackendStopped:false,updateSessionEnding:false,
      runtime:{storageWarning:null,async persist(){events.push('flush');if(failFlush)this.storageWarning='failed';}},
      win:{webContents:{session:{flushStorageData(){events.push('appearance-flush');}}}},
      backendSupervisor:{status:{owned:true},async stop(){events.push('stop');}},
      updateRecovery:{async prepare(){events.push('snapshot');return {state:'prepared'};}}};
    vm.createContext(context);
    const promise=vm.runInContext(prepareFunction+';prepareUpdateRestart({targetVersion:"0.0.2"})',context);
    if(failFlush) { await assert.rejects(promise,/could not be saved/);assert.deepEqual(events,['flush']); }
    else {await promise;assert.deepEqual(events,['flush','appearance-flush','stop','snapshot']);}
  }
});
function fixture(stopped, startFailure = false) {
  const events = []; let rebuilds = 0, stoppedTimers = 0;
  const original = { ownedMarker: true };
  const context = {
    updateLifecycle: { stop() { stoppedTimers++; } }, updateController: { stop() { stoppedTimers++; }, status: {} },
    updateRecovery: { async fail() {}, status: { state: 'recovery_required' } },
    updateBackendStopped: stopped, updateQuiescing: true, quitting: false, updateSessionEnding: false,
    backendOptions: {}, credentials: { getPublicConfig: () => ({ configured: false }) }, bootstrapStatus: {}, installedUpdates: { status: { state: 'blocked' } },
    backendSupervisor: original, emit: event => events.push(event),
    BackendSupervisor: class { constructor() { rebuilds++; } async start() { if (startFailure) throw Error('start failed'); return { state: 'ready', owned: true }; } }
  };
  vm.createContext(context);
  return { context, original, events, counts: () => ({ rebuilds, stoppedTimers }), run: () => vm.runInContext(recoveryFunction + ';recoverFailedUpdate(new Error("installer verification failed"))', context) };
}
test('failure before backend stop retains ownership of the still-running service', async () => {
  const f = fixture(false); await f.run();
  assert.equal(f.context.backendSupervisor, f.original);
  assert.equal(f.counts().rebuilds, 0);
  assert.equal(f.context.updateQuiescing, false); assert.equal(f.context.updateBackendStopped, false);
  assert.equal(f.events.at(-1).state.state, 'recovery_required');
});
test('failure after backend stop reconstructs and starts the owned supervisor', async () => {
  const f = fixture(true); await f.run();
  assert.notEqual(f.context.backendSupervisor, f.original);
  assert.equal(f.counts().rebuilds, 1); assert.equal(f.counts().stoppedTimers, 2);
  assert.equal(f.context.bootstrapStatus.backend.state, 'ready');
  assert.equal(f.context.updateQuiescing, false);
});
test('backend restore failure remains explicit and cannot leave UI permanently frozen', async () => {
  const f = fixture(true, true); await f.run();
  assert.equal(f.context.bootstrapStatus.backend.state, 'failed');
  assert.match(f.context.bootstrapStatus.backend.message, /恢复失败/);
  assert.equal(f.context.updateQuiescing, false);
  assert.equal(f.events.at(-1).state.state, 'recovery_required');
});
