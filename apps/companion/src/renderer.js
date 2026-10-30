'use strict';
const $ = id => document.getElementById(id);
const api = window.companion;
let conversationId = localStorage.getItem('football-assistant-conversation') || undefined;
let lastReply = '';
let sending = false;
let pointer = null;
let dragged = false;
let draggingReady = Promise.resolve();
let dragMovePending = false;
let monitorBusy = false;
const savedMonitorCursor = localStorage.getItem('football-assistant-monitor-cursor');
let monitorCursor = savedMonitorCursor !== null && Number.isSafeInteger(Number(savedMonitorCursor)) && Number(savedMonitorCursor) >= 0 ? Number(savedMonitorCursor) : null;
const changeLabels = {
  source_connected:'运行时数据流已连接', source_stale:'运行时心跳延迟', source_disconnected:'运行时数据流已断开',
  snapshot_received:'收到数据快照', ui_text_changed:'页面原文发生变化', raw_fields_changed:'原始字段发生变化',
  capabilities_changed:'读取能力状态变化', interface_catalog_registered:'接口结构清单已登记',
};

function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; updateRects(); }
function addMessage(kind, message) {
  const element = document.createElement('p'); element.className = `message ${kind}`; element.textContent = message;
  $('messages').append(element); $('messages').scrollTop = $('messages').scrollHeight;
}
function updateRects() {
  const rects = [$('pet'), !$('panel').hidden ? $('panel') : null].filter(Boolean).map(element => {
    const r = element.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height };
  });
  api.inputRects(rects);
}
function sourceLabel(source) {
  if (!source || source.availability === 'not_connected') return '尚未接入游戏数据 · 真实数据接通后才提供球队事实';
  if (source.synthetic || source.availability === 'synthetic') return '当前为合成测试数据 · 不能用于真实球队判断';
  if (source.availability === 'unavailable') return '当前数据不可用 · 需要检查游戏或存档适配器';
  const name = source.source === 'save' ? (source.adapter_id?.includes('experimental') ? '实验性存档快照' : '存档快照') : source.source === 'runtime' ? '运行时观测' : '未知来源';
  const time = source.last_captured_at ? new Date(source.last_captured_at).toLocaleString('zh-CN') : '采集时间未知';
  return `${name}${source.availability === 'stale' ? ' · 可能已过期' : ''} · ${source.facts_count || 0} 项字段 · ${time}`;
}
function showChange(event) {
  if (!event) return;
  const label = changeLabels[event.kind] || '数据状态更新';
  const time = event.created_at ? new Date(event.created_at).toLocaleTimeString('zh-CN') : '';
  $('monitor-change').textContent = `最新${event.synthetic ? '模拟' : ''}变化：${label} ${time}`;
  $('monitor-change').title = '这是底层数据变化，不自动解释为比赛、转会或伤病事件。';
}
async function refreshMonitoring() {
  if (monitorBusy) return;
  monitorBusy = true;
  try {
    const result = await api.monitoring();
    if (!result.ok) { $('monitor-state').textContent = '持续监听服务尚未接通'; return; }
    const value = result.value;
    const streams = Array.isArray(value.streams) ? value.streams : [];
    const runtime = streams.filter(stream => stream.source === 'runtime' && !stream.synthetic);
    const connected = runtime.filter(stream => stream.connection_state === 'connected').length;
    const stale = runtime.filter(stream => stream.connection_state === 'stale').length;
    const latestRuntime = runtime.filter(stream => stream.last_captured_at).sort((a, b) => Date.parse(b.last_captured_at) - Date.parse(a.last_captured_at))[0];
    const lastUpdate = latestRuntime ? new Date(latestRuntime.last_captured_at).toLocaleString('zh-CN') : '暂无';
    $('monitor-state').textContent = `运行时数据流：${connected ? '已连接' : stale ? '连接延迟' : '未连接'} · 最近更新 ${lastUpdate}`;
    $('monitor-state').title = '每2秒只读取本机监听状态；原生包头接收不代表字段值已解码。';
    const catalogs = value.coverage?.catalogs || [];
    const count = catalogs.reduce((sum, item) => sum + (Number(item.registered_count) || 0), 0);
    const readable = catalogs.reduce((sum, item) => sum + (Number(item.runtime_verified_coverage?.verified_readable) || 0), 0);
    $('monitor-coverage').textContent = `最近显式探测的已验证数据：${readable ? '可用' : '暂无可用数据'}（不代表当前会话）`;
    $('monitor-coverage').title = '接口结构登记不代表数据可读；已验证可读状态仅反映最近显式探测，不代表当前会话或持续采集覆盖。';
    const managed = catalogs.filter(item => item.inventory_kind !== 'native_exports').reduce((sum, item) => sum + (Number(item.registered_count) || 0), 0);
    const native = catalogs.filter(item => item.inventory_kind === 'native_exports').reduce((sum, item) => sum + (Number(item.registered_count) || 0), 0);
    const complete = catalogs.filter(item => item.inventory_complete === true || item.complete === true).length;
    $('monitor-catalogs').textContent = `托管接口结构 ${managed} 项 · 原生接口结构 ${native} 项 · 合计 ${count} 项`;
    $('monitor-probes').textContent = `最近显式探测可读 ${readable} 项（范围：最近显式探测）`;
    $('monitor-integrity').textContent = `接口目录完整 ${complete}/${catalogs.length}`;
    if (value.source_status) $('source').textContent = sourceLabel(value.source_status);
    if (monitorCursor === null) {
      monitorCursor = Number.isSafeInteger(value.latest_event_cursor) ? value.latest_event_cursor : 0;
      showChange(value.recent_changes?.at(-1));
    } else {
      const changes = await api.events(monitorCursor);
      if (changes.ok) {
        if (changes.value.cursor_reset_required) monitorCursor = 0;
        else {
          showChange(changes.value.events?.at(-1));
          if (Number.isSafeInteger(changes.value.next_cursor)) monitorCursor = changes.value.next_cursor;
        }
      }
    }
    localStorage.setItem('football-assistant-monitor-cursor', String(monitorCursor));
  } catch { $('monitor-state').textContent = '持续监听状态暂不可用'; }
  finally { monitorBusy = false; updateRects(); }
}
async function refresh() {
  const result = await api.status();
  if (!result.ok) {
    $('connection').textContent = '服务未连接'; $('dot').classList.remove('online'); $('source').textContent = result.error;
    return;
  }
  const value = result.value;
  $('dot').classList.add('online');
  $('connection').textContent = value.modelConfigured ? (value.modelStatus === 'error' ? '服务已连接 · 模型请求失败' : '服务已连接 · 可以聊天') : '服务已连接 · 模型待配置';
  $('source').textContent = sourceLabel(value.source_status);
}
async function speak(text) {
  const result = await api.speak(text);
  if (!result.ok) { $('speech-status').textContent = '朗读失败'; error(result.error); }
}
async function send(event) {
  event?.preventDefault();
  const message = $('message').value.trim();
  if (!message || sending) return;
  sending = true; $('send').disabled = true; $('pet').classList.add('thinking'); error('');
  addMessage('user', message); $('message').value = '';
  try {
    const result = await api.chat({ message, ...(conversationId ? { conversation_id: conversationId } : {}) });
    if (!result.ok) throw new Error(result.error);
    const value = result.value;
    if (typeof value.reply !== 'string' || !value.reply.trim() || typeof value.conversation_id !== 'string') throw new Error('服务回复格式无效。');
    conversationId = value.conversation_id; localStorage.setItem('football-assistant-conversation', conversationId);
    lastReply = value.reply; addMessage('assistant', lastReply); $('read-last').disabled = false;
    $('source').textContent = sourceLabel(value.source_status);
    if ($('auto-speak').checked) await speak(lastReply);
  } catch (failure) { error(failure.message); }
  finally { sending = false; $('send').disabled = false; $('pet').classList.remove('thinking'); refresh(); }
}
$('chat-form').addEventListener('submit', send);
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) send(event); });
$('reconnect').addEventListener('click', refresh);
$('collapse').addEventListener('click', () => { $('panel').hidden = true; updateRects(); });
$('read-last').addEventListener('click', () => speak(lastReply));
$('stop-speech').addEventListener('click', () => api.stopSpeech());
$('quit').addEventListener('click', () => api.quit());
$('choose-runtime').addEventListener('click', async () => {
  const result = await api.chooseRuntime();
  if (!result.ok) error(result.error); else { error(''); refresh(); }
});
api.onSpeech(state => {
  $('speech-status').textContent = ({speaking:'朗读中',finished:'朗读完成',stopped:''})[state.state] || '朗读失败';
  if (state.state === 'error') error(state.message);
});
$('pet').addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  pointer = { x: event.screenX, y: event.screenY, id: event.pointerId };
  dragged = false; $('pet').setPointerCapture(event.pointerId);
  draggingReady = api.dragStart();
});
$('pet').addEventListener('pointermove', event => {
  if (!pointer) return;
  if (Math.hypot(event.screenX - pointer.x, event.screenY - pointer.y) > 5) dragged = true;
  if (!dragged || dragMovePending) return;
  dragMovePending = true;
  requestAnimationFrame(async () => { await draggingReady; if (pointer) await api.dragMove(); dragMovePending = false; });
});
async function endDrag(event) {
  if (!pointer) return;
  const toggle = !dragged; pointer = null; await draggingReady; await api.dragEnd();
  if (event.type === 'pointerup' && toggle) { $('panel').hidden = !$('panel').hidden; updateRects(); if (!$('panel').hidden) $('message').focus(); }
}
$('pet').addEventListener('pointerup', endDrag);
$('pet').addEventListener('pointercancel', endDrag);
$('pet').addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { $('panel').hidden = !$('panel').hidden; updateRects(); } });
new ResizeObserver(updateRects).observe(document.body);
window.addEventListener('resize', updateRects);
window.addEventListener('DOMContentLoaded', updateRects);
updateRects(); refresh(); refreshMonitoring(); setInterval(refresh, 8_000); setInterval(refreshMonitoring, 2_000);
