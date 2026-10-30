'use strict';

const MOCK_LIMITATIONS = Object.freeze([
  '这是前端模拟数据，没有连接游戏、Reader 或模型服务。',
  '原始 UI 可能包含缓存文本；本示例不确认球员身份、属性或字段含义。',
]);

function metadata(sessionId, extra = {}) {
  return {
    source: 'mock', sourceLabel: '模拟适配器', sessionId,
    sampledAt: new Date().toISOString(), partial: true,
    limitations: [...MOCK_LIMITATIONS], synthetic: true, freshness: 'unknown', ...extra,
  };
}

function abortError() { return Object.assign(new Error('请求已取消。'), { name: 'AbortError' }); }
function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const cancel = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve(); }, ms);
    signal?.addEventListener('abort', cancel, { once: true });
  });
}

class MockReaderClient {
  constructor(options = {}) { this.delay = options.delay ?? 300; }
  capabilities() {
    return ['status', 'snapshot', 'raw-ui', 'events', 'native'].map(id => ({ id, available: true, synthetic: true }));
  }
  async status({ sessionId, signal } = {}) {
    await pause(this.delay, signal);
    return { connection: 'simulated', metadata: metadata(sessionId), capabilities: this.capabilities() };
  }
  async snapshot({ sessionId, signal, kind = 'default' } = {}) {
    await pause(this.delay, signal);
    const meta = metadata(sessionId, kind === 'stale' ? { freshness: 'stale', sampledAt: new Date(Date.now() - 15 * 60_000).toISOString() } : {});
    return {
      metadata: meta,
      cards: [{ id: 'mock-observation', title: '模拟观测 · 信息边界', metadata: meta, fields: [
        { label: '示例 UI 原文', value: '训练概览（模拟文本）', status: 'observed' },
        { label: '当前球员', value: null, status: 'unknown' },
        { label: '球员属性', value: null, status: 'unknown' },
        { label: '原生数据', value: '仅包头诊断示例，未解码足球字段', status: 'observed' },
      ] }],
    };
  }
  async rawUi(options) { return this.snapshot(options); }
  async native(options) { return this.snapshot(options); }
  async events(options) { return this.snapshot(options); }
  // A subscription is owned by the client, never exposed as a model tool call.
  watch(callback, { sessionId, signal, intervalMs = 10_000 } = {}) {
    if (typeof callback !== 'function') throw new Error('监听回调无效。');
    let closed = false;
    const timer = setInterval(() => { if (!closed) callback({ kind: 'mock-observation', metadata: metadata(sessionId) }); }, Math.max(1_000, intervalMs));
    timer.unref?.();
    const stop = () => { closed = true; clearInterval(timer); signal?.removeEventListener('abort', stop); };
    if (signal?.aborted) stop(); else signal?.addEventListener('abort', stop, { once: true });
    return stop;
  }
}

class DisconnectedReaderClient {
  capabilities() {
    return ['status', 'snapshot', 'raw-ui', 'events', 'native', 'player-query'].map(id => ({ id, available: false, synthetic: false, reason: '真实后端尚未接入，能力未知。' }));
  }
  async status() { return { connection: 'unavailable', capabilities: this.capabilities(), synthetic: false, limitations: ['真实后端尚未接入；没有发起网络请求。'] }; }
  async snapshot() { throw new Error('真实后端尚未接入，无法读取游戏信息。'); }
  async rawUi(options) { return this.snapshot(options); }
  async native(options) { return this.snapshot(options); }
  async events(options) { return this.snapshot(options); }
  watch() { throw new Error('真实后端尚未接入，无法订阅。'); }
}

module.exports = { MockReaderClient, DisconnectedReaderClient, metadata, MOCK_LIMITATIONS };

