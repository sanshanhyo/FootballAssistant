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
