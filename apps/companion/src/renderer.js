'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const api = window.companion;
  const UI = window.CompanionUI;
  let state = null;
  let messages = new Map();
  const tools = new Map();
  const requests = new Map();
  let lastReply = null;
  let noticeTimer;
  let speechInfo = null;
  let recording = null;
  let speechOperation = null;
  let player = null;
  let playerUrl = null;
  let speechPhase = 'idle';
  let holdTimer;
  let dragReady = Promise.resolve();
  let dragMovePending = false;
  const gesture = UI.createGesture();
  const voiceFence = UI.createFence();
  const operationId = prefix => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  const unwrap = result => {
    if (!result?.ok) throw new Error(result?.error || '桌宠请求失败，请重试。');
    return result.value;
  };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };

  function updateRects() {
    if (!api?.inputRects) return;
    const rects = [$('pet'), $('panel').hidden ? $('compact-bubble') : $('panel')].filter(item => item && !item.hidden).map(element => {
      const rect = element.getBoundingClientRect();
      return { x:rect.x, y:rect.y, width:rect.width, height:rect.height };
    });
    api.inputRects(rects);
  }

  function showError(message) {
    $('error').textContent = message || '';
    $('error').hidden = !message;
    if (message) {
      $('compact-text').textContent = message;
      setExpression('error');
    }
    updateRects();
  }

  function setPanel(open, focus = false) {
    $('panel').hidden = !open;
    $('compact-bubble').hidden = open;
    updateRects();
    if (open && focus) $('message').focus();
  }

  function setExpression(next) {
    const manual = $('expression').value;
    const expression = manual !== 'auto' ? manual : next;
    $('pet').dataset.expression = UI.EXPRESSIONS[expression] ? expression : 'idle';
    $('expression-label').textContent = UI.EXPRESSIONS[expression] || UI.EXPRESSIONS.idle;
  }

  function refreshExpression() {
    if (!$('error').hidden) return setExpression('error');
    if (speechPhase !== 'idle') return setExpression(({ recording:'listening', permission:'listening', transcribing:'transcribing', speaking:'speaking' })[speechPhase] || 'idle');
    if ([...requests.values()].some(item => ['pending', 'running', 'accepted', 'queued'].includes(item.status))) return setExpression('thinking');
    setExpression('idle');
  }

  function setVoiceStatus(message, phase = 'idle') {
    speechPhase = phase;
    $('voice-status').textContent = message || '';
    $('voice-feedback').hidden = !message;
    $('voice-feedback').classList.toggle('recording', phase === 'recording');
    $('speech-summary').textContent = message || '按需使用';
    $('cancel-voice').hidden = !['recording', 'permission', 'transcribing', 'speaking'].includes(phase);
    refreshExpression();
    updateRects();
  }

  function metadataView(metadata = {}) {
    metadata = metadata && typeof metadata === 'object' ? metadata : {};
    const details = node('details', 'observation');
    details.append(node('summary', '', '来源与数据限制'));
    details.append(node('p', '', `来源：${metadata.sourceLabel || (typeof metadata.source === 'string' ? metadata.source : metadata.source ? JSON.stringify(metadata.source) : '未知')} · 会话：${metadata.sessionId || '未知'}`));
    details.append(node('p', '', `采样：${UI.timestampLabel(metadata.sampledAt)}`));
    details.append(node('p', '', `partial：${metadata.partial === true ? '是' : metadata.partial === false ? '否' : '未知'} · synthetic：${metadata.synthetic === true ? '是（模拟）' : metadata.synthetic === false ? '否' : '未知'}`));
    const limitations = Array.isArray(metadata.limitations) ? metadata.limitations : metadata.limitations ? [metadata.limitations] : [];
    if (limitations.length) {
      const list = node('ul'); limitations.forEach(value => list.append(node('li', '', value))); details.append(list);
    } else details.append(node('p', '', '限制：未提供，不能据此视为完整或已验证。'));
    return details;
  }

  function metadataTags(metadata) {
    const row = node('div', 'observation-tags');
    UI.observationLabels(metadata).forEach(label => row.append(node('span', `badge ${label === '模拟数据' ? 'synthetic' : label.includes('过期') ? 'stale' : label.includes('完整') ? 'partial' : label.includes('未知') || label.includes('确认') ? 'unknown' : ''}`, label)));
    return row;
  }

  function cardView(card, inheritedMetadata) {
    const element = node('section', 'info-card');
    element.append(node('h3', '', card.title || '信息卡'));
    const fields = node('dl', 'card-fields');
    for (const field of Array.isArray(card.fields) ? card.fields : []) {
      fields.append(node('dt', '', field?.label || '未知字段'));
      const value = UI.valueLabel(field);
      fields.append(node('dd', value === '未知' ? 'unknown' : '', value));
    }
    element.append(fields);
    const metadata = { ...inheritedMetadata, ...card.metadata };
    element.append(metadataTags(metadata), metadataView(metadata));
    if (card.action || card.type === 'action-proposal') {
      const button = node('button', 'action-disabled', '执行暂不可用'); button.disabled = true; element.append(button);
    }
    return element;
  }

  function messageView(message) {
    const article = node('article', `message ${message.role === 'user' ? 'user' : 'assistant'} ${message.origin === 'proactive' ? 'proactive' : ''}`);
    article.dataset.messageId = message.id;
    const head = node('div', 'message-head');
    head.append(node('span', '', message.role === 'user' ? '你' : message.origin === 'proactive' ? '主动消息' : '桌宠'));
    if (message.metadata?.synthetic) head.append(node('span', 'badge synthetic', '模拟'));
    if (message.createdAt) {
      const date = new Date(message.createdAt);
      head.append(node('time', '', Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleTimeString('zh-CN', { hour12:false, hour:'2-digit', minute:'2-digit' })));
    }
    article.append(head, node('p', 'message-text', typeof message.text === 'string' ? message.text : '消息内容不可用'));
    if (message.role !== 'user') {
      article.append(metadataTags(message.metadata), metadataView(message.metadata));
      for (const card of Array.isArray(message.cards) ? message.cards : []) article.append(cardView(card, message.metadata));
    }
    return article;
  }

  function renderMessages() {
    const container = $('messages'); const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
    container.replaceChildren();
    const current = [...messages.values()].filter(message => UI.belongsToSession(message, state));
    if (!current.length) container.append(node('p', 'empty-message', state?.mode === 'real' ? '真实后端尚未接入。当前可检查前端状态，或切换模拟演示。' : '这是前端模拟演示。你可以输入消息，查看工具进度、数据来源和信息卡；角色与人格等待你的素材。'));
    for (const message of current) container.append(messageView(message));
    lastReply = current.filter(message => message.role === 'assistant').at(-1) || null;
    $('read-last').disabled = !lastReply;
    if (lastReply) $('compact-text').textContent = lastReply.text;
    else $('compact-text').textContent = state?.mode === 'real' ? '真实后端尚未接入，数据不会自动切回模拟。' : '前端模拟演示已就绪。单击打字，长按说话。';
    if (nearBottom) container.scrollTop = container.scrollHeight;
    updateRects();
  }

  function renderTasks() {
    const container = $('tasks'); container.replaceChildren();
    const taskItems = [...tools.values()].filter(item => UI.belongsToSession(item, state));
    for (const item of taskItems.slice(-6)) {
      const element = node('div');
      const row = node('div', `task ${item.tool.status}`);
      row.append(node('span', 'task-label', item.tool.label || item.tool.name || '读取信息'));
      row.append(node('span', 'task-state', ({ running:'进行中', completed:'完成', cancelled:'已取消', error:'失败' })[item.tool.status] || '等待'));
      if (item.tool.status === 'running') {
        const cancel = node('button', 'text-button', '取消');
        cancel.addEventListener('click', () => call(() => api.cancelRequest(item.requestId)));
        row.append(cancel);
      }
      element.append(row, metadataView(item.tool.metadata)); container.append(element);
    }
    container.hidden = !taskItems.length;
    refreshExpression(); updateRects();
  }

  function applyState(next) {
    if (!next || !Number.isSafeInteger(next.epoch) || typeof next.sessionId !== 'string') return;
    if (state && next.epoch < state.epoch) return;
    const switched = !state || next.epoch !== state.epoch || next.sessionId !== state.sessionId;
    if (switched) {
      cancelVoice('');
      messages = new Map(); tools.clear(); requests.clear();
      $('message').value = ''; $('draft-note').textContent = 'Enter 发送 · Shift + Enter 换行'; $('draft-note').classList.remove('synthetic');
    }
    state = next;
    if (Array.isArray(next.messages)) messages = new Map(next.messages.filter(item => UI.belongsToSession(item, next)).map(item => [item.id, item]));
    if (Array.isArray(next.pendingRequests)) {
      requests.clear();
      next.pendingRequests.forEach(item => {
        const request = typeof item === 'string' ? { id:item, status:'pending' } : item;
        requests.set(request.requestId || request.id, { ...request, status:request.status || 'pending' });
      });
    }
    $('mode').value = next.mode;
    $('mode-badge').textContent = next.synthetic ? '模拟模式' : '真实模式';
    $('mode-badge').classList.toggle('synthetic', next.synthetic === true);
    $('compact-mode').textContent = next.synthetic ? '模拟模式' : '真实模式 · 未接入';
    $('compact-mode').classList.toggle('synthetic', next.synthetic === true);
    $('dot').className = `dot ${next.connection?.state || 'unavailable'}`;
    $('connection').textContent = next.connection?.label || '连接状态未知';
    $('connection-note').textContent = next.connection?.reason || (next.mode === 'mock' ? '所有游戏信息和回复均为模拟，未连接游戏后端。' : '真实后端尚未接入。');
    $('send').disabled = next.mode !== 'mock' || next.connection?.state === 'disconnected';
    $('simulate-event').disabled = next.mode !== 'mock'; $('simulate-scenario').disabled = next.mode !== 'mock';
    $('message').placeholder = next.mode !== 'mock' ? '真实后端尚未接入，暂不能发送对话' : next.connection?.state === 'disconnected' ? '模拟连接已中断；可选择其他数据示例恢复' : '输入消息；长按桌宠也可以说话…';
    $('proactivity').value = String(next.proactivity ?? 80); renderProactivity();
    $('history-enabled').checked = next.historyEnabled === true;
    $('session-label').textContent = `会话 ${next.sessionId} · ${next.mode === 'mock' ? '模拟' : '真实后端待接入'}`;
    $('session-label').title = `来源：${next.connection?.backendId || '未知'} · epoch ${next.epoch}`;
    renderMessages(); renderTasks();
    if (next.storageWarning) showError(next.storageWarning);
  }

  function onRuntimeEvent(event) {
    if (!event || typeof event !== 'object') return;
    if (event.type === 'visibility' && event.visible === false) { cancelVoice('桌宠已隐藏，语音操作已停止', false); return; }
    if (event.type === 'stop-speech') { cancelVoice('语音操作已停止', false); return; }
    if (event.type === 'state') { applyState(event.state); return; }
    if (event.type === 'speech') { onSpeechEvent(event.state); return; }
    if (event.type === 'message' && UI.belongsToSession(event.message, state)) {
      messages.set(event.message.id, event.message); renderMessages();
      if (event.message.origin === 'proactive') {
        setExpression('notice'); clearTimeout(noticeTimer); noticeTimer = setTimeout(refreshExpression, 2500);
      }
    }
    if (event.type === 'tool' && UI.belongsToSession(event, state)) {
      tools.set(`${event.requestId}:${event.tool.id}`, event); renderTasks();
    }
    if (event.type === 'request' && UI.belongsToSession(event, state)) {
      requests.set(event.requestId, event);
      if (['cancelled', 'error'].includes(event.status)) {
        for (const [key, task] of tools) {
          if (task.requestId === event.requestId && task.tool.status === 'running') tools.set(key, { ...task, tool:{ ...task.tool, status:event.status } });
        }
        renderTasks();
      }
      if (event.status === 'error' && event.error) showError(event.error);
      refreshExpression();
    }
  }

  async function call(action) {
    try { return unwrap(await action()); }
    catch (error) { showError(error.message); return undefined; }
  }

  async function send(event) {
    event?.preventDefault();
    const text = $('message').value.trim();
    if (!text || !state || state.mode !== 'mock' || state.connection?.state === 'disconnected') return;
    const context = { sessionId:state.sessionId, epoch:state.epoch };
    $('message').value = ''; $('draft-note').textContent = 'Enter 发送 · Shift + Enter 换行'; $('draft-note').classList.remove('synthetic');
    showError('');
    try {
      const result = unwrap(await api.sendMessage({ text, conversationId:context.sessionId, generation:context.epoch }));
      if (!UI.belongsToSession(context, state)) return;
      refreshExpression();
    } catch (error) {
      if (!UI.belongsToSession(context, state)) return;
      if (!$('message').value) $('message').value = text;
      showError(error.message);
    }
  }

  function renderProactivity() {
    const value = `${$('proactivity').value}%`;
    $('proactivity-value').textContent = value; $('proactivity-summary').textContent = `主动性 ${value}`;
  }

  async function changeContext(action) {
    cancelVoice(''); showError('');
    const next = await call(action);
    if (next?.state) applyState(next.state);
    else if (next?.sessionId) applyState(next);
    else if (next) { const current = await call(() => api.getState()); if (current) applyState(current); }
  }

  function providerEntries(kind) {
    const value = speechInfo?.[kind];
    return Array.isArray(value) ? value : Array.isArray(value?.providers) ? value.providers : [];
  }

  async function refreshSpeechCapabilities() {
    try {
      speechInfo = unwrap(await api.speechCapabilities());
      for (const kind of ['stt', 'tts']) {
        const select = $(`${kind}-provider`); const selected = select.value;
        const entries = providerEntries(kind);
        if (entries.length) {
          select.replaceChildren();
          for (const provider of entries) {
            const label = provider.label || ({ openai:kind === 'stt' ? '云端转写' : '云端 TTS', azure:'Azure TTS', edge:'Edge TTS', system:'系统语音', mock:kind === 'stt' ? '模拟转写（非实际识别）' : '模拟播报（无实际音频）' })[provider.id] || provider.id;
            const option = node('option', '', `${label}${provider.available === false && provider.id !== 'mock' ? ' · 未就绪' : ''}`);
            option.value = provider.id; select.append(option);
          }
          if (entries.some(item => item.id === selected)) select.value = selected;
          else select.value = entries.find(item => item.available && item.id !== 'mock')?.id || entries.find(item => item.id !== 'mock')?.id || entries[0].id;
        }
      }
      updateProviderNotes();
    } catch (error) { $('stt-note').textContent = `语音服务状态不可用：${error.message}`; }
  }

  function updateProviderNotes() {
    const stt = providerEntries('stt').find(item => item.id === $('stt-provider').value);
    const tts = providerEntries('tts').find(item => item.id === $('tts-provider').value);
    $('stt-note').textContent = $('stt-provider').value === 'mock' ? '模拟转写不会识别实际录音。结果会明确标记为模拟，先进入草稿。' : stt?.available === false ? (stt.reason || '转写服务尚未配置。') : '按住录音，松开转写；识别结果先进入可编辑草稿。';
    $('tts-note').textContent = $('tts-provider').value === 'mock' ? '仅演示播报状态，不会播放实际音频。' : tts?.available === false ? (tts.reason || '播报服务尚未配置。') : '手动点击“读回复”播放；可以随时停止。';
  }

  function stopPlayer() {
    if (player) { player.pause(); player.removeAttribute('src'); player.load(); player = null; }
    if (playerUrl) { URL.revokeObjectURL(playerUrl); playerUrl = null; }
  }

  function cancelVoice(message = '语音操作已取消', notifyMain = true) {
    voiceFence.invalidate();
    if (recording) {
      recording.cancelled = true; recording.stopRequested = true;
      clearTimeout(recording.timer);
      recording.stream?.getTracks().forEach(track => track.stop());
      if (recording.recorder?.state === 'recording') recording.recorder.stop();
      recording = null;
    }
    if (speechOperation) api.cancelSpeechOperation(speechOperation.id).catch(() => {});
    speechOperation = null;
    stopPlayer(); if (notifyMain) api.stopSpeech?.().catch(() => {});
    setVoiceStatus(message);
  }

  function speechContext(id) {
    return { operationId:id, generation:state.epoch, conversationId:state.sessionId };
  }

  function speechResultCurrent(result, operation) {
    return speechOperation === operation && voiceFence.accepts(operation.token) && state?.epoch === operation.context.generation && state?.sessionId === operation.context.conversationId &&
      (!result.operationId || result.operationId === operation.id) &&
      (result.generation === undefined || result.generation === operation.context.generation) &&
      (!result.conversationId || result.conversationId === operation.context.conversationId);
  }

  async function beginRecording() {
    if (!state || recording || speechPhase === 'transcribing') return;
    cancelVoice(''); showError('');
    const provider = $('stt-provider').value;
    const capability = providerEntries('stt').find(item => item.id === provider);
    if (capability?.available === false) { showError(capability.reason || '语音转写服务未配置，请选择可用服务。'); setVoiceStatus('转写服务未就绪'); return; }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder !== 'function') { showError('当前环境无法录音。'); return; }
    const operation = { id:operationId('stt'), token:voiceFence.capture(), context:speechContext(''), provider, cancelled:false, stopRequested:false, chunks:[], totalBytes:0 };
    operation.context.operationId = operation.id;
    recording = operation;
    setVoiceStatus('正在请求麦克风权限…松开可取消', 'permission');
    try {
      if (api.microphonePermission) {
        const permission = unwrap(await api.microphonePermission());
        if (recording !== operation || operation.cancelled || operation.stopRequested || !voiceFence.accepts(operation.token)) return;
        if (['denied', 'restricted'].includes(permission.state)) { const error = new Error('麦克风权限被拒绝。'); error.name = 'NotAllowedError'; throw error; }
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio:true, video:false });
      if (recording !== operation || operation.cancelled || operation.stopRequested || !voiceFence.accepts(operation.token)) { stream.getTracks().forEach(track => track.stop()); return; }
      operation.stream = stream;
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      operation.recorder = recorder;
      recorder.addEventListener('dataavailable', event => {
        if (!event.data.size || operation.cancelled) return;
        operation.totalBytes += event.data.size;
        if (operation.totalBytes > 20 * 1024 * 1024) { cancelVoice('录音过大，已取消。请缩短后重试。'); return; }
        operation.chunks.push(event.data);
      });
      recorder.addEventListener('error', () => { if (recording === operation) { cancelVoice('录音失败'); showError('无法完成录音，请检查麦克风后重试。'); } });
      recorder.addEventListener('stop', () => finishTranscription(operation));
      recorder.start(250);
      operation.timer = setTimeout(() => stopRecording(), 60_000);
      setVoiceStatus(provider === 'mock' ? '正在录音 · 模拟转写不会识别实际内容' : '正在聆听…松开结束，Esc 取消', 'recording');
    } catch (error) {
      operation.cancelled = true; clearTimeout(operation.timer);
      operation.stream?.getTracks().forEach(track => track.stop());
      if (operation.recorder?.state === 'recording') operation.recorder.stop();
      if (recording !== operation || !voiceFence.accepts(operation.token)) return;
      recording = null; setVoiceStatus('麦克风不可用');
      const message = ['NotAllowedError', 'PermissionDeniedError'].includes(error.name) ? '麦克风权限被拒绝。可以在系统隐私设置中允许此应用使用麦克风。' : error.name === 'NotFoundError' ? '未找到可用麦克风。' : `录音失败：${error.message}`;
      showError(message);
    }
  }

  function stopRecording(cancelled = false) {
    const operation = recording;
    if (!operation) return;
    operation.stopRequested = true;
    if (cancelled || !operation.recorder) { cancelVoice(cancelled ? '已取消录音' : '已松开，未开始录音'); return; }
    clearTimeout(operation.timer);
    if (operation.recorder.state === 'recording') operation.recorder.stop();
    operation.stream?.getTracks().forEach(track => track.stop());
  }

  async function finishTranscription(operation) {
    clearTimeout(operation.timer); operation.stream?.getTracks().forEach(track => track.stop());
    if (operation.cancelled || !voiceFence.accepts(operation.token) || recording !== operation) return;
    recording = null;
    if (!operation.chunks.length || operation.totalBytes === 0) { setVoiceStatus('未录到声音，请重试。'); return; }
    const blob = new Blob(operation.chunks, { type:operation.recorder.mimeType || operation.chunks[0].type });
    if (blob.size < 64) { setVoiceStatus('录音太短，请重试。'); return; }
    speechOperation = operation;
    setVoiceStatus(operation.provider === 'mock' ? '模拟转写中（非实际识别）…' : '正在转为文字…', 'transcribing');
    try {
      const audio = await blob.arrayBuffer();
      if (!speechResultCurrent({}, operation)) return;
      const result = unwrap(await api.transcribe({ ...operation.context, provider:operation.provider, audio, mimeType:blob.type, language:'zh' }));
      if (!speechResultCurrent(result, operation)) return;
      if (typeof result.text !== 'string' || !result.text.trim()) throw new Error('转写服务未返回文字。');
      if ($('message').value && !$('message').value.endsWith('\n')) $('message').value += '\n';
      $('message').value = ($('message').value + result.text).slice(0, 4000);
      const synthetic = result.synthetic === true;
      $('draft-note').textContent = synthetic ? '模拟转写 · 未识别实际录音，请检查后再发送' : '转写已放入草稿 · 请检查后再发送';
      $('draft-note').classList.toggle('synthetic', synthetic);
      setVoiceStatus(synthetic ? '模拟转写完成 · 没有识别实际录音' : '转写完成，等待你确认发送');
      setPanel(true, true);
    } catch (error) {
      if (!speechResultCurrent({}, operation)) return;
      setVoiceStatus('转写失败'); showError(error.message);
    } finally { if (speechOperation === operation) speechOperation = null; }
  }

  async function speakLast() {
    if (!lastReply || !state) return;
    const reply = lastReply;
    cancelVoice(''); showError('');
    const operation = { id:operationId('tts'), token:voiceFence.capture(), context:speechContext('') };
    operation.context.operationId = operation.id; speechOperation = operation;
    setVoiceStatus('正在准备播报…', 'speaking');
    try {
      const result = unwrap(await api.speak({ ...operation.context, text:reply.text, provider:$('tts-provider').value }));
      if (!speechResultCurrent(result, operation)) return;
      if (result.playback === 'renderer') {
        const bytes = result.audio instanceof ArrayBuffer ? result.audio : result.audio?.buffer instanceof ArrayBuffer ? result.audio.buffer : null;
        if (!bytes || !bytes.byteLength) throw new Error('语音服务未返回音频。');
        playerUrl = URL.createObjectURL(new Blob([bytes], { type:result.mimeType || 'audio/mpeg' }));
        player = new Audio(playerUrl);
        player.addEventListener('ended', () => { if (speechOperation === operation) { stopPlayer(); speechOperation = null; setVoiceStatus('播报完成'); } });
        player.addEventListener('error', () => { if (speechOperation === operation) { stopPlayer(); speechOperation = null; setVoiceStatus('播放失败'); showError('无法播放返回的音频，请检查语音服务。'); } });
        await player.play();
        if (!speechResultCurrent(result, operation)) { stopPlayer(); return; }
        setVoiceStatus('正在播报…', 'speaking');
      } else if (result.playback === 'none') { speechOperation = null; setVoiceStatus(result.synthetic ? '模拟播报完成 · 未播放实际音频' : '未播放音频'); }
      else setVoiceStatus('正在使用系统语音播报…', 'speaking');
    } catch (error) {
      if (!speechResultCurrent({}, operation)) return;
      speechOperation = null; stopPlayer(); setVoiceStatus('播报失败'); showError(error.message);
    }
  }

  function onSpeechEvent(event) {
    if (!event || !speechOperation) return;
    const operation = speechOperation;
    if (event.operationId && event.operationId !== operation.id) return;
    if (!speechResultCurrent(event, operation)) return;
    if (['finished', 'stopped', 'cancelled', 'error'].includes(event.state)) {
      speechOperation = null; stopPlayer();
      setVoiceStatus(event.state === 'finished' ? '播报完成' : event.state === 'error' ? '播报失败' : '播报已停止');
      if (event.state === 'error') showError(event.message || '语音服务失败。');
    }
  }

  async function refreshMemories() {
    const result = await call(() => api.getMemories());
    if (!result) return;
    const entries = Array.isArray(result.entries) ? result.entries : [];
    const list = $('memory-list'); list.replaceChildren();
    if (!entries.length) list.append(node('p', 'saved-empty', '尚未明确保存记忆。'));
    for (const entry of entries) {
      const row = node('div', 'saved-entry'); row.append(node('p', '', entry.text || '空记忆'));
      const remove = node('button', 'text-button danger', '删除');
      remove.addEventListener('click', async () => { const result = await call(() => api.deleteMemory(entry.id)); if (result !== undefined) refreshMemories(); });
      row.append(remove); list.append(row);
    }
    updateRects();
  }

  async function showHistory() {
    const result = await call(() => api.getHistory());
    if (!result) return;
    const list = $('history-list'); list.hidden = false; list.replaceChildren();
    const history = Array.isArray(result.messages) ? result.messages : [];
    if (!history.length) list.append(node('p', 'saved-empty', '没有保存的聊天历史。'));
    for (const message of history) {
      const row = node('div', 'saved-entry');
      row.append(node('p', '', `${message.metadata?.synthetic ? '【模拟】' : ''}${message.role === 'user' ? '你' : '桌宠'} · ${message.sessionId || '会话未知'}\n${message.text || ''}`)); list.append(row);
    }
    updateRects();
  }

  function startDrag() { dragReady = api.dragStart(); }
  function moveDrag() {
    if (dragMovePending) return;
    dragMovePending = true;
    requestAnimationFrame(async () => { try { await dragReady; if (gesture.mode === 'dragging') await api.dragMove(); } finally { dragMovePending = false; } });
  }

  function endGesture(event, cancelled = false) {
    clearTimeout(holdTimer);
    const action = gesture.end(event.pointerId, cancelled);
    if (action === 'drag-end') dragReady.then(() => api.dragEnd()).catch(() => {});
    if (action === 'voice-stop') stopRecording();
    if (action === 'voice-cancel') stopRecording(true);
    if (action === 'click') setPanel($('panel').hidden, true);
    if ($('pet').hasPointerCapture?.(event.pointerId)) $('pet').releasePointerCapture(event.pointerId);
  }

  function bindEvents() {
    Object.entries(UI.EXPRESSIONS).forEach(([value, label]) => { const option = node('option', '', label); option.value = value; $('expression').append(option); });
    $('expression').addEventListener('change', refreshExpression);
    $('chat-form').addEventListener('submit', send);
    $('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
    $('collapse').addEventListener('click', () => setPanel(false));
    $('open-panel').addEventListener('click', () => setPanel(true, true));
    $('show-settings').addEventListener('click', () => call(() => api.openSettings()));
    $('quit').addEventListener('click', () => api.quit());
    $('mode').addEventListener('change', () => changeContext(() => api.setMode($('mode').value)));
    $('new-conversation').addEventListener('click', () => changeContext(() => api.newConversation()));
    $('proactivity').addEventListener('input', renderProactivity);
    $('proactivity').addEventListener('change', () => call(() => api.setProactivity(Number($('proactivity').value))));
    $('simulate-event').addEventListener('click', () => call(() => api.simulateEvent()));
    $('simulate-scenario').addEventListener('click', () => call(() => api.simulateEvent($('scenario').value)));
    $('history-enabled').addEventListener('change', () => call(() => api.setHistoryEnabled($('history-enabled').checked)));
    $('show-history').addEventListener('click', showHistory);
    $('clear-history').addEventListener('click', async () => { const result = await call(() => api.clearHistory()); if (result !== undefined) showHistory(); });
    $('refresh-memories').addEventListener('click', refreshMemories);
    $('save-memory').addEventListener('click', async () => {
      const text = $('memory-text').value.trim(); if (!text) return;
      const result = await call(() => api.saveMemory({ text }));
      if (result !== undefined) { $('memory-text').value = ''; refreshMemories(); }
    });
    $('cancel-voice').addEventListener('click', () => cancelVoice());
    $('read-last').addEventListener('click', speakLast);
    $('stop-speech').addEventListener('click', () => cancelVoice('播报已停止'));
    ['stt-provider', 'tts-provider'].forEach(id => $(id).addEventListener('change', () => { cancelVoice('语音服务已切换'); updateProviderNotes(); }));
    $('pet').addEventListener('contextmenu', event => { event.preventDefault(); clearTimeout(holdTimer); call(() => api.showContextMenu()); });
    $('pet').addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      gesture.begin({ id:event.pointerId, x:event.screenX, y:event.screenY, time:performance.now() });
      $('pet').setPointerCapture(event.pointerId);
      holdTimer = setTimeout(() => { if (gesture.hold(performance.now())) beginRecording(); }, gesture.holdMs + 5);
    });
    $('pet').addEventListener('pointermove', event => {
      const action = gesture.move({ id:event.pointerId, x:event.screenX, y:event.screenY });
      if (action) clearTimeout(holdTimer);
      if (action === 'drag-start') { startDrag(); moveDrag(); }
      if (action === 'drag-move') moveDrag();
    });
    $('pet').addEventListener('pointerup', event => endGesture(event));
    $('pet').addEventListener('pointercancel', event => endGesture(event, true));
    $('pet').addEventListener('lostpointercapture', event => { if (gesture.mode !== 'idle') endGesture(event, true); });
    $('pet').addEventListener('keydown', event => { if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) { event.preventDefault(); setPanel($('panel').hidden, true); } });
    const recordButton = $('record-button');
    recordButton.addEventListener('pointerdown', event => { if (event.button !== 0) return; event.preventDefault(); recordButton.setPointerCapture(event.pointerId); beginRecording(); });
    recordButton.addEventListener('pointerup', () => stopRecording());
    recordButton.addEventListener('pointercancel', () => stopRecording(true));
    recordButton.addEventListener('keydown', event => { if (event.key === ' ' && !event.repeat) { event.preventDefault(); beginRecording(); } });
    recordButton.addEventListener('keyup', event => { if (event.key === ' ') { event.preventDefault(); stopRecording(); } });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { clearTimeout(holdTimer); cancelVoice(); } });
    document.querySelectorAll('details').forEach(element => element.addEventListener('toggle', updateRects));
    window.addEventListener('resize', updateRects);
    window.addEventListener('blur', () => { clearTimeout(holdTimer); if (recording) stopRecording(true); });
    window.addEventListener('beforeunload', () => { cancelVoice(''); unsubscribe?.(); });
    new ResizeObserver(updateRects).observe(document.body);
  }

  let unsubscribe;
  if (!api || !UI) {
    $('connection').textContent = '桌宠桥接未就绪';
    $('connection-note').textContent = '请从 Electron 应用打开桌宠。';
    $('compact-text').textContent = '桌宠桥接未就绪，请从应用打开。';
    $('open-panel').addEventListener('click', () => { $('panel').hidden = false; $('compact-bubble').hidden = true; });
    return;
  }
  bindEvents();
  unsubscribe = api.subscribe(onRuntimeEvent);
  call(() => api.getState()).then(value => { if (value) applyState(value); });
  refreshSpeechCapabilities();
  refreshMemories();
  updateRects();
})();