const BUSINESS_CAPABILITIES = Object.freeze(['player_info', 'transfer_analysis', 'tactical_analysis', 'schedule_analysis']);
function businessMetadata(envelope = {}) {
  const source = envelope.source || null;
  const reasons = Array.isArray(envelope.reasons) ? envelope.reasons : [];
  return {
    source: source?.kind || 'unknown', sourceLabel: source ? '业务 Reader · ' + source.kind : '业务来源未知',
    sessionId: source?.session_id ?? null, snapshotId: envelope.snapshot?.snapshot_id ?? null,
    sampledAt: source?.observed_at ?? source?.captured_at ?? null,
    partial: envelope.status !== 'available', limitations: [...reasons], synthetic: source?.synthetic === true,
    freshness: reasons.some(reason => ['capture_not_fresh', 'observation_not_fresh'].includes(reason)) ? 'stale' : !source?.observed_at || reasons.includes('observation_time_unknown') ? 'unknown' : 'current',
    provenance: source, readiness: envelope,
  };
}
function adviceCapability(message, explicit) {
  if (explicit !== undefined) {
    if (!BUSINESS_CAPABILITIES.includes(explicit)) throw new Error('不支持的业务建议能力。');
    return explicit;
  }
  if (!/我的|当前(?:存档|球队|阵容|球员|赛程|战术)|(?:看看|查看|分析)球队|给我引援建议|my (?:team|squad|save)|current save/i.test(message)) return null;
  if (/赛程|轮换|schedule|fixture|congestion/i.test(message)) return 'schedule_analysis';
  if (/转会|引援|预算|transfer|signing/i.test(message)) return 'transfer_analysis';
  if (/战术|阵型|阵容|首发|tactic|lineup|formation/i.test(message)) return 'tactical_analysis';
  if (/球员|属性|存档|player|squad/i.test(message)) return 'player_info';
  return null;
}
class RealReaderClient {
  constructor({ request } = {}) {
    if (typeof request !== 'function') throw new Error('需要受控主进程连接。');
    this.request = request;
  }
  capabilities(envelope = {}) {
    return BUSINESS_CAPABILITIES.map(id => ({ id, available: envelope.production_ready === true && envelope.capabilities?.[id]?.ready === true,
      synthetic: envelope.source?.synthetic === true, reason: (envelope.capabilities?.[id]?.missing_requirements || envelope.reasons || ['业务能力尚未验证']).join('、') }));
  }
  async status({ signal } = {}) {
    const envelope = await this.request('/v1/reader/business/status', undefined, { signal });
    return { connection: 'connected', metadata: businessMetadata(envelope), capabilities: this.capabilities(envelope), readiness: envelope };
  }
  async snapshot({ signal } = {}) {
    const envelope = await this.request('/v1/reader/business/snapshot', undefined, { signal });
    const meta = businessMetadata(envelope);
    // A partial verified snapshot may contain useful facts without satisfying every advice capability.
    const snapshot = envelope.snapshot;
    const fields = [];
    if (snapshot && envelope.production_ready === true && !meta.synthetic && meta.freshness === 'current') {
      const visit = (value, ref) => {
        if (fields.length >= 100) return;
        if (value !== null && typeof value === 'object') for (const [key, child] of Object.entries(value)) visit(child, ref + '/' + key);
        else fields.push({ label: ref, value, status: value === null ? 'unknown' : 'observed' });
      };
      for (const [key, value] of Object.entries(snapshot)) if (!['source', 'schema_version'].includes(key)) visit(value, '/' + key);
    }
    return { metadata: meta, readiness: envelope, cards: fields.length ? [{ id: snapshot.snapshot_id, title: '已读取业务事实', metadata: meta, fields }] : [] };
  }
  async reply({ message, conversationId, capability, signal }) {
    if (capability) {
      const result = await this.request('/v1/agent/business-advice', { message, conversation_id: conversationId, capability }, { signal });
      const meta = businessMetadata(result.readiness);
      meta.snapshotId = result.facts?.[0]?.snapshot_id ?? null;
      meta.limitations.push(...(result.missing_requirements || []));
      const facts = result.status === 'generated' && result.readiness?.production_ready === true && meta.freshness === 'current' && !meta.synthetic ? result.facts || [] : [];
      return { text: result.reply, conversationId: result.conversation_id, metadata: meta,
        cards: facts.length ? [{ id: 'business-facts', title: '已读取事实 · 建议见回复', metadata: meta,
          fields: facts.slice(0, 100).map(fact => ({ label: `${fact.snapshot_id} ${fact.field_ref}`, value: fact.value, status: 'observed' })) }] : [] };
    }
    const result = await this.request('/v1/chat', { message, conversation_id: conversationId }, { signal });
    return { text: result.reply, conversationId: result.conversation_id, metadata: { ...businessMetadata(), source: 'agent', sourceLabel: 'AI 对话 · 非当前存档事实', limitations: ['普通对话不代表已读取当前存档业务数据。'] }, cards: [] };
  }
}
module.exports.RealReaderClient = RealReaderClient;
module.exports.businessMetadata = businessMetadata;
module.exports.adviceCapability = adviceCapability;
