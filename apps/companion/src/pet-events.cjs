'use strict';
const { createHash } = require('node:crypto');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const id = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 256;
const time = value => typeof value === 'number' && Number.isFinite(value);
const score = value => Number.isSafeInteger(value) && value >= 0 && value <= 999;
const keyOf = values => createHash('sha256').update(JSON.stringify(values)).digest('hex');

// Adapter-only input. Never infer verified=true from reachability, score changes,
// period numbers, UI text or the current experimental match transport.
function validateObservation(value, now, maxAgeMs) {
  if (!value || value.verified !== true || !id(value.saveId) || !id(value.matchId) ||
      !id(value.playerTeamId) || !id(value.homeTeamId) || !id(value.awayTeamId) ||
      value.homeTeamId === value.awayTeamId ||
      ![value.homeTeamId, value.awayTeamId].includes(value.playerTeamId) ||
      !['live', 'final'].includes(value.phase) || !score(value.homeScore) || !score(value.awayScore) ||
      !time(value.observedAt) || value.observedAt > now || now - value.observedAt > maxAgeMs) return null;
  if (value.phase === 'final' && (!time(value.finishedAt) || value.finishedAt > value.observedAt ||
      now - value.finishedAt > maxAgeMs)) return null;
  const own = value.playerTeamId === value.homeTeamId ? value.homeScore : value.awayScore;
  const opponent = value.playerTeamId === value.homeTeamId ? value.awayScore : value.homeScore;
  return { ...value, result: own > opponent ? 'win' : own < opponent ? 'loss' : 'draw' };
}

// Dedicated journal: no chat history dependency. A failed write suppresses delivery.
// Single application process; existing state-file CAS rejects competing writers.
class FileResultJournal {
  constructor(file) { this.file = file; }
  async claim(key, now, cooldownMs, eligible) {
    const stored = await readStateFile(this.file);
    const state = stored.bytes ? JSON.parse(stored.bytes.toString('utf8')) : { version: 1, seen: [], lastDeliveredAt: null };
    if (state.version !== 1 || !Array.isArray(state.seen) || state.seen.some(k => !/^[a-f0-9]{64}$/.test(k)) ||
        !(state.lastDeliveredAt === null || time(state.lastDeliveredAt))) throw Error('Invalid result journal');
    if (state.seen.includes(key)) return 'duplicate';
    if (state.seen.length >= 10000) throw Error('Result journal full; preserve deduplication history');
    const cooling = state.lastDeliveredAt !== null && now - state.lastDeliveredAt < cooldownMs;
    state.seen.push(key);
    const status = !eligible ? 'suppressed' : cooling ? 'cooldown' : 'ready';
    if (status === 'ready') state.lastDeliveredAt = now;
    await writeStateFile(this.file, JSON.stringify(state), stored.revision);
    return status;
  }
}

class ResultEventGate {
  constructor({ journal, now = Date.now, maxAgeMs = 15000, cooldownMs = 60000 }) {
    if (!journal || typeof journal.claim !== 'function' || !time(maxAgeMs) || maxAgeMs <= 0 ||
        !time(cooldownMs) || cooldownMs < 0) throw Error('Invalid result gate configuration');
    this.journal = journal; this.now = now; this.maxAgeMs = maxAgeMs; this.cooldownMs = cooldownMs;
    this.queue = Promise.resolve(); this.reset();
  }
  reset() { this.generation = (this.generation || 0) + 1; this.previous = null; }
  observe(value, config = {}) {
    const generation = this.generation;
    // Snapshot caller-owned objects before entering the asynchronous queue.
    const input = value && { ...value }, options = { ...config };
    const operation = this.queue.catch(() => {}).then(() => this.evaluate(input, options, generation));
    this.queue = operation; return operation;
  }
  async evaluate(input, config, generation) {
    if (generation !== this.generation) return { status: 'cancelled' };
    const now = this.now(), value = validateObservation(input, now, this.maxAgeMs);
    if (!value) { this.previous = null; return { status: 'unknown' }; }
    const identity = keyOf([value.saveId, value.matchId, value.playerTeamId, value.homeTeamId, value.awayTeamId]);
    const old = this.previous;
    if (old && old.identity === identity && value.observedAt < old.observedAt) return { status: 'out_of_order' };
    this.previous = { identity, phase: value.phase, observedAt: value.observedAt };
    if (value.phase !== 'final') return { status: 'observing' };
    const transition = old?.identity === identity && old.phase === 'live' && now - old.observedAt <= this.maxAgeMs && value.finishedAt >= old.observedAt;
    const enabled = config.enabled === true && config.muted !== true &&
      Number.isFinite(config.proactivity) && config.proactivity > 0 && config.proactivity <= 100 &&
      id(config.characterId) && Number.isSafeInteger(config.sessionGeneration) && config.sessionGeneration >= 0;
    const key = keyOf([value.saveId, value.matchId, value.result]);
    let status;
    try { status = await this.journal.claim(key, now, this.cooldownMs, Boolean(transition && enabled)); }
    catch { return { status: 'storage_unavailable' }; }
    if (generation !== this.generation) return { status: 'cancelled' };
    if (status !== 'ready') return { status: !transition && status === 'suppressed' ? 'baseline' : status };
    return { status: 'ready', event: {
      type: 'match_result', key, result: value.result,
      expression: { win: 'happy', loss: 'sad', draw: 'thinking' }[value.result],
      characterId: config.characterId, sessionGeneration: config.sessionGeneration,
      facts: { saveId: value.saveId, matchId: value.matchId, playerTeamId: value.playerTeamId,
        homeTeamId: value.homeTeamId, awayTeamId: value.awayTeamId,
        homeScore: value.homeScore, awayScore: value.awayScore, finishedAt: value.finishedAt },
    } };
  }
}
module.exports = { ResultEventGate, FileResultJournal, validateObservation };
