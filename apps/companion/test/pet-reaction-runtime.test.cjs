'use strict';
const test = require('node:test'); const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events'); const fs = require('node:fs'); const path = require('node:path'); const os = require('node:os');
const { createPetReactionRuntime } = require('../src/pet-reaction-runtime.cjs');
async function setup(t, reply) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fa-reaction-integration-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const runtime = new EventEmitter(), motions = [], messages = []; let calls = 0;
  Object.assign(runtime, { epoch: 1, sessionId: 'conversation', characterId: 'official.eckera', verifiedSave: true, state() { return { mode: 'real', epoch: this.epoch, sessionId: this.sessionId, proactivity: 80, characterScope: { verifiedSave: this.verifiedSave } }; }, characterContext() { return { save_id: 'verified-save', character_id: this.characterId, persona: 'fixture' }; }, realClient: { reply: async input => { calls++; return reply ? reply(input) : { text: 'A bounded fixture response', metadata: {}, cards: [] }; } }, addMessage(value) { messages.push(value); }, changed() { this.emit('event', { type: 'state' }); } });
  const adapter = await createPetReactionRuntime({ runtime, journalFile: path.join(root, 'journal.json'), preferencesFile: path.join(root, 'preferences.json'), emit: event => motions.push(event) }); t.after(() => adapter.dispose());
  return { runtime, adapter, messages, motions, calls: () => calls };
}
function observation(phase) { const now = Date.now(); return { verified: true, saveId: 'verified-save', matchId: 'fixture-match', playerTeamId: 'home', homeTeamId: 'home', awayTeamId: 'away', phase, homeScore: 2, awayScore: 1, observedAt: now, ...(phase === 'final' ? { finishedAt: now } : {}) }; }
test('default opt-out and unknown reader identity cannot invoke model', async t => {
  const f = await setup(t); await f.adapter.observeVerified(observation('live')); await f.adapter.observeVerified(observation('final')); assert.equal(f.calls(), 0);
  await f.adapter.setEnabled(true); f.runtime.verifiedSave = false;
  assert.equal((await f.adapter.observeVerified(observation('final'))).status, 'unknown'); assert.equal(f.calls(), 0);
});
test('trusted fixture live→final delivers through existing agent and motion; duplicate is silent', async t => {
  const f = await setup(t); await f.adapter.setEnabled(true); await f.adapter.observeVerified(observation('live'));
  const result = await f.adapter.observeVerified(observation('final')); assert.equal(result.status, 'delivered'); assert.equal(f.calls(), 1); assert.equal(f.messages.length, 1);
  assert.equal(f.messages[0].sessionId, 'conversation'); assert.ok(f.motions.some(event => event.state === 'happy'));
  await f.adapter.observeVerified(observation('final')); assert.equal(f.messages.length, 1);
});
test('character generation change rejects a late model result and settles old motion', async t => {
  let resolve; const f = await setup(t, () => new Promise(r => { resolve = r; })); await f.adapter.setEnabled(true); await f.adapter.observeVerified(observation('live'));
  const task = f.adapter.observeVerified(observation('final'));
  while (!resolve) await new Promise(r => setImmediate(r));
  f.runtime.epoch++; f.runtime.characterId = 'example.other'; f.runtime.changed(); resolve({ text: 'Must not appear', metadata: {} });
  assert.equal((await task).status, 'cancelled'); assert.equal(f.messages.length, 0); assert.equal(f.motions.at(-1).state, 'idle');
});
