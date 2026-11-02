(function (root) {
  'use strict';
  function bind({ root: container, api, onError = () => {} }) {
    let state = null, busy = false, closed = false, generation = 0;
    const make = (tag, text, parent = container) => { const element = document.createElement(tag); if (text) element.textContent = text; parent.append(element); return element; };
    const title = make('h2', '游戏读取');
    const status = make('div'); status.setAttribute('role', 'status');
    const game = make('div');
    const consentLabel = make('label'); consentLabel.className = 'switch-row'; make('span', '允许只读读取本机 FM27（不修改游戏）', consentLabel);
    const consent = make('input', '', consentLabel); consent.type = 'checkbox'; consent.setAttribute('aria-label', '允许只读读取本机 FM27');
    const actions = make('div'); actions.className = 'row-actions';
    const select = make('button', '选择游戏', actions), enable = make('button', '启用读取', actions), verify = make('button', '检查连接', actions), refresh = make('button', '重新检测', actions);
    const labels = { not_enabled: '读取尚未启用', payload_unavailable: '读取组件缺失或校验失败', configured: '读取器已配置，等待检查', consent_required: '读取尚未授权', producer_not_configured: '后台未配置读取器', resource_missing: '后台读取组件缺失', producer_busy: '读取正在进行，请稍后重试', reader_busy: '读取正在进行，请稍后重试', producer_unavailable: '读取组件未能返回可信结果', fm_not_running: '请启动 FM27 并加载存档', fm_process_not_unique: '检测到多个 FM 进程，请只保留一个', multiple_processes: '检测到多个 FM 进程，请只保留一个', unsupported_binary: '当前游戏版本不受支持', unsupported_game: '当前游戏版本不受支持', process_access_denied: '无法只读访问游戏进程', no_session: '游戏已运行，尚未识别可读会话', no_data: '读取器已连接，尚无数据', fresh_partial: '已取得新鲜的部分游戏数据', read_failed: '读取失败，请重试', backend_unavailable: '后台未连接', disabled: '读取已停用' };
    function buttons() { consent.disabled = busy || state?.enabled === true; select.disabled = busy; refresh.disabled = busy; enable.disabled = busy || (!state?.enabled && (!consent.checked || !state?.payloadReady || state?.canEnable === false)); verify.disabled = busy || state?.enabled !== true; }
    function render(value) {
      state = value; if (value.supported === false) { container.hidden = true; return; }
      container.hidden = false; consent.checked = value.enabled === true; enable.textContent = value.enabled ? '停用读取' : '启用读取';
      status.textContent = labels[value.state] || value.backend?.reason || value.state || '读取状态未确认';
      if (value.restartRequired) status.textContent += ' · 请重启外部后台后再检查';
      game.textContent = value.gamePath || '';
      if (value.externalLoaders?.length) game.textContent += ` · 发现其他加载器：${value.externalLoaders.join('、')}（未修改）`;
      if (value.error || value.backendError) onError(value.error || value.backendError);
      buttons();
    }
    async function run(action) {
      if (busy) return; busy = true; const token = ++generation; buttons(); onError('');
      try { const result = await action(); if (closed || token !== generation) return; if (!result?.ok) throw Error(result?.error || '读取器操作失败'); if (!result.value?.cancelled) render(result.value); }
      catch (error) { if (!closed && token === generation) { onError(error.message); status.textContent = '操作未完成'; } }
      finally { if (!closed && token === generation) { busy = false; buttons(); } }
    }
    consent.addEventListener('change', buttons);
    select.addEventListener('click', () => run(() => api.selectReaderGame()));
    enable.addEventListener('click', () => run(() => api.enableReader({ enabled: state?.enabled !== true, readOnlyConsent: state?.enabled !== true && consent.checked })));
    verify.addEventListener('click', () => run(() => api.verifyReader()));
    refresh.addEventListener('click', () => run(() => api.inspectReaderOnboarding()));
    const ready = run(() => api.inspectReaderOnboarding());
    return { ready, refresh: () => run(() => api.inspectReaderOnboarding()), dispose() { closed = true; generation++; } };
  }
  if (typeof module === 'object' && module.exports) module.exports = { bind }; else root.FootballReaderOnboarding = { bind };
})(typeof window === 'object' ? window : globalThis);
