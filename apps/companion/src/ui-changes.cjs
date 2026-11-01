'use strict';

// Pure, local-only display-change detector. No timers, requests, provider or game actions.
// Scope hashes identify a capture layout, never a verified page/player/team identity.
const TEXT = Object.freeze({
  next_match: '这页的下一场比赛信息变了。如果你说的是这场，要一起想想怎么安排吗？我还没确认这是你执教的球队。',
  schedule: '赛程这页和刚才不一样了。我还拿不准是换了页面，还是赛程真有调整。要一起看看接下来的安排吗？',
  tactics: '战术这页和刚才不一样了。先核对一下阵型、风格和心态？光凭这页，我还拿不准场上会怎么踢。',
  current_page_attributes: '这页显示的属性变了。不过我还没弄清是谁的，不能当成同一个球员的变化。',
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
