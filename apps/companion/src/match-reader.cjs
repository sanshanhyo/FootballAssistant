'use strict';

// This is an experimental local file transport, not an authenticated proof of
// the native producer or a replacement for business readiness.
function matchView(envelope, now = Date.now()) {
  const value = envelope?.snapshot;
  const captured = Date.parse(value?.captured_at);
  const age = now - captured;
  const home = value?.home_metadata?.Name;
  const away = value?.away_metadata?.Name;
  const h = value?.home?.Goals;
  const a = value?.away?.Goals;
  if (envelope?.status !== 'experimental' || envelope?.reason !== 'game_facts_not_verified' || envelope?.producerVerified !== true ||
      value?.schema_version !== 'fa-match-snapshot/0.1' || value?.producer?.id !== 'footballassistant.match-reader' ||
      value?.producer?.version !== '0.1.0' || value?.producer?.protocol !== 'fa-match-snapshot/0.1' ||
      !/^[a-f0-9]{64}$/.test(value?.process?.sessionId || '') || !/^[a-f0-9]{32}$/.test(value?.instanceId || '') ||
      value?.status !== 'live' || value?.synthetic !== false || value?.source !== 'native_match_hook' ||
      !/^[a-f0-9]{32}$/.test(value?.match_id || '') || !Number.isFinite(age) || age < -5000 || age > 15000 ||
      typeof home !== 'string' || !home || typeof away !== 'string' || !away ||
      !Number.isSafeInteger(h) || h < 0 || !Number.isSafeInteger(a) || a < 0) return null;
  return { sessionId: value.process.sessionId, instanceId: value.instanceId, id: value.match_id, home: home.slice(0, 128), away: away.slice(0, 128), h, a,
    period: value.period, tick: value.display_tick, capturedAt: value.captured_at };
}

function matchCard(view) {
  const meta = { source: 'native_match_hook', sourceLabel: '比赛内存读取 · 实验', sessionId: view.sessionId, matchId: view.id, instanceId: view.instanceId,
    sampledAt: view.capturedAt, partial: true, synthetic: false, freshness: 'current',
    limitations: ['已核对读取组件协议与当前进程身份；比赛字段仍属实验读取，需与实机画面核对。'] };
  return { id: 'live-match', title: '实时比赛', status: 'available', transport: 'connected', metadata: meta,
    fields: [{ label: '比赛', value: `${view.home} ${view.h} : ${view.a} ${view.away}`, status: 'observed' },
      { label: '比赛阶段', value: String(view.period), status: 'observed' }] };
}

// The reference reader returns zero for failed/invalid memory reads, so zero
// must remain unknown rather than becoming a displayed football attribute.
function displayAttribute(raw) {
  if (!Number.isInteger(raw) || raw <= 0 || raw > 100) return { raw, display: null };
  return { raw, display: Math.min(20, Math.max(1, Math.round(raw / 5))) };
}

class MatchChangeTracker {
  constructor() { this.previous = null; }
  reset() { this.previous = null; }
  observe(view, enabled) {
    if (!enabled || !view) { this.reset(); return null; }
    const old = this.previous; this.previous = view;
    if (!old || old.id !== view.id || old.sessionId !== view.sessionId || old.instanceId !== view.instanceId || old.h === view.h && old.a === view.a) return null;
    return { text: `比分变化：${view.home} ${view.h} : ${view.a} ${view.away}。`,
      metadata: matchCard(view).metadata };
  }
}
module.exports = { matchView, matchCard, displayAttribute, MatchChangeTracker };
