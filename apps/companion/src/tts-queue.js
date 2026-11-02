/* Non-blocking synthesis + playback queue. No text storage or network decisions here. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FootballTtsQueue = factory();
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  function createTtsQueue({ synthesize, play, cancel, stopPlayback, maxPending = 20 }) {
    let pending = [], current = null, generation = 0, disposed = false;
    const cancelled = () => Object.assign(new Error('语音操作已取消。'), { code: 'cancelled' });
    function finish(item, value, error) {
      if (item.settled) return;
      item.settled = true;
      if (error) item.reject(error); else item.resolve(value);
    }
    function pump() {
      if (current || !pending.length || disposed) return;
      const item = current = pending.shift();
      const token = generation;
      const valid = () => current === item && generation === token && !item.settled;
      Promise.resolve().then(() => valid() ? synthesize(item.payload) : null).then(async result => {
        if (!valid()) return;
        // play resolves on ended, NOT when playback merely starts.
        await play(result, item.controller.signal);
        if (valid()) finish(item, result);
      }).catch(() => { if (valid()) finish(item, null, Object.assign(new Error('语音服务或播放失败，文字仍可阅读。'), { code: 'speech-failed' })); })
        .finally(() => { if (current === item) { current = null; pump(); } });
    }
    function stop() {
      generation++;
      const item = current; current = null;
      if (item) {
        item.controller.abort(); finish(item, null, cancelled());
        try { Promise.resolve(cancel?.(item.payload.operationId)).catch(() => {}); } catch {}
      }
      for (const queued of pending) finish(queued, null, cancelled());
      pending = [];
      try { stopPlayback?.(); } catch {}
    }
    function enqueue(payload, { interrupt = false } = {}) {
      if (disposed) return Promise.reject(Object.assign(new Error('语音队列已关闭。'), { code: 'disposed' }));
      if (interrupt) stop();
      if (pending.length >= maxPending) return Promise.reject(Object.assign(new Error('语音队列已满。'), { code: 'queue-full' }));
      return new Promise((resolve, reject) => {
        pending.push({ payload: { ...payload }, resolve, reject, controller: new AbortController(), settled: false }); pump();
      });
    }
    return { enqueue, stop, switchContext: stop, dispose() { stop(); disposed = true; } };
  }
  return { createTtsQueue };
});
