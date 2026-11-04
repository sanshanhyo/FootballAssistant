'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { ResultEventGate, FileResultJournal } = require('../src/pet-events.cjs');
const { PetReactions } = require('../src/pet-reactions.cjs');
const config = { enabled: true, muted: false, proactivity: 80, characterId: 'fixture', sessionGeneration: 1 };
const live = { verified: true, saveId: 'save', matchId: 'match', playerTeamId: 'home', homeTeamId: 'home', awayTeamId: 'away', phase: 'live', homeScore: 2, awayScore: 1, observedAt: 100000 };
const final = { ...live, phase: 'final', observedAt: 101000, finishedAt: 101000 };
async function fixture(t, options = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'pet-events-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'journal.json');
  const journal = new FileResultJournal(file);
  const gate = new ResultEventGate({ journal, now: () => 101000, ...options });
  return { gate, journal, file };
}
test('win/loss/draw require live to trusted final, map player side, and never generate advice', async t => {
  for (const [playerTeamId, awayScore, result, expression] of [['home', 1, 'win', 'happy'], ['away', 1, 'loss', 'sad'], ['home', 2, 'draw', 'thinking']]) {
    const { gate } = await fixture(t);
    assert.equal((await gate.observe({ ...live, playerTeamId, awayScore }, config)).status, 'observing');
    const got = await gate.observe({ ...final, playerTeamId, awayScore }, config);
    assert.equal(got.status, 'ready'); assert.equal(got.event.result, result); assert.equal(got.event.expression, expression);
    assert.equal(got.event.text, undefined); assert.equal(got.event.characterId, 'fixture');
  }
});
test('score changes remain live and never trigger results', async t => {
  const { gate } = await fixture(t); await gate.observe(live, config);
  assert.equal((await gate.observe({ ...live, homeScore: 3, observedAt: 101000 }, config)).status, 'observing');
});
test('missing identity, untrusted state, invalid score/time and stale evidence fail closed', async t => {
  for (const patch of [{ verified: false }, { saveId: null }, { matchId: '' }, { playerTeamId: 'other' }, { homeTeamId: 'away' }, { homeScore: -1 }, { awayScore: 1.5 }, { homeScore: '2' }, { phase: 'unknown' }, { observedAt: 80000 }, { observedAt: 102000 }, { observedAt: NaN }, { finishedAt: null }, { finishedAt: 102000 }, { finishedAt: 80000 }]) {
    const { gate } = await fixture(t); await gate.observe(live, config);
    assert.equal((await gate.observe({ ...final, ...patch }, config)).status, 'unknown', JSON.stringify(patch));
  }
});
test('first final, reconnect and changed save/team do not emit historical results', async t => {
  for (const setup of ['first', 'reset', 'save', 'team']) {
    const { gate } = await fixture(t);
    if (setup !== 'first') await gate.observe(live, config);
    if (setup === 'reset') gate.reset();
    const input = { ...final, ...(setup === 'save' ? { saveId: 'new' } : {}), ...(setup === 'team' ? { playerTeamId: 'away' } : {}) };
    assert.equal((await gate.observe(input, config)).status, 'baseline');
    await gate.observe({ ...input, phase: 'live' }, config);
    assert.equal((await gate.observe(input, config)).status, 'duplicate');
  }
});
test('mute, disabled, zero/invalid proactivity consume events without replay', async t => {
  for (const patch of [{ muted: true }, { enabled: false }, { proactivity: 0 }, { proactivity: NaN }, { proactivity: 101 }, { characterId: '' }, { sessionGeneration: -1 }]) {
    const { gate } = await fixture(t); await gate.observe(live, config);
    assert.equal((await gate.observe(final, { ...config, ...patch })).status, 'suppressed');
    await gate.observe(live, config);
    assert.equal((await gate.observe(final, config)).status, 'duplicate');
  }
});
test('persistent duplicate and cooldown survive gate/journal recreation', async t => {
  const { gate, file } = await fixture(t); await gate.observe(live, config);
  assert.equal((await gate.observe(final, config)).status, 'ready');
  const next = new ResultEventGate({ journal: new FileResultJournal(file), now: () => 101000 });
  await next.observe(live, config); assert.equal((await next.observe(final, config)).status, 'duplicate');
  await next.observe({ ...live, matchId: 'next' }, config);
  assert.equal((await next.observe({ ...final, matchId: 'next' }, config)).status, 'cooldown');
});
test('distinct save identity separates dedup, and cooldown can be configured', async t => {
  const { gate } = await fixture(t, { cooldownMs: 0 });
  for (const saveId of ['one', 'two']) {
    await gate.observe({ ...live, saveId }, config);
    assert.equal((await gate.observe({ ...final, saveId }, config)).status, 'ready');
  }
});
test('concurrent duplicate polls deliver at most once and reset invalidates queued polls', async t => {
  const { gate } = await fixture(t); await gate.observe(live, config);
  const results = await Promise.all([gate.observe(final, config), gate.observe(final, config)]);
  assert.deepEqual(results.map(x => x.status), ['ready', 'duplicate']);
  const pending = gate.observe(live, config); gate.reset(); assert.equal((await pending).status, 'cancelled');
});
test('corrupt journal fails closed and out-of-order observation cannot regress live state', async t => {
  const { gate, file } = await fixture(t); await fs.writeFile(file, 'bad json');
  await gate.observe(live, config); assert.equal((await gate.observe(final, config)).status, 'storage_unavailable');
  const second = await fixture(t); await second.gate.observe({ ...live, observedAt: 100500 }, config);
  assert.equal((await second.gate.observe(live, config)).status, 'out_of_order');
});
test('reaction adapter delegates facts, cancels old generation, settles motion', async t => {
  const { gate } = await fixture(t); let finish, signal; const delivered = [], states = [];
  const adapter = new PetReactions({ gate, motion: { reset: () => states.push('idle'), setState: value => states.push(value) },
    suggest(event, options) { assert.equal(event.result, 'win'); signal = options.signal; return new Promise(resolve => { finish = resolve; }); },
    deliver: value => delivered.push(value) });
  adapter.configure(config); await adapter.observe(live);
  const pending = adapter.observe(final);
  while (!finish) await new Promise(resolve => setImmediate(resolve));
  adapter.configure({ ...config, sessionGeneration: 2 }); assert.equal(signal.aborted, true);
  finish('fixture suggestion'); assert.equal((await pending).status, 'cancelled'); assert.equal(delivered.length, 0);
  assert.ok(states.includes('happy')); assert.equal(states.at(-1), 'idle'); adapter.dispose();
});
test('reaction adapter delivers the existing agent result without inventing a fallback', async t => {
  const { gate } = await fixture(t); const delivered = [];
  const adapter = new PetReactions({ gate, suggest: async () => ({ text: 'fixture-only reply' }), deliver: value => delivered.push(value) });
  adapter.configure(config); await adapter.observe(live); assert.equal((await adapter.observe(final)).status, 'delivered');
  assert.equal(delivered[0].suggestion.text, 'fixture-only reply'); adapter.dispose();
});

test('a fresh final cannot revive a long-expired live baseline', async t => {
  let now = 100000;
  const { gate } = await fixture(t, { now: () => now });
  await gate.observe(live, config); now = 200000;
  assert.equal((await gate.observe({ ...final, observedAt: now, finishedAt: now }, config)).status, 'baseline');
});
