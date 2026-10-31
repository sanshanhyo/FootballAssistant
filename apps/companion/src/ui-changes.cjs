'use strict';

// Pure, local-only display-change detector. No timers, requests, provider or game actions.
// Scope hashes identify a capture layout, never a verified page/player/team identity.
const TEXT = Object.freeze({
  schedule: '当前显示的赛程数据已更新。请先核对当前页面；这不表示新增比赛或游戏日期推进。需要建议时，可以输入“看看我的赛程”。',
  tactics: '当前显示的战术数据已更新。可以先核对阵型、风格和心态，再输入“分析我的战术”。这只是 UI 显示变化，不代表已确认的比赛事件。',
  current_page_attributes: '当前显示的属性数据已更新。球员身份未知，不能判断是否为同一球员，也不表示球员能力发生变化。请先核对当前页面。',
});
const LIMITATIONS = Object.freeze([
  '本地、无模型的 UI 显示更新提示；不是比赛、伤病、转会或球员能力事件。',
  '只比较当前采样布局中的已映射显示；页面、球员身份与像素可见性未验证。',
  '页面/布局切换、重新连接和失效后的首次读取只重建基线，不生成游戏事件。',
]);
const HASH = /^[a-f0-9]{64}$/;

function validEnvelope(value, now) {
  if (!value || value.status !== 'ready' || value.source !== 'ui' || value.synthetic !== false ||
      value.partial !== true || value.production_ready !== false || !Object.hasOwn(TEXT, value.kind) ||
      typeof value.session_id !== 'string' || !value.session_id || value.session_id.length > 128 ||
      typeof value.event_id !== 'string' || !value.event_id || value.event_id.length > 128 ||
      typeof value.captured_at !== 'string' || value.captured_at.length > 64 ||
      typeof value.display_sha256 !== 'string' || !HASH.test(value.display_sha256) ||
      typeof value.scope_sha256 !== 'string' || !HASH.test(value.scope_sha256)) return false;
  const captured = Date.parse(value.captured_at);
  return Number.isFinite(captured) && Number.isFinite(now) && captured <= now && now - captured <= 15_000;
}

class UiChangeTracker {
  constructor({ now = Date.now, cooldownMs = 60_000 } = {}) {
    if (typeof now !== 'function' || !Number.isFinite(cooldownMs) || cooldownMs < 0) throw new TypeError('Invalid UI change detector options.');
    this.now = now;
    this.cooldownMs = cooldownMs;
    this.lastNoticeAt = -Infinity;
    this.latestCaptured = -Infinity;
    this.reset();
  }
  reset() {
    this.context = null;
    this.lastEvent = null;
    this.lastCaptured = null;
    this.candidate = null;
    this.stable = null;
    this.seen = [];
  }
  remember(digest) {
    if (!this.seen.includes(digest)) this.seen.push(digest);
    if (this.seen.length > 32) this.seen.shift();
  }
  observe(envelope, { enabled = true } = {}) {
    const now = this.now();
    if (!enabled || !validEnvelope(envelope, now)) { this.reset(); return null; }
    const captured = Date.parse(envelope.captured_at);
    // Also fence delayed responses from a prior session/layout before changing context.
    if (captured <= this.latestCaptured) return null;
    const context = JSON.stringify([envelope.session_id, envelope.kind, envelope.scope_sha256]);
    if (context !== this.context) { this.reset(); this.context = context; }
    if (this.lastCaptured !== null && captured - this.lastCaptured > 15_000) {
      this.reset(); this.context = context; // No comparison across an unobserved/stale gap.
    }
    // A repeated poll is not a second frame. Never compare a late response to newer data.
    if (envelope.event_id === this.lastEvent || (this.lastCaptured !== null && captured <= this.lastCaptured)) return null;
    this.lastEvent = envelope.event_id;
    this.lastCaptured = captured;
    this.latestCaptured = captured;
    const digest = envelope.display_sha256;
    if (this.candidate !== digest) { this.candidate = digest; return null; }
    if (this.stable === digest) return null;
    const firstBaseline = this.stable === null;
    const repeated = this.seen.includes(digest);
    this.stable = digest;
    this.remember(digest);
    // Suppressed changes become the baseline, never a delayed queue of stale notices.
    if (firstBaseline || repeated || now - this.lastNoticeAt < this.cooldownMs) return null;
    this.lastNoticeAt = now;
    return {
      text: TEXT[envelope.kind], cards: [],
      metadata: {
        source: 'ui', sourceLabel: 'Alpha · 本地 UI 显示更新',
        sessionId: envelope.session_id, snapshotId: envelope.event_id, sampledAt: envelope.captured_at,
        partial: true, synthetic: false, freshness: 'current', identity: null,
        individualAdviceAllowed: false, limitations: [...LIMITATIONS],
      },
    };
  }
}

module.exports = { UiChangeTracker };
