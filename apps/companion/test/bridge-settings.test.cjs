'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { mountBridgeSettings } = require('../src/bridge-settings.js');
const { createBridgeDeployment } = require('../src/bridge-ipc.cjs');
const { allowsWindowIpc } = require('../src/companion-security.cjs');
function ui(api) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { checked: false, hidden: false, disabled: false, textContent: '', handlers: {}, children: [], addEventListener(event, fn) { this.handlers[event] = fn; }, append(...children) { this.children.push(...children); }, replaceChildren() { this.children = []; } });
    return elements.get(id);
  };
  const controller = mountBridgeSettings({ api, document: { getElementById: get, createElement: () => get(Symbol()) } });
  return { get, controller, click: id => get(id).handlers.click(), check: id => { get(id).checked = true; get(id).handlers.change(); } };
}
const ok = value => ({ ok: true, value });
const plan = { state: 'planned', canEnable: true, planId: 'TEST-plan', gamePath: '/TEST/FM.app', privateRoot: '/TEST/private', gameVersion: 'TEST-version', architecture: 'arm64', changes: ['TEST private copy only'] };
test('UI demands three explicit unchecked consents and never sends filesystem paths', async () => {
  let deployed;
  const f = ui({ bridgeInspect: async () => ok({ state: 'ready' }), bridgePlan: async () => ok(plan), bridgeDeploy: async value => { deployed = value; return ok({ state: 'deployed', canRollback: true }); } });
  await f.controller.refresh(); await f.click('bridge-select');
  assert.equal(f.get('bridge-plan').hidden, false); assert.equal(f.get('bridge-enable').disabled, true);
  await f.click('bridge-enable'); assert.equal(deployed, undefined);
  f.check('bridge-consent-copy'); f.check('bridge-consent-signing'); assert.equal(f.get('bridge-enable').disabled, true);
  f.check('bridge-consent-jit'); await f.click('bridge-enable');
  assert.deepEqual(deployed, { planId: 'TEST-plan', enable: true, allowShadowSigning: true, allowJit: true });
  assert.equal(f.get('bridge-consent-jit').checked, false); assert.equal(f.get('bridge-rollback').disabled, true);
});
test('unsupported/missing payload never enables; cancelled and failed planning do not preserve consent', async () => {
  const api = { bridgeInspect: async () => ok({ state: 'payload_unavailable' }), bridgePlan: async () => ok(plan) };
  const f = ui(api); await f.controller.refresh(); assert.equal(f.get('bridge-select').disabled, true); assert.match(f.get('bridge-status').textContent, /缺少/);
  api.bridgeInspect = async () => ok({ state: 'unsupported_platform' }); await f.controller.refresh(); assert.match(f.get('bridge-status').textContent, /Windows/);
  api.bridgeInspect = async () => ok({ state: 'ready' }); await f.controller.refresh(); await f.click('bridge-select'); f.check('bridge-consent-copy');
  api.bridgePlan = async () => ok({ cancelled: true }); await f.click('bridge-select'); assert.equal(f.get('bridge-consent-copy').checked, false);
  api.bridgePlan = async () => ({ ok: false, error: 'TEST stale game' }); await f.click('bridge-select'); assert.equal(f.get('bridge-plan').hidden, true); assert.equal(f.get('bridge-enable').disabled, true);
});
test('main IPC takes path only from picker, rejects extra fields and missing independent consent', async () => {
  const handlers = {}, calls = [];
  const setup = { inspect: async () => ({}), plan: async value => { calls.push(value); return plan; }, deploy: async value => value, rollback: async () => ({}) };
  const bridge = createBridgeDeployment({ setup, chooseGame: async () => '/native-picker/FM.app' }); bridge.register((name, handler) => { handlers[name] = handler; });
  await handlers['bridge-plan'](); assert.deepEqual(calls, ['/native-picker/FM.app']);
  assert.throws(() => handlers['bridge-plan']('/renderer/arbitrary.app'));
  const valid = { planId: 'TEST', enable: true, allowShadowSigning: true, allowJit: true };
  for (const patch of [{ allowJit: false }, { allowShadowSigning: false }, { enable: false }, { gamePath: '/evil' }]) assert.throws(() => handlers['bridge-deploy']({ ...valid, ...patch }));
  assert.deepEqual(await handlers['bridge-deploy'](valid), valid);
});
test('main serializes pending operations and honors shutdown/update gate', async () => {
  const handlers = {}; let finish; let allowed = true;
  const setup = { inspect: () => new Promise(resolve => { finish = resolve; }), rollback: async () => ({}) };
  const bridge = createBridgeDeployment({ setup, chooseGame: async () => null, canMutate: () => allowed }); bridge.register((name, fn) => { handlers[name] = fn; });
  const pending = handlers['bridge-inspect'](); assert.equal(bridge.busy, true);
  await assert.rejects(handlers['bridge-rollback']()); finish({}); await pending; assert.equal(bridge.busy, false);
  allowed = false; await assert.rejects(handlers['bridge-rollback']()); assert.equal(bridge.busy, false);
});
test('bridge IPC is settings main-frame only', () => {
  const context = { role: 'settings', trustedMainFrame: true, currentUrl: 'file://settings', pageUrl: 'file://settings' };
  for (const name of ['bridge-inspect', 'bridge-plan', 'bridge-deploy', 'bridge-rollback']) {
    assert.equal(allowsWindowIpc(context, name), true);
    assert.equal(allowsWindowIpc({ ...context, role: 'pet' }, name), false);
    assert.equal(allowsWindowIpc({ ...context, trustedMainFrame: false }, name), false);
  }
});
