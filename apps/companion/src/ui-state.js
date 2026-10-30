(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CompanionUI = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const EXPRESSIONS = Object.freeze({
    idle: '待机', listening: '聆听', transcribing: '识别中', thinking: '等待回复',
    speaking: '说话', notice: '提醒', happy: '开心', puzzled: '疑惑', error: '异常',
  });

  function createGesture({ holdMs = 460, movePx = 8 } = {}) {
    let active = null;
    return {
      begin({ id, x, y, time }) { active = { id, x, y, time, mode: 'pressed' }; },
      move({ id, x, y }) {
        if (!active || id !== active.id || active.mode === 'holding') return null;
        if (Math.hypot(x - active.x, y - active.y) >= movePx) {
          const first = active.mode !== 'dragging'; active.mode = 'dragging';
          return first ? 'drag-start' : 'drag-move';
        }
        return null;
      },
      hold(time) {
        if (!active || active.mode !== 'pressed' || time - active.time < holdMs) return false;
        active.mode = 'holding'; return true;
      },
      end(id, cancelled = false) {
        if (!active || id !== active.id) return null;
        const mode = active.mode; active = null;
        if (cancelled) return mode === 'holding' ? 'voice-cancel' : mode === 'dragging' ? 'drag-end' : 'cancel';
        return mode === 'holding' ? 'voice-stop' : mode === 'dragging' ? 'drag-end' : 'click';
      },
      get mode() { return active?.mode || 'idle'; },
      get holdMs() { return holdMs; },
    };
  }

  function belongsToSession(item, state) {
    return Boolean(item && state && item.sessionId === state.sessionId && item.epoch === state.epoch);
  }

  function createFence() {
    let generation = 0;
    return {
      capture() { return generation; },
      invalidate() { generation += 1; return generation; },
      accepts(token) { return token === generation; },
    };
  }

  function valueLabel(field) {
    if (!field || field.value === null || field.value === undefined || field.status === 'unknown') return '未知';
    if (typeof field.value === 'string' && !field.value.trim()) return '未知';
    if (typeof field.value === 'boolean') return field.value ? '是' : '否';
    if (typeof field.value === 'number') return Number.isFinite(field.value) ? String(field.value) : '未知';
    if (typeof field.value === 'string') return field.value;
    return '未知';
  }

  function observationLabels(metadata = {}) {
    metadata = metadata && typeof metadata === 'object' ? metadata : {};
    const labels = [];
    labels.push(metadata.synthetic === true ? '模拟数据' : metadata.synthetic === false ? '真实来源' : '来源待确认');
    if (metadata.freshness === 'stale') labels.push('已过期');
    else if (metadata.freshness !== 'current') labels.push('时效未知');
    if (metadata.partial === true) labels.push('数据不完整');
    else if (metadata.partial !== false) labels.push('完整性未知');
    return labels;
  }

  function timestampLabel(value) {
    if (value === null || value === undefined || value === '') return '采样时间未知';
    const time = new Date(value);
    return Number.isNaN(time.getTime()) ? '采样时间未知' : time.toLocaleString('zh-CN', { hour12: false });
  }

  return { EXPRESSIONS, createGesture, belongsToSession, createFence, valueLabel, observationLabels, timestampLabel };
});
