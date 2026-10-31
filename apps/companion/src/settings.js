'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const api = window.companion;
  const UI = window.CompanionUI;
  const PAGES = {
    connection: ['连接与数据', '查看连接状态、数据来源和任务进度。'],
    voice: ['语音', '选择转写和播报服务，查看服务是否就绪。'],
    companion: ['陪伴与表情', '调整提醒偏好与桌宠的表情表现。'],
    records: ['历史与记忆', '聊天记录与明确保存的记忆分别管理。'],
  };
  const TOOL_STATES = { running: '进行中', completed: '完成', cancelled: '已取消', error: '失败' };
  let state = null;
  let activePage = 'connection';
  let speechInfo = null;
  let tools = new Map();
  let history = [];
  let historyLimit = 40;
  let historyLoad = 0;
  let memoryLoad = 0;
  let recordsTimer;
  let noticeTimer;
  let unsubscribe;
  let stopped = false;
  let proactivityEditing = false;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }
  function unwrap(result) {
    if (!result?.ok) throw new Error(result?.error || '操作未完成，请重试。');
    return result.value;
  }
  function showError(message) {
    $('error').textContent = message || '';
    $('error').hidden = !message;
  }
  function notice(message) {
    clearTimeout(noticeTimer);
    $('notice').textContent = message || '';
    $('notice').hidden = !message;
    if (message) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 4500);
  }
  async function perform(action, { success, button } = {}) {
    showError('');
    if (button) button.disabled = true;
    try {
      const value = unwrap(await action());
      if (success) notice(success);
      return value;
    } catch (error) {
      showError(error.message);
      return undefined;
    } finally {
      if (button) button.disabled = false;
      if (state) renderModeAvailability();
    }
  }
  function sourceLabel(metadata) {
    if (typeof metadata.sourceLabel === 'string') return metadata.sourceLabel;
    if (typeof metadata.source === 'string') return metadata.source;
    try { return metadata.source ? JSON.stringify(metadata.source) : '未知'; }
    catch { return '来源结构不可用'; }
  }
  function metadataView(value) {
    const metadata = value && typeof value === 'object' ? value : {};
    const details = node('details', 'metadata');
    details.append(node('summary', '', '查看来源与数据限制'));
    details.append(node('p', '', `来源：${sourceLabel(metadata)}`));
    details.append(node('p', '', `会话：${metadata.sessionId || '未知'}`));
    details.append(node('p', '', `采样时间：${UI.timestampLabel(metadata.sampledAt)}`));
    details.append(node('p', '', `partial：${metadata.partial === true ? '是' : metadata.partial === false ? '否' : '未知'} · synthetic：${metadata.synthetic === true ? '是（模拟）' : metadata.synthetic === false ? '否' : '未知'}`));
    const limitations = Array.isArray(metadata.limitations) ? metadata.limitations : metadata.limitations ? [metadata.limitations] : [];
    if (limitations.length) {
      const list = node('ul');
      limitations.forEach(item => list.append(node('li', '', item)));
      details.append(list);
    } else details.append(node('p', '', '数据限制未提供，不能据此认定信息完整或已经验证。'));
    return details;
  }
  function metadataTags(metadata) {
    const tags = node('div', 'observation-tags');
    UI.observationLabels(metadata).forEach(label => {
      const kind = label === '模拟数据' ? 'synthetic' : label.includes('过期') ? 'stale' : label.includes('完整') ? 'partial' : label.includes('未知') || label.includes('确认') ? 'unknown' : '';
      tags.append(node('span', `badge ${kind}`, label));
    });
    return tags;
  }
  function cardView(card, inherited = {}) {
    const element = node('section', 'info-card');
    element.append(node('h3', '', card.title || '信息卡'));
    const fields = node('dl', 'card-fields');
    for (const field of Array.isArray(card.fields) ? card.fields : []) {
      const value = UI.valueLabel(field);
      fields.append(node('dt', '', field?.label || '未知字段'), node('dd', value === '未知' ? 'unknown' : '', value));
    }
    const metadata = { ...inherited, ...card.metadata };
    element.append(fields, metadataTags(metadata), metadataView(metadata));
    if (card.action || card.type === 'action-proposal') {
      const button = node('button', 'action-disabled', '执行暂不可用');
      button.disabled = true; element.append(button);
    }
    return element;
  }
  function renderModeAvailability() {
    $('refresh-reader').disabled = state.mode !== 'real';
    $('simulate-event').disabled = state.mode !== 'mock';
    $('simulate-scenario').disabled = state.mode !== 'mock';
    $('scenario').disabled = state.mode !== 'mock';
  }
  function renderCharacter() {
    const character = state?.character;
    $('character-name').textContent = character ? `${character.displayName} / ${character.englishName}` : '角色资料待读取';
    $('character-id').textContent = character ? `角色 ID：${character.characterId}` : '';
    $('character-visual').textContent = character ? `${character.visual?.label || '视觉待确认'} · 当前使用默认形象。` : '';
    $('expression').disabled = character?.visual?.kind === 'builtin-image';
    $('character-fallback').hidden = !character?.fallback;
    const requestedLabel = typeof character?.requestedCharacterId === 'string' ? character.requestedCharacterId.slice(0, 120) : '';
    $('character-fallback').textContent = character?.fallback ? `配置中的角色 ${requestedLabel}${character.requestedCharacterId.length > 120 ? '…' : ''} 当前不可用，暂时显示内置角色；原角色 ID 已完整保留。` : '';
  }
  function renderConnection() {
    const synthetic = state.synthetic === true;
    const modeLabel = synthetic ? '模拟模式' : '真实模式';
    for (const id of ['sidebar-mode', 'mode-badge']) {
      $(id).textContent = modeLabel;
      $(id).classList.toggle('synthetic', synthetic);
    }
    $('header-status').textContent = state.connection?.state === 'disconnected' ? '模拟连接已中断' : synthetic ? '模拟演示中' : state.connection?.label || '连接未知';
    $('header-status').className = `status-indicator ${synthetic ? 'synthetic' : ''} ${state.connection?.state || 'unavailable'}`;
    $('connection-label').textContent = state.connection?.label || '连接状态未知';
    $('connection-reason').textContent = state.connection?.reason || (synthetic ? '所有游戏信息和回复均为模拟，未连接游戏或模型。' : '本机服务连接状态见上方；不会自动切换到模拟。');
    $('mode').value = state.mode;
    $('session-id').textContent = state.sessionId;
    $('backend-id').textContent = synthetic ? '模拟适配器' : (!state.connection?.backendId || ['unconfigured', 'local-service'].includes(state.connection.backendId)) ? '本机服务（runtime 连接；非模型配置状态）' : state.connection.backendId;
    const capabilities = Array.isArray(state.capabilities) ? state.capabilities : [];
    $('reader-capabilities').textContent = capabilities.length ? capabilities.map(item => `${item.id || '未知能力'}${item.available === true ? item.synthetic ? '（模拟）' : '（可用）' : '（待确认）'}`).join(' · ') : '能力尚未确认';
    const limitations = $('connection-limitations'); limitations.replaceChildren();
    (Array.isArray(state.limitations) ? state.limitations : []).forEach(value => limitations.append(node('li', '', value)));
    $('session-short').textContent = `会话 ${state.sessionId.slice(0, 8)} · ${synthetic ? '模拟' : '真实'}`;
    $('session-short').title = state.sessionId;
    $('refresh-reader').disabled = synthetic;
    const previews = $('reader-previews'); previews.replaceChildren();
    if (!state.readerPreviews?.length) previews.append(node('p', 'empty', synthetic ? '模拟模式不读取真实页面。' : '未知 · 正在等待读取，或当前 Reader 不可用。'));
    const previewSpecs = [{ id: 'schedule', title: '实验性 UI 赛程', profile: 'schedule' }, { id: 'tactics', title: '实验性 UI 战术', profile: 'tactics' }, { id: 'current-page-attributes', title: '当前页面属性 · 身份未知', profile: 'current_page_attributes' }];
    for (const spec of previewSpecs) {
      const card = (state.readerPreviews || []).find(item => item.id === spec.id) || { ...spec, status: 'unknown', fields: [], metadata: { partial: true, freshness: 'unknown' } };
      const element = cardView(card);
      element.prepend(node('span', `badge ${card.status === 'stale' ? 'stale' : card.status === 'available' ? '' : 'unknown'}`, ({ available: '可用 · 部分 UI', stale: '过期 · 已隐藏旧值', unknown: '未知 / 当前页面不支持' })[card.status] || '未知'));
      if (card.statusReason === 'connection_failed') {
        element.firstChild.textContent = '未知 · 服务连接失败';
        element.append(node('p', 'muted', card.error || '请检查本机服务是否仍在运行。'));
      } else if (card.statusReason === 'endpoint_unavailable') {
        element.firstChild.textContent = '未知 · 服务版本不支持此预览接口';
        element.append(node('p', 'muted', card.error || '请更新本机服务。'));
      }
      const request = state.captureRequest;
      const controls = [{ profile: spec.profile, label: '读取当前页' }];
      if (spec.id === 'schedule') {
        controls.push({ profile: 'next_match', label: '读取下一场卡片' });
        element.append(node('p', 'muted', '读取当前页：先打开赛程安排。读取下一场卡片：先打开俱乐部概况；仅日期、对手、赛事三项，不是完整赛程，也不确认你执教的球队。'));
      }
      for (const control of controls) {
        const read = node('button', 'secondary-button', control.label);
        read.dataset.captureProfile = control.profile;
        read.disabled = synthetic || request?.status === 'requesting' || (request?.profile === control.profile && ['pending', 'applied'].includes(request.status));
        read.addEventListener('click', () => perform(() => api.setCaptureProfile(control.profile)));
        element.append(read);
      }
      if (controls.some(control => request?.profile === control.profile)) {
        const label = { requesting: '正在提交读取请求…', pending: '请求已提交，等待采样范围应用…', applied: '采样范围已应用，等待当前页的新鲜内容…', ready: '已确认：采样范围已应用，当前页内容新鲜。', failed: '读取请求失败；未确认生效。', unavailable: '读取暂不可用；未确认生效。', not_configured: '本机 Reader 控制未配置；未确认生效。' }[request.status] || '读取状态未知';
        const target = request.profile === 'next_match' ? '下一场卡片 · ' : '';
        const feedback = node('p', 'muted', target + (request.reason ? `${label} ${request.reason}` : label));
        feedback.setAttribute('role', 'status'); element.append(feedback);
      }
      previews.append(element);
    }
    renderModeAvailability();
  }
  function renderTasks() {
    const container = $('tasks'); container.replaceChildren();
    const items = [...tools.values()].filter(item => UI.belongsToSession(item, state)).slice(-12);
    const running = items.filter(item => item.tool?.status === 'running').length;
    $('task-count').textContent = running ? `${running} 项进行中` : items.length ? `${items.length} 项最近任务` : '暂无任务';
    if (!items.length) container.append(node('p', 'empty', '桌宠处理消息时，工具进度会显示在这里。'));
    for (const item of items) {
      const tool = item.tool || {};
      const element = node('div', 'task-item');
      const row = node('div', 'task-row');
      row.append(node('span', 'task-name', tool.label || tool.name || '读取信息'), node('span', `task-state ${tool.status || ''}`, TOOL_STATES[tool.status] || '等待'));
      if (tool.status === 'running') {
        const button = node('button', 'text-button', '取消');
        button.addEventListener('click', () => perform(() => api.cancelRequest(item.requestId), { button }));
        row.append(button);
      }
      element.append(row, metadataTags(tool.metadata), metadataView(tool.metadata));
      container.append(element);
    }
  }
  function renderObservations() {
    const container = $('observations'); container.replaceChildren();
    const observed = (Array.isArray(state.messages) ? state.messages : []).filter(message => message.role !== 'user' && UI.belongsToSession(message, state)).slice(-3).reverse();
    $('observation-count').textContent = observed.length ? `最近 ${observed.length} 条` : '暂无观测';
    if (!observed.length) container.append(node('p', 'empty', '发送消息或演示数据后，可以在这里查看来源和信息卡。'));
    for (const message of observed) {
      const element = node('article', 'observation-item');
      element.append(node('h3', '', message.origin === 'proactive' ? '主动消息' : '桌宠回复'), node('p', 'record-text', message.text || '消息内容不可用'), metadataTags(message.metadata), metadataView(message.metadata));
      for (const card of Array.isArray(message.cards) ? message.cards : []) element.append(cardView(card, message.metadata));
      container.append(element);
    }
  }
  function renderPreferences() {
    if (!proactivityEditing) {
      $('proactivity').value = String(state.proactivity ?? 80);
      $('proactivity-value').textContent = `${state.proactivity ?? 80}%`;
    }
    $('expression').value = state.preferences?.expression || 'auto';
    $('stt-provider').value = state.preferences?.sttProvider || 'openai';
    $('tts-provider').value = state.preferences?.ttsProvider || 'system';
    $('history-enabled').checked = state.historyEnabled === true;
    renderProviderNotes();
  }
  function applyState(next) {
    if (!next || !Number.isSafeInteger(next.epoch) || typeof next.sessionId !== 'string') return;
    if (state && next.epoch < state.epoch) return;
    const switched = state && (next.epoch !== state.epoch || next.sessionId !== state.sessionId);
    state = next;
    tools = new Map((Array.isArray(next.tools) ? next.tools : []).filter(item => UI.belongsToSession(item, state)).map(item => [item.tool.id, item]));
    historyLoad += 1; memoryLoad += 1;
    if (switched) { history = []; historyLimit = 40; renderHistory(); $('speech-state').textContent = '会话已切换，语音已停止'; }
    renderCharacter(); renderConnection(); renderPreferences(); renderTasks(); renderObservations();
    if (next.storageWarning) showError(next.storageWarning);
    if (activePage === 'records') scheduleRecords();
  }
  function providerEntries(kind) {
    return Array.isArray(speechInfo?.[kind]) ? speechInfo[kind] : [];
  }
  function providerName(provider, kind) {
    return provider.label || ({ openai: kind === 'stt' ? '云端转写' : '云端 TTS', azure: 'Azure TTS', edge: 'Edge TTS', system: '系统语音', mock: kind === 'stt' ? '模拟转写（非实际识别）' : '模拟播报（无实际音频）' })[provider.id] || provider.id;
  }
  function renderProviderNotes() {
    for (const kind of ['stt', 'tts']) {
      const provider = providerEntries(kind).find(item => item.id === $(`${kind}-provider`).value);
      const synthetic = provider?.synthetic === true || $(`${kind}-provider`).value === 'mock';
      $(`${kind}-note`).textContent = synthetic ? (kind === 'stt' ? '模拟转写不会识别实际录音。结果明确标记为模拟，只放入草稿。' : '模拟播报只演示状态，不会播放实际音频。') : !speechInfo ? '语音服务状态尚未确认。' : provider?.available !== true ? (provider?.reason || '所选服务尚未就绪；不会自动改用其他服务。') : kind === 'stt' ? '服务已就绪。按住桌宠录音，松开转写，结果由你确认发送。' : '服务已就绪。通过桌宠回复气泡手动播报，可随时停止。';
    }
  }
  async function refreshSpeech() {
    try {
      speechInfo = unwrap(await api.speechCapabilities());
      if (stopped) return;
      for (const kind of ['stt', 'tts']) {
        const select = $(`${kind}-provider`);
        const selected = state?.preferences?.[`${kind}Provider`] || select.value;
        const entries = providerEntries(kind);
        const container = $(`${kind}-capabilities`); container.replaceChildren();
        if (entries.length) {
          select.replaceChildren();
          for (const provider of entries) {
            const option = node('option', '', `${providerName(provider, kind)}${provider.available !== true ? ' · 未就绪' : ''}`);
            option.value = provider.id; select.append(option);
            const row = node('div', 'provider-item');
            row.append(node('strong', '', providerName(provider, kind)), node('span', `provider-state ${provider.available !== true ? 'unavailable' : ''}`, provider.synthetic ? '模拟' : provider.available === true ? '可用' : '未就绪'));
            if (provider.reason) row.append(node('p', '', provider.reason));
            container.append(row);
          }
          if (entries.some(item => item.id === selected)) select.value = selected;
        } else container.append(node('p', 'muted', '服务能力尚未确认。'));
      }
      renderProviderNotes();
    } catch (error) { showError(`无法读取语音服务状态：${error.message}`); }
  }
  function renderHistory() {
    const list = $('history-list'); list.replaceChildren();
    $('history-count').textContent = history.length ? `${history.length} 条记录${history.length > historyLimit ? ` · 显示最近 ${historyLimit} 条` : ''}` : '暂无聊天记录';
    $('history-more').hidden = history.length <= historyLimit;
    if (!history.length) list.append(node('p', 'empty', '目前没有聊天历史。'));
    for (const message of history.slice(-historyLimit)) {
      const entry = node('article', 'record-entry');
      entry.dataset.messageId = message.id;
      const header = node('div', 'record-header');
      const role = node('div'); role.append(node('span', '', message.role === 'user' ? '你' : message.origin === 'proactive' ? '主动消息' : '桌宠'));
      if (message.metadata?.synthetic === true) role.append(node('span', 'badge synthetic', '模拟'));
      header.append(role, node('time', '', UI.timestampLabel(message.createdAt)));
      entry.append(header, node('p', 'record-text', typeof message.text === 'string' ? message.text : '消息内容不可用'), node('p', 'record-session', `会话 ${message.sessionId || '未知'}`));
      if (message.role !== 'user') {
        entry.append(metadataTags(message.metadata), metadataView(message.metadata));
        if (Array.isArray(message.cards) && message.cards.length) {
          const details = node('details', 'metadata'); details.append(node('summary', '', `信息卡（${message.cards.length}）`));
          message.cards.forEach(card => details.append(cardView(card, message.metadata))); entry.append(details);
        }
      }
      list.append(entry);
    }
  }
  async function refreshHistory() {
    const request = ++historyLoad;
    try {
      const value = unwrap(await api.getHistory());
      if (stopped || request !== historyLoad) return;
      history = Array.isArray(value.messages) ? value.messages : [];
      $('history-enabled').checked = value.enabled === true;
      renderHistory();
    } catch (error) { if (request === historyLoad) showError(error.message); }
  }
  async function refreshMemories() {
    const request = ++memoryLoad;
    try {
      const value = unwrap(await api.getMemories());
      if (stopped || request !== memoryLoad) return;
      const entries = Array.isArray(value.entries) ? value.entries : [];
      const list = $('memory-list'); list.replaceChildren();
      $('memory-count').textContent = `${entries.length} 条`;
      if (!entries.length) list.append(node('p', 'empty', '还没有明确保存的记忆。'));
      for (const entry of entries) {
        const row = node('div', 'record-entry memory-entry'); row.dataset.memoryId = entry.id;
        const body = node('div'); body.append(node('p', 'record-text', entry.text || '空记忆'), node('time', 'record-session', UI.timestampLabel(entry.createdAt)));
        const remove = node('button', 'text-button danger', '删除'); remove.setAttribute('aria-label', `删除记忆：${String(entry.text || '').slice(0, 30)}`);
        remove.addEventListener('click', async () => {
          const result = await perform(() => api.deleteMemory(entry.id), { button: remove, success: '这条记忆已删除。' });
          if (result !== undefined) refreshMemories();
        });
        row.append(body, remove); list.append(row);
      }
    } catch (error) { if (request === memoryLoad) showError(error.message); }
  }
  function scheduleRecords() {
    clearTimeout(recordsTimer);
    recordsTimer = setTimeout(() => { refreshHistory(); refreshMemories(); }, 35);
  }
  function setPage(page) {
    if (!PAGES[page]) return;
    activePage = page;
    for (const button of document.querySelectorAll('[data-page]')) {
      const current = button.dataset.page === page;
      button.classList.toggle('active', current);
      if (current) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    }
    for (const section of document.querySelectorAll('.settings-page')) section.hidden = section.id !== `page-${page}`;
    $('page-title').textContent = PAGES[page][0]; $('page-description').textContent = PAGES[page][1];
    if (page === 'records') { refreshHistory(); refreshMemories(); }
    if (page === 'voice') refreshSpeech();
    if (page === 'companion') refreshPersona();
    window.scrollTo({ top: 0 });
  }
  function onEvent(event) {
    if (!event || stopped) return;
    if (event.type === 'update' || event.type === 'update-status') { renderUpdate(event.status || event.state); return; }
    if (event.type === 'state') { applyState(event.state); return; }
    if (event.type === 'speech') {
      const value = event.state || {};
      if (state && ((value.generation !== undefined && value.generation !== state.epoch) || (value.conversationId && value.conversationId !== state.sessionId))) return;
      if (value.provider && state?.preferences?.ttsProvider && value.provider !== state.preferences.ttsProvider) return;
      $('speech-state').textContent = ({ speaking: '正在播报', started: '正在播报', finished: '播报完成', stopped: '语音已停止', cancelled: '语音已取消', error: '语音操作失败' })[value.state] || '语音状态已更新';
      return;
    }
    if (event.type === 'stop-speech') { $('speech-state').textContent = '语音已停止'; return; }
    if (event.type === 'tool' && UI.belongsToSession(event, state)) { tools.set(event.tool.id, event); renderTasks(); }
    if (event.type === 'message' && UI.belongsToSession(event.message, state)) {
      state.messages = [...(state.messages || []).filter(item => item.id !== event.message.id), event.message];
      renderObservations();
      if (activePage === 'records') { historyLoad += 1; scheduleRecords(); }
    }
  }
  function renderPersona(value) {
    if (!value) return;
    const ready = value.status === 'ready';
    $('persona-status').textContent = ready ? value.created ? '已首次创建人设文件。' : '人设文件可用；编辑保存后下次请求生效。' : '自定义人设不可用，当前使用默认人设。';
    $('persona-path').textContent = typeof value.path === 'string' ? value.path : '尚无可用路径';
    $('persona-note').textContent = value.external ? '外部服务模式：路径由已认证后端提供，应用无法确认本机安全位置，不自动打开。请在该后端所在机器编辑。' : !ready ? `请检查文件状态（${value.reason || '未知原因'}）；原文件不会被覆盖。` : value.canOpen ? '将在系统默认文本编辑器或文件管理器中打开。' : '当前文件位置无法安全确认，暂不自动打开。';
    $('persona-open-file').disabled = !ready || value.canOpen !== true;
    $('persona-open-folder').disabled = !ready || value.canOpen !== true;
  }
  async function refreshPersona() {
    $('persona-open-file').disabled = true;
    $('persona-open-folder').disabled = true;
    const value = await perform(() => api.personaStatus(), { button: $('persona-refresh') });
    if (value) renderPersona(value);
    else { $('persona-status').textContent = '无法读取人设状态，请确认本机后台已连接后重试。'; $('persona-path').textContent = ''; $('persona-note').textContent = ''; }
  }
  function renderBootstrap(value) {
    if (!value) return;
    const backend = { ready: '已连接', starting: '正在启动', stopped: '已停止', unavailable: '不可用', error: '启动失败' }[value.backend?.state] || '待确认';
    const game = { running: '检测到游戏进程', not_detected: '未检测到游戏进程', unknown: '游戏进程状态未知' }[value.game?.state] || '游戏进程状态未知';
    $('bootstrap-status').textContent = `后台服务：${backend}（${value.backend?.owned ? '由应用管理' : '外部或尚未启动'}） · ${game}。进程检测不代表数据已连接。`;
    $('bootstrap-reader').textContent = value.readerPlatformSupported === false ? '此平台当前尚不支持真实游戏页面读取；可使用桌宠与模拟演示。' : value.bridgeConfigured === null ? '外部后端的 Reader 配置请以页面预览为准。' : value.bridgeConfigured ? 'Reader 已配置，真实页面读取结果请以当前页面预览为准。' : '尚未配置本机 Reader bridge；检测到游戏进程也不能读取页面。';
  }
  function renderUpdate(value) {
    if (!value) return;
    const labels = { ready_for_safe_exit: '已验证更新就绪，等待正常安全退出', deferred: '更新等待中，当前有游戏或交互任务，不会强制安装', installing: '正在正常退出并安装已验证更新', recovery_required: '更新后健康检查未通过，已暂停自动更新，请检查恢复信息', blocked: '更新校验或安全条件未满足，未安装', disabled: '尚未配置可信 Alpha 更新源', idle: '等待检查官方 Release', up_to_date: '当前已是最新版本', update_available: '发现官方新版本', manual_required: '请前往官方 Release 手动下载与安装', no_release: '官方尚未发布可用版本', network_error: '无法连接官方更新源，可重试', checking: '正在检查', available: '有已验证的新版本', downloading: '正在下载', downloaded: '已验证安装包已下载，请退出后手动安装', 'up-to-date': '当前已是最新版本', error: '更新失败，可重试' };
    const installation = value.installation || {};
    const displayState = value.recovery?.state === 'recovery_required' ? 'recovery_required' : ['ready_for_safe_exit', 'deferred', 'installing', 'blocked'].includes(installation.state) ? installation.state : value.state;
    $('update-mode-note').textContent = value.automaticInstallEnabled === true ? '可信自动安装通道已启用：后台下载并验证，FM 未运行且对话、录音、设置及后台任务均空闲时自动安装并重启；不会强退游戏。系统可能仍显示确认提示。配置保留，异常时暂停后续更新。' : '此安装包当前使用手动安装。自动安装信任配置尚未启用；可查看官方下载页。不会为更新结束游戏或覆盖本机模型配置。';
    $('update-status').textContent = `当前版本 ${value.currentVersion || '未知'} · ${labels[displayState] || '状态未知'}${value.availableVersion ? ' · ' + value.availableVersion : ''}`;
    $('update-check').disabled = ['disabled', 'checking', 'downloading', 'installing'].includes(displayState);
    $('update-download').disabled = !['available', 'update_available'].includes(value.state) || value.signedDownloadAvailable !== true || ['installing', 'recovery_required', 'blocked'].includes(displayState);
  }
  function renderModelConfig(value) {
    if (!value) return;
    $('model-provider').value = value.provider;
    $('model-base-url').value = value.baseUrl;
    $('model-name').value = value.model;
    $('model-api-key').value = '';
    $('model-storage-note').textContent = value.hasApiKey
      ? value.storage === 'encrypted' ? '已配置密钥 · 使用系统安全存储加密保存。' : '已配置密钥 · 仅本次运行有效，退出后需重新输入。'
      : value.secureStorageAvailable ? '尚未配置密钥 · 可使用系统安全存储。' : '尚未配置密钥 · 系统安全存储不可用，仅支持会话内使用。';
  }
  async function saveModelConfig(removeKey = false) {
    const input = { provider: $('model-provider').value, baseUrl: $('model-base-url').value, model: $('model-name').value };
    if (removeKey) input.removeKey = true;
    else if ($('model-api-key').value) input.apiKey = $('model-api-key').value;
    // Clear typed secret before IPC settles; never echo it in notices or logs.
    $('model-api-key').value = '';
    $('model-remove-key').disabled = true;
    const value = await perform(() => api.saveModelConfig(input), { button: $('model-save') });
    delete input.apiKey;
    $('model-remove-key').disabled = false;
    if (value) { renderModelConfig(value); notice(value.restartRequired ? '配置已保存。现有外部服务需由你重启后生效。' : '模型配置已保存；尚未发送模型请求。'); }
  }
  function bind() {
    document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => setPage(button.dataset.page)));
    Object.entries(UI.EXPRESSIONS).forEach(([value, label]) => { const option = node('option', '', label); option.value = value; $('expression').append(option); });
    $('mode').addEventListener('change', async () => {
      const result = await perform(() => api.setMode($('mode').value));
      if (result) applyState(result); else if (state) renderConnection();
    });
    $('refresh-reader').addEventListener('click', () => perform(() => api.refreshReaderPreviews(), { button: $('refresh-reader') }));
    $('simulate-scenario').addEventListener('click', () => perform(() => api.simulateEvent($('scenario').value), { button: $('simulate-scenario'), success: '示例已发送到桌宠气泡。' }));
    $('simulate-event').addEventListener('click', () => perform(() => api.simulateEvent(), { button: $('simulate-event'), success: '模拟主动消息已发送。' }));
    $('proactivity').addEventListener('input', () => { proactivityEditing = true; $('proactivity-value').textContent = `${$('proactivity').value}%`; });
    $('proactivity').addEventListener('change', async () => { const value = Number($('proactivity').value); proactivityEditing = false; const result = await perform(() => api.setProactivity(value)); if (result) applyState(result); else if (state) renderPreferences(); });
    for (const [id, key] of [['expression', 'expression'], ['stt-provider', 'sttProvider'], ['tts-provider', 'ttsProvider']]) {
      $(id).addEventListener('change', async () => { const result = await perform(() => api.setPreferences({ [key]: $(id).value })); if (result) applyState(result); else if (state) renderPreferences(); });
    }
    $('stop-speech').addEventListener('click', () => perform(() => api.stopSpeech(), { button: $('stop-speech'), success: '语音操作已停止。' }));
    $('history-enabled').addEventListener('change', async () => { await perform(() => api.setHistoryEnabled($('history-enabled').checked)); refreshHistory(); });
    $('new-conversation').addEventListener('click', async () => { const result = await perform(() => api.newConversation(), { button: $('new-conversation'), success: '已开始新对话。' }); if (result) applyState(result); });
    $('refresh-history').addEventListener('click', refreshHistory);
    $('history-more').addEventListener('click', () => { historyLimit += 40; renderHistory(); });
    $('clear-history').addEventListener('click', async () => { const result = await perform(() => api.clearHistory(), { button: $('clear-history'), success: '聊天历史已清除，明确保存的记忆不受影响。' }); if (result !== undefined) refreshHistory(); });
    $('save-memory').addEventListener('click', async () => {
      const input = $('memory-text'); const text = input.value.trim();
      if (!text) { input.focus(); showError('请先输入希望保存的记忆内容。'); return; }
      const result = await perform(() => api.saveMemory({ text }), { button: $('save-memory'), success: '已明确保存这条记忆。' });
      if (result !== undefined) { if (input.value.trim() === text) input.value = ''; refreshMemories(); }
    });
    $('persona-refresh').addEventListener('click', refreshPersona);
    $('persona-open-file').addEventListener('click', () => perform(() => api.openPersonaFile(), { button: $('persona-open-file') }));
    $('persona-open-folder').addEventListener('click', () => perform(() => api.openPersonaFolder(), { button: $('persona-open-folder') }));
    $('update-open-release').addEventListener('click', () => perform(() => api.openUpdateRelease(), { button: $('update-open-release') }));
    $('bootstrap-refresh').addEventListener('click', async () => renderBootstrap(await perform(() => api.bootstrapStatus(), { button: $('bootstrap-refresh') })));
    $('update-check').addEventListener('click', async () => renderUpdate(await perform(() => api.checkUpdate(), { button: $('update-check') })));
    $('update-download').addEventListener('click', async () => renderUpdate(await perform(() => api.downloadUpdate(), { button: $('update-download') })));
    $('model-config-form').addEventListener('submit', event => { event.preventDefault(); saveModelConfig(); });
    $('model-remove-key').addEventListener('click', () => saveModelConfig(true));
    $('quit').addEventListener('click', () => perform(() => api.quit()));
    window.addEventListener('beforeunload', () => { stopped = true; clearTimeout(recordsTimer); clearTimeout(noticeTimer); unsubscribe?.(); });
  }

  if (!api || !UI) { showError('设置桥接未就绪，请从桌宠菜单打开设置。'); return; }
  bind();
  window.CompanionBridgeSettings?.mountBridgeSettings({ document, api }).refresh();
  unsubscribe = api.subscribe(onEvent);
  perform(() => api.getState()).then(value => { if (value) applyState(value); });
  refreshSpeech();
  perform(() => api.getModelConfig()).then(renderModelConfig);
  perform(() => api.updateStatus()).then(renderUpdate);
  perform(() => api.bootstrapStatus()).then(renderBootstrap);
  refreshPersona();
})();
