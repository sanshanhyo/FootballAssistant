'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createUpdateLifecycle } = require('../src/update-lifecycle.cjs');
test('unknown/busy/game activity never dispatches install, idle does', async () => {
  let activity = 'unknown', calls = 0;
  const updater = { status: { state: 'ready_for_safe_exit' }, applyOnSafeExit: async opts => { assert.deepEqual(opts, { normalQuit: true, sessionEnding: false }); calls++; return { state: 'installing' }; } };
  const lifecycle = createUpdateLifecycle({ installedUpdater: updater, inspectActivity: async () => activity });
  for (const state of ['unknown', 'busy', 'game', null]) { activity = state; await lifecycle.check(); }
  assert.equal(calls, 0); activity = 'idle'; await lifecycle.check(); assert.equal(calls, 1);
  lifecycle.stop(); await lifecycle.check(); assert.equal(calls, 1);
});
test('concurrent idle checks coalesce and stopping in flight prevents installation', async () => {
  let release, calls = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const lifecycle = createUpdateLifecycle({ installedUpdater: { status: { state: 'ready_for_safe_exit' }, applyOnSafeExit: async () => { calls++; } }, inspectActivity: async () => { await gate; return 'idle'; } });
  const a = lifecycle.check(), b = lifecycle.check(); lifecycle.stop(); release(); await Promise.all([a, b]); assert.equal(calls, 0);
});
