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
  if (envelope?.status !== 'experimental' || envelope?.reason !== 'native_producer_not_verified' ||
      value?.status !== 'live' || value?.synthetic !== false || value?.source !== 'native_match_hook' ||
      typeof value?.match_id !== 'string' || !value.match_id || !Number.isFinite(age) || age < -5000 || age > 15000 ||
      typeof home !== 'string' || !home || typeof away !== 'string' || !away ||
      !Number.isSafeInteger(h) || h < 0 || !Number.isSafeInteger(a) || a < 0) return null;
  return { id: value.match_id, home: home.slice(0, 128), away: away.slice(0, 128), h, a,
    period: value.period, tick: value.display_tick, capturedAt: value.captured_at };
}

function matchCard(view) {
  const meta = { source: 'native_match_hook', sourceLabel: '比赛内存读取 · 实验', sessionId: view.id,
    sampledAt: view.capturedAt, partial: true, synthetic: false, freshness: 'current',
    limitations: ['当前比分已完成一次实机画面核对；其他字段和传输来源仍需验证。'] };
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
    if (!old || old.id !== view.id || old.h === view.h && old.a === view.a) return null;
    return { text: `比分变化：${view.home} ${view.h} : ${view.a} ${view.away}。`,
      metadata: matchCard(view).metadata };
  }
}
module.exports = { matchView, matchCard, displayAttribute, MatchChangeTracker };
