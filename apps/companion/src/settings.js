'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const api = window.companion;
  const UI = window.CompanionUI;
  const PAGES = { connection: '连接', voice: '输入', records: '历史与记忆', appearance: '外观', about: '关于' };
  let state = null, activePage = 'connection', speechInfo = null;
  let history = [], historyLimit = 40, historyLoad = 0, memoryLoad = 0;
  let recordsTimer, noticeTimer, unsubscribe, stopped = false, proactivityEditing = false;
  let providers = [], savedConfig = null, modelGeneration = 0, modelReadyGeneration = -1, modelBusy = false, modelSaving = false;
  let personaRevision = null, personaDirty = false, personaLoad = 0;
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }
  function unwrap(result) {
    if (!result?.ok) throw new Error(result?.error || '操作失败');
    return result.value;
  }
  function showError(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
  function notice(message) {
    clearTimeout(noticeTimer); $('notice').textContent = message || ''; $('notice').hidden = !message;
    if (message) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 4500);
  }
  async function perform(action, { success, button } = {}) {
    showError(''); if (button) button.disabled = true;
    try { const value = unwrap(await action()); if (success) notice(success); return value; }
    catch (error) { showError(error.message); return undefined; }
    finally { if (button) button.disabled = false; }
  }
  function metadataTags(metadata) {
    const tags = node('div', 'observation-tags');
    UI.observationLabels(metadata).forEach(label => tags.append(node('span', 'badge', label)));
    return tags;
  }
  function metadataView(value) {
    const metadata = value && typeof value === 'object' ? value : {};
    const details = node('details', 'metadata'); details.append(node('summary', '', '来源'));
    const fields = node('dl');
    for (const [label, data] of [['来源', metadata.sourceLabel || metadata.source], ['会话', metadata.sessionId], ['采样时间', UI.timestampLabel(metadata.sampledAt)]]) {
      if (data) fields.append(node('dt', '', label), node('dd', '', typeof data === 'string' ? data : JSON.stringify(data)));
    }
    details.append(fields); return details;
  }
  function cardView(card, inherited = {}) {
    const element = node('section', 'info-card'); element.append(node('h3', '', card.title || '信息卡'));
    const fields = node('dl', 'card-fields');
    for (const field of Array.isArray(card.fields) ? card.fields : []) fields.append(node('dt', '', field?.label || '未知字段'), node('dd', '', UI.valueLabel(field)));
    const metadata = { ...inherited, ...card.metadata };
    element.append(fields, metadataTags(metadata), metadataView(metadata)); return element;
  }
  function renderConnection() {
    const connection = state?.connection;
    const unavailable = !connection || ['disconnected', 'unavailable', 'error'].includes(connection.state);
    // A mock state must never masquerade as a working API/backend connection.
    $('connection-status').textContent = unavailable ? '后台未连接' : state.synthetic === true || state.mode === 'mock' ? '模拟模式' : connection.state === 'connected' ? '后台已连接' : '连接未确认';
  }
  function renderCharacter() {
    const character = state?.character;
    $('expression').disabled = character?.visual?.kind === 'builtin-image' || !character;
  }
  function renderPreferences() {
    if (!proactivityEditing) { $('proactivity').value = String(state.proactivity ?? 80); $('proactivity-value').textContent = `${state.proactivity ?? 80}%`; }
    $('expression').value = state.preferences?.expression || 'auto';
    $('stt-provider').value = state.preferences?.sttProvider || 'local-whisper';
    $('history-enabled').checked = state.historyEnabled === true;
    renderSpeechStatus();
  }
  function applyState(next) {
    if (!next || !Number.isSafeInteger(next.epoch) || typeof next.sessionId !== 'string') return;
    if (state && next.epoch < state.epoch) return;
    const switched = state && (next.epoch !== state.epoch || next.sessionId !== state.sessionId);
    state = next; historyLoad += 1; memoryLoad += 1;
    if (switched) { history = []; historyLimit = 40; renderHistory(); }
    renderConnection(); renderCharacter(); renderPreferences();
    if (next.storageWarning) showError(next.storageWarning);
    if (activePage === 'records') scheduleRecords();
  }
  function renderSpeechStatus() {
    const selected = $('stt-provider').value;
    const provider = speechInfo?.stt?.find(item => item.id === selected);
    $('stt-note').textContent = !provider ? '状态未确认' : provider.synthetic || selected === 'mock' ? '模拟转写' : provider.available === true ? '已就绪' : '未就绪';
  }
  async function refreshSpeech() {
    const value = await perform(() => api.speechCapabilities()); if (!value || stopped) return;
    speechInfo = value;
    const select = $('stt-provider'), selected = state?.preferences?.sttProvider || select.value || 'local-whisper';
    select.replaceChildren();
    for (const provider of Array.isArray(value.stt) ? value.stt : []) {
      if (provider.synthetic || provider.id === 'mock') continue;
      const option = node('option', '', provider.label || provider.id); option.value = provider.id; select.append(option);
    }
    if (![...select.options].some(option => option.value === selected)) {
      const option = node('option', '', selected === 'mock' ? '模拟转写' : '未就绪'); option.value = selected; option.disabled = true; select.append(option);
    }
    select.value = selected; select.disabled = select.options.length === 0; renderSpeechStatus();
  }
  function renderHistory() {
    const list = $('history-list'); list.replaceChildren();
    $('history-count').textContent = history.length ? `${history.length} 条记录${history.length > historyLimit ? ` · 显示最近 ${historyLimit} 条` : ''}` : '暂无聊天记录';
    $('history-more').hidden = history.length <= historyLimit;
    if (!history.length) list.append(node('p', 'empty', '暂无记录'));
    for (const message of history.slice(-historyLimit)) {
      const entry = node('article', 'record-entry');
      entry.dataset.messageId = message.id;
      const header = node('div', 'record-header');
      const role = node('div'); role.append(node('span', '', message.role === 'user' ? '你' : message.origin === 'proactive' ? '主动消息' : '桌宠'));
      if (message.metadata?.synthetic === true) role.append(node('span', 'badge synthetic', '模拟'));
      header.append(role, node('time', '', UI.timestampLabel(message.createdAt)));
      entry.append(header, node('p', 'record-text', typeof message.text === 'string' ? message.text : '消息内容不可用'));
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
      if (!entries.length) list.append(node('p', 'empty', '暂无记忆'));
      for (const entry of entries) {
        const row = node('div', 'record-entry memory-entry'); row.dataset.memoryId = entry.id;
        const body = node('div'); body.append(node('p', 'record-text', entry.text || '空记忆'), node('time', 'record-session', UI.timestampLabel(entry.createdAt)));
        const remove = node('button', 'text-button danger', '删除'); remove.setAttribute('aria-label', `删除记忆：${String(entry.text || '').slice(0, 30)}`);
        remove.addEventListener('click', async () => {
          const result = await perform(() => api.deleteMemory(entry.id), { button: remove, success: '已删除' });
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
    if (!Object.hasOwn(PAGES, page)) page = 'connection';
    activePage = page;
    for (const button of document.querySelectorAll('[data-page]')) {
      const current = button.dataset.page === page; button.classList.toggle('active', current);
      if (current) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    }
    for (const section of document.querySelectorAll('.settings-page')) section.hidden = section.id !== `page-${page}`;
    $('page-title').textContent = PAGES[page];
    if (page === 'records') { refreshHistory(); refreshMemories(); }
    if (page === 'voice') refreshSpeech();
    if (page === 'companion' && !personaDirty) refreshPersona();
    window.scrollTo({ top: 0 });
  }
  function onEvent(event) {
    if (!event || stopped) return;
    if (event.type === 'update' || event.type === 'update-status') { renderUpdate(event.status || event.state); return; }
    if (event.type === 'state') { applyState(event.state); return; }
    if (event.type === 'message' && UI.belongsToSession(event.message, state) && activePage === 'records') { historyLoad += 1; scheduleRecords(); }
  }
  function invalidateModels() {
    modelGeneration += 1; modelReadyGeneration = -1;
    api?.cancelModelList?.().catch(() => {});
    $('model-name').replaceChildren(node('option', '', '未读取')); $('model-name').firstChild.value = '';
    $('model-name').disabled = true; $('model-save').disabled = true;
  }
  function selectedProvider() { return providers.find(item => item.id === $('model-provider').value); }
  function savedCredentialSelected() {
    const provider = $('model-provider').value;
    const baseUrl = (provider === 'openai-compatible' ? $('model-base-url').value.trim() : selectedProvider()?.baseUrl || '').replace(/\/+$/, '');
    return savedConfig?.provider === provider && savedConfig.baseUrl === baseUrl && savedConfig.hasApiKey;
  }
  function renderCredentialStatus() {
    const configured = savedCredentialSelected(), draft = Boolean($('model-api-key').value);
    // The mask is a placeholder, never an input value or a secret readback.
    $('model-api-key').placeholder = configured ? '••••••••' : '输入 API Key';
    $('model-api-key').setAttribute('aria-label', configured ? 'API Key，已配置；输入新密钥以替换' : 'API Key');
    $('model-storage-note').textContent = draft ? configured ? '新密钥待保存' : '密钥待保存' : configured ? savedConfig.storage === 'encrypted' ? '密钥已配置' : '密钥已配置（仅本次）' : '未配置密钥';
    $('model-remove-key').disabled = modelSaving || !configured;
  }
  function updateProvider() {
    const custom = $('model-provider').value === 'openai-compatible';
    $('custom-url-row').hidden = !custom; $('model-base-url').required = custom;
    $('model-api-key').value = '';
    $('model-base-url').value = custom ? savedConfig?.provider === 'openai-compatible' ? savedConfig.baseUrl : '' : selectedProvider()?.baseUrl || '';
    renderCredentialStatus();
    invalidateModels();
  }
  function renderModelConfig(value) {
    if (!value) return; savedConfig = value;
    $('model-provider').value = value.provider;
    $('model-base-url').value = value.baseUrl || '';
    $('custom-url-row').hidden = value.provider !== 'openai-compatible';
    $('model-base-url').required = value.provider === 'openai-compatible';
    $('model-api-key').value = '';
    renderCredentialStatus();
    invalidateModels();
  }
  async function loadModelConfiguration() {
    const generation = modelGeneration;
    const registry = await perform(() => api.getModelProviders());
    if (!registry) return;
    providers = registry.providers || []; $('model-provider').replaceChildren();
    for (const provider of providers) {
      const option = node('option', '', provider.name || provider.id); option.value = provider.id; option.disabled = provider.disabled === true; $('model-provider').append(option);
    }
    $('model-provider').disabled = !providers.length;
    const value = await perform(() => api.getModelConfig());
    if (generation === modelGeneration) renderModelConfig(value);
    else if (value) { savedConfig = value; renderCredentialStatus(); }
  }
  async function fetchModels() {
    const generation = ++modelGeneration; modelReadyGeneration = -1; modelBusy = true;
    $('model-save').disabled = true; $('model-name').disabled = true; $('model-fetch').disabled = true;
    const input = { provider: $('model-provider').value };
    if (input.provider === 'openai-compatible') input.baseUrl = $('model-base-url').value.trim();
    if ($('model-api-key').value) input.apiKey = $('model-api-key').value;
    try {
      showError(''); const value = unwrap(await api.listModels(input));
      if (stopped || generation !== modelGeneration) return;
      const models = Array.isArray(value.models) ? value.models.filter(item => typeof item.id === 'string' && item.id) : [];
      $('model-name').replaceChildren();
      for (const model of models) { const option = node('option', '', model.name || model.id); option.value = model.id; $('model-name').append(option); }
      if (!models.length) { const option = node('option', '', '无可用模型'); option.value = ''; $('model-name').append(option); return; }
      if (savedConfig?.provider === input.provider && models.some(item => item.id === savedConfig.model)) $('model-name').value = savedConfig.model;
      modelReadyGeneration = generation; $('model-name').disabled = false; $('model-save').disabled = false;
    } catch (error) { if (generation === modelGeneration) showError(error.message); }
    finally { delete input.apiKey; modelBusy = false; $('model-fetch').disabled = false; }
  }
  async function saveModelConfig(removeKey = false) {
    if (modelSaving || (removeKey && !savedCredentialSelected())) return;
    if (!removeKey && (modelBusy || modelReadyGeneration !== modelGeneration || !$('model-name').value)) { showError('请读取并选择模型'); return; }
    const generation = modelGeneration;
    const provider = $('model-provider').value;
    const input = { provider, baseUrl: provider === 'openai-compatible' ? $('model-base-url').value.trim() : selectedProvider()?.baseUrl || '', model: $('model-name').value || savedConfig?.model || '' };
    if (removeKey) input.removeKey = true; else if ($('model-api-key').value) input.apiKey = $('model-api-key').value;
    modelSaving = true; $('model-save').disabled = true; $('model-remove-key').disabled = true;
    const value = await perform(() => api.saveModelConfig(input)); delete input.apiKey;
    modelSaving = false;
    if (value) {
      savedConfig = value;
      if (generation === modelGeneration) renderModelConfig(value);
      notice(value.restartRequired ? '已保存，待重启服务' : '已保存');
    } else if (generation === modelGeneration) $('model-save').disabled = modelReadyGeneration !== modelGeneration;
    renderCredentialStatus();
  }
  function renderPersona(value) {
    personaRevision = value.revision;
    $('persona-content').value = typeof value.content === 'string' ? value.content : '';
    $('persona-content').disabled = value.canEdit !== true;
    $('persona-save').disabled = true; personaDirty = false;
    $('persona-status').textContent = value.status === 'ready' ? '已读取' : '不可用';
    $('persona-open-file').disabled = value.canOpen !== true; $('persona-open-folder').disabled = value.canOpen !== true;
  }
  async function refreshPersona() {
    if (personaDirty) { if (!window.confirm('放弃未保存的修改？')) return; personaDirty = false; }
    $('persona-open-file').disabled = true; $('persona-open-folder').disabled = true;
    const request = ++personaLoad;
    $('persona-refresh').disabled = true;
    const value = await perform(() => api.getPersona());
    $('persona-refresh').disabled = false;
    if (request !== personaLoad || stopped) return;
    // Never replace text typed while the read was in flight.
    if (value && !personaDirty) renderPersona(value);
    else if (!value) $('persona-status').textContent = '读取失败';
  }
  async function savePersona() {
    const content = $('persona-content').value;
    const value = await perform(() => api.savePersona({ content, revision: personaRevision }), { button: $('persona-save') });
    if (!value) return;
    if ($('persona-content').value === content) renderPersona(value);
    else { personaRevision = value.revision; personaDirty = true; $('persona-save').disabled = false; }
    notice('已保存');
  }
  function renderUpdate(value) {
    if (!value) return;
    const labels = { ready_for_safe_exit:'更新已就绪', deferred:'等待安装', installing:'正在安装', recovery_required:'更新恢复待处理', blocked:'更新已阻止', disabled:'更新不可用', idle:'尚未检查', up_to_date:'已是最新版本', update_available:'发现新版本', manual_required:'需要手动安装', no_release:'暂无版本', network_error:'连接失败', checking:'正在检查', available:'发现新版本', downloading:'正在下载', downloaded:'已下载', 'up-to-date':'已是最新版本', error:'更新失败' };
    const installation = value.installation || {};
    const status = value.recovery?.state === 'recovery_required' ? 'recovery_required' : ['ready_for_safe_exit','deferred','installing','blocked'].includes(installation.state) ? installation.state : value.state;
    $('app-version').textContent = value.currentVersion || '版本未确认';
    $('update-status').textContent = (labels[status] || '状态未知') + (value.availableVersion ? ` · ${value.availableVersion}` : '');
    $('update-check').disabled = ['disabled','checking','downloading','installing'].includes(status);
    $('update-download').disabled = !['available','update_available'].includes(value.state) || value.signedDownloadAvailable !== true || ['installing','recovery_required','blocked'].includes(status);
  }
  const Appearance = window.CompanionAppearance;
  const APPEARANCE_KEY = Appearance.KEY;
  function applyAppearance(value) {
    const prefs = Appearance.apply(document, value);
    $('font-family').value = prefs.fontFamily; $('font-size').value = String(prefs.fontSize); $('dark-mode').checked = prefs.darkMode; $('light-motion').checked = prefs.lightMotion;
    $('bubble-duration-mode').value = prefs.bubbleDurationMode;
    $('bubble-duration-seconds').value = String(prefs.bubbleDurationSeconds);
    $('bubble-duration-row').hidden = prefs.bubbleDurationMode !== 'fixed';
  }
  function saveAppearance() {
    const value = { ...Appearance.normalize(readAppearance()), fontFamily:$('font-family').value, fontSize:Number($('font-size').value), darkMode:$('dark-mode').checked, lightMotion:$('light-motion').checked };
    try { localStorage.setItem(APPEARANCE_KEY, JSON.stringify(value)); applyAppearance(value); }
    catch { showError('外观保存失败'); }
  }
  function readAppearance() {
    try { return JSON.parse(localStorage.getItem(APPEARANCE_KEY) || '{}') || {}; } catch { return {}; }
  }
  function saveBubbleDuration() {
    let seconds = Number($('bubble-duration-seconds').value);
    const fixed = $('bubble-duration-mode').value === 'fixed';
    if (fixed && (!Number.isInteger(seconds) || seconds < 2 || seconds > 60)) {
      showError('对白停留时间请输入 2–60 的整数秒数'); return;
    }
    try {
      if (!fixed) seconds = Appearance.normalize(readAppearance()).bubbleDurationSeconds;
      const value = { ...readAppearance(), bubbleDurationMode:fixed ? 'fixed' : 'auto', bubbleDurationSeconds:seconds };
      localStorage.setItem(APPEARANCE_KEY, JSON.stringify(value)); applyAppearance(value); showError('');
    } catch { showError('外观保存失败'); }
  }
  function saveLightMotion() {
    try {
      let previous = {};
      try { previous = JSON.parse(localStorage.getItem(APPEARANCE_KEY) || '{}'); } catch {}
      const value = { ...previous, lightMotion:$('light-motion').checked };
      localStorage.setItem(APPEARANCE_KEY, JSON.stringify(value)); applyAppearance(value);
    } catch { showError('外观保存失败'); }
  }
  function bind() {
    for (const [id, action] of [['window-minimize','minimize'],['window-maximize','toggle-maximize'],['window-close','close']]) {
      $(id).addEventListener('click', () => perform(() => api.controlSettingsWindow(action)));
    }
    document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => setPage(button.dataset.page)));
    Object.entries(UI.EXPRESSIONS).forEach(([value,label]) => { if (value === 'auto') return; const option=node('option','',label); option.value=value; $('expression').append(option); });
    $('proactivity').addEventListener('input', () => { proactivityEditing=true; $('proactivity-value').textContent=`${$('proactivity').value}%`; });
    $('proactivity').addEventListener('change', async () => { const result=await perform(() => api.setProactivity(Number($('proactivity').value))); proactivityEditing=false; if(result) applyState(result); else if(state) renderPreferences(); });
    for (const [id,key] of [['expression','expression'],['stt-provider','sttProvider']]) $(id).addEventListener('change',async () => { const result=await perform(() => api.setPreferences({[key]:$(id).value})); if(result) applyState(result); else if(state) renderPreferences(); });
    $('history-enabled').addEventListener('change',async () => { await perform(() => api.setHistoryEnabled($('history-enabled').checked)); refreshHistory(); });
    $('new-conversation').addEventListener('click',async () => { const result=await perform(() => api.newConversation(),{button:$('new-conversation'),success:'已开始新对话'}); if(result) applyState(result); });
    $('refresh-history').addEventListener('click',refreshHistory);
    $('history-more').addEventListener('click',() => { historyLimit+=40; renderHistory(); });
    $('clear-history').addEventListener('click',async () => { if(!window.confirm('清除全部聊天历史？')) return; const result=await perform(() => api.clearHistory(),{button:$('clear-history'),success:'已清除'}); if(result!==undefined) refreshHistory(); });
    $('save-memory').addEventListener('click',async () => { const input=$('memory-text'), text=input.value.trim(); if(!text) {input.focus();return;} const result=await perform(() => api.saveMemory({text}),{button:$('save-memory'),success:'已保存'}); if(result!==undefined) {if(input.value.trim()===text)input.value='';refreshMemories();} });
    $('model-provider').addEventListener('change',updateProvider);
    $('model-api-key').addEventListener('input',() => { invalidateModels(); renderCredentialStatus(); });
    $('model-base-url').addEventListener('input',() => { invalidateModels(); renderCredentialStatus(); });
    $('model-fetch').addEventListener('click',fetchModels);
    $('model-config-form').addEventListener('submit',event => {event.preventDefault();saveModelConfig();});
    $('model-remove-key').addEventListener('click',() => saveModelConfig(true));
    $('persona-content').addEventListener('input',() => {personaDirty=true;personaLoad+=1;$('persona-save').disabled=false;$('persona-status').textContent='未保存';});
    $('persona-refresh').addEventListener('click',refreshPersona);
    $('persona-save').addEventListener('click',savePersona);
    $('persona-open-file').addEventListener('click',() => perform(() => api.openPersonaFile()));
    $('persona-open-folder').addEventListener('click',() => perform(() => api.openPersonaFolder()));
    $('update-check').addEventListener('click',async () => renderUpdate(await perform(() => api.checkUpdate(),{button:$('update-check')})));
    $('update-download').addEventListener('click',async () => renderUpdate(await perform(() => api.downloadUpdate(),{button:$('update-download')})));
    $('update-open-release').addEventListener('click',() => perform(() => api.openUpdateRelease()));
    $('open-repository').addEventListener('click',() => perform(() => api.openRepository()));
    $('open-contributors').addEventListener('click',() => perform(() => api.openContributors()));
    for (const id of ['bubble-duration-mode','bubble-duration-seconds']) $(id).addEventListener('change',saveBubbleDuration);
    for (const id of ['font-family','font-size','dark-mode']) $(id).addEventListener('change',saveAppearance);
    $('light-motion').addEventListener('change',saveLightMotion);
    window.addEventListener('beforeunload',event => { if(personaDirty) {event.preventDefault();event.returnValue='';return;} stopped=true;api.cancelModelList?.().catch(() => {});clearTimeout(recordsTimer);clearTimeout(noticeTimer);unsubscribe?.(); });
  }
  try { applyAppearance(JSON.parse(localStorage.getItem(APPEARANCE_KEY) || '{}')); } catch { applyAppearance({}); }
  if (!api || !UI) { showError('设置服务未连接'); return; }
  bind(); unsubscribe=api.subscribe(onEvent);
  perform(() => api.getState()).then(value => {if(value)applyState(value);});
  loadModelConfiguration(); refreshSpeech();
  perform(() => api.getAbout()).then(value => { if(value?.version) $('app-version').textContent=value.version; });
  perform(() => api.updateStatus()).then(renderUpdate);
})();
