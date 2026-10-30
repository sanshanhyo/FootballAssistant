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
  let selectedMessageId = null;
  let followLatest = true;
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
  let composing = false;
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
  const preferences = () => ({ expression:'auto', sttProvider:'openai', ttsProvider:'system', ...state?.preferences });

  function updateRects() {
    if (!api?.inputRects) return;
    const rects = [$('pet'), $('compact-bubble'), $('chat-form'), $('draft-note')].filter(item => item && !item.hidden).map(element => {
      const rect = element.getBoundingClientRect();
      return { x:rect.x, y:rect.y, width:rect.width, height:rect.height };
    });
    api.inputRects(rects);
  }

  function showError(message) {
    $('error').textContent = message || '';
    $('error').hidden = !message;
    refreshExpression(); updateRects();
  }

  function resizeComposer() {
    const textarea = $('message');
    textarea.style.height = '30px';
    textarea.style.height = `${Math.min(66, Math.max(30, textarea.scrollHeight))}px`;
    updateSendAvailability(); updateRects();
  }

  function updateSendAvailability() {
    $('send').disabled = !state || state.mode !== 'mock' || state.connection?.state === 'disconnected' || !$('message').value.trim();
  }

  function setComposer(open, focus = false) {
    $('chat-form').hidden = !open;
    $('pet').setAttribute('aria-expanded', String(open));
    $('draft-note').hidden = !open;
    if (open) resizeComposer();
    updateRects();
    if (open && focus) $('message').focus();
  }

  function resetDraftNote() {
    $('draft-note').textContent = 'Enter 发送 · Shift + Enter 换行';
    $('draft-note').classList.remove('synthetic');
  }

  function setExpression(next) {
    const manual = preferences().expression;
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
    $('cancel-voice').hidden = !['recording', 'permission', 'transcribing', 'speaking'].includes(phase);
    $('stop-speech').hidden = phase !== 'speaking';
    refreshExpression(); updateRects();
  }

  function metadataView(metadata = {}) {
    metadata = metadata && typeof metadata === 'object' ? metadata : {};
    const details = node('details', 'observation');
    details.append(node('summary', '', '来源详情'));
    details.append(node('p', '', `来源：${metadata.sourceLabel || (typeof metadata.source === 'string' ? metadata.source : metadata.source ? JSON.stringify(metadata.source) : '未知')} · 会话：${metadata.sessionId || '未知'}`));
    details.append(node('p', '', `采样：${UI.timestampLabel(metadata.sampledAt)}`));
    details.append(node('p', '', `partial：${metadata.partial === true ? '是' : metadata.partial === false ? '否' : '未知'} · synthetic：${metadata.synthetic === true ? '是（模拟）' : metadata.synthetic === false ? '否' : '未知'}`));
    const limitations = Array.isArray(metadata.limitations) ? metadata.limitations : metadata.limitations ? [metadata.limitations] : [];
    if (limitations.length) {
      const list = node('ul'); limitations.forEach(value => list.append(node('li', '', value))); details.append(list);
    } else details.append(node('p', '', '限制：未提供，不能据此视为完整或已验证。'));
    return details;
  }

  function badge(label, kind = '') { return node('span', `badge ${kind}`, label); }
  function metadataTags(metadata) {
    const row = node('div', 'observation-tags');
    UI.observationLabels(metadata).forEach(label => row.append(badge(label, label === '模拟数据' ? 'synthetic' : label.includes('过期') ? 'stale' : label.includes('完整') ? 'partial' : 'unknown')));
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

  function currentReplies() { return [...messages.values()].filter(message => message.role === 'assistant' && UI.belongsToSession(message, state)); }

  function renderBubble() {
    const replies = currentReplies();
    if (followLatest || !replies.some(item => item.id === selectedMessageId)) selectedMessageId = replies.at(-1)?.id || null;
    lastReply = replies.find(item => item.id === selectedMessageId) || null;
    $('read-last').disabled = !lastReply;
    $('compact-text').textContent = lastReply?.text || (state?.mode === 'real' ? '真实后端尚未接入。可以从设置切换为模拟演示。' : state?.connection?.state === 'disconnected' ? '模拟连接已中断，等待恢复。' : '单击桌宠输入消息，长按说话。');
    $('message-origin').textContent = lastReply?.origin === 'proactive' ? '主动消息' : '桌宠';
    const badges = $('message-badges'); badges.replaceChildren();
    badges.append(badge(state?.synthetic === true ? '模拟模式' : state?.mode === 'real' ? '真实 · 未接入' : '状态待确认', state?.synthetic ? 'synthetic' : 'unknown'));
    if (state?.connection?.state === 'disconnected' || state?.connection?.state === 'unavailable') badges.append(badge('未连接', 'disconnected'));
    const metadata = lastReply?.metadata;
    if (metadata?.freshness === 'stale') badges.append(badge('已过期', 'stale'));
    else if (metadata && metadata.freshness !== 'current') badges.append(badge('时效未知', 'unknown'));
    if (metadata?.partial === true) badges.append(badge('数据不完整', 'partial'));
    const navigation = $('message-navigation'); navigation.hidden = replies.length < 2;
    const index = replies.findIndex(item => item.id === selectedMessageId);
    $('message-count').textContent = `${index + 1} / ${replies.length}`;
    $('previous-message').disabled = index <= 0;
    $('next-message').disabled = index < 0 || index >= replies.length - 1;
    const detail = $('message-detail-content'); detail.replaceChildren();
    $('message-details').hidden = !lastReply;
    if (lastReply) {
      detail.append(metadataTags(metadata), metadataView(metadata));
      for (const card of Array.isArray(lastReply.cards) ? lastReply.cards : []) detail.append(cardView(card, metadata));
    }
    updateRects();
  }

  function navigateMessage(delta) {
    const replies = currentReplies();
    const current = replies.findIndex(item => item.id === selectedMessageId);
    const next = replies[current + delta];
    if (!next) return;
    selectedMessageId = next.id; followLatest = current + delta === replies.length - 1;
    $('message-details').open = false;
    renderBubble();
  }

  function renderTasks() {
    const container = $('task-list'); container.replaceChildren();
    const taskItems = [...tools.values()].filter(item => UI.belongsToSession(item, state));
    const active = taskItems.filter(item => item.tool.status === 'running');
    $('task-summary').textContent = active.length ? `${active[0].tool.label || '正在读取信息'}${active.length > 1 ? ` · ${active.length} 项进行中` : ''}` : taskItems.length ? '最近处理进度' : '暂无处理任务';
    for (const item of taskItems.slice(-6)) {
      const element = node('div'); const row = node('div', `task ${item.tool.status}`);
      row.append(node('span', 'task-label', item.tool.label || item.tool.name || '读取信息'));
      row.append(node('span', 'task-state', ({ running:'进行中', completed:'完成', cancelled:'已取消', error:'失败' })[item.tool.status] || '等待'));
      if (item.tool.status === 'running') {
        const cancel = node('button', 'quiet-button', '取消');
        cancel.addEventListener('click', () => call(() => api.cancelRequest(item.requestId))); row.append(cancel);
      }
      element.append(row, metadataView(item.tool.metadata)); container.append(element);
    }
    $('tasks').hidden = !taskItems.length;
    refreshExpression(); updateRects();
  }

  function applyState(next) {
    if (!next || !Number.isSafeInteger(next.epoch) || typeof next.sessionId !== 'string') return;
    if (state && next.epoch < state.epoch) return;
    const switched = !state || next.epoch !== state.epoch || next.sessionId !== state.sessionId;
    const oldPreferences = preferences();
    const providersChanged = next.preferences && (next.preferences.sttProvider !== oldPreferences.sttProvider || next.preferences.ttsProvider !== oldPreferences.ttsProvider);
    if (switched || providersChanged) cancelVoice(providersChanged && state ? '语音服务已切换' : '');
    if (switched) {
      messages = new Map(); tools.clear(); requests.clear(); selectedMessageId = null; followLatest = true;
      $('message').value = ''; resetDraftNote(); resizeComposer(); $('message-details').open = false;
    }
    state = next;
    if (Array.isArray(next.messages)) messages = new Map(next.messages.filter(item => UI.belongsToSession(item, next)).map(item => [item.id, item]));
    if (Array.isArray(next.tools)) { tools.clear(); next.tools.forEach(item => { if (UI.belongsToSession(item, next)) tools.set(`${item.requestId}:${item.tool.id}`, item); }); }
    if (Array.isArray(next.pendingRequests)) {
      requests.clear(); next.pendingRequests.forEach(item => {
        const request = typeof item === 'string' ? { id:item, status:'pending' } : item;
        requests.set(request.requestId || request.id, { ...request, status:request.status || 'pending' });
      });
    }
    updateSendAvailability();
    $('message').placeholder = next.mode !== 'mock' ? '后端未接入，暂不能发送' : next.connection?.state === 'disconnected' ? '连接已中断' : '输入消息…';
    renderBubble(); renderTasks();
    if (next.storageWarning) showError(next.storageWarning);
  }

  function onRuntimeEvent(event) {
    if (!event || typeof event !== 'object') return;
    if (event.type === 'visibility' && event.visible === false) { cancelVoice('桌宠已隐藏，语音操作已停止', false); return; }
    if (event.type === 'stop-speech') { cancelVoice('语音操作已停止', false); return; }
    if (event.type === 'composer') { setComposer(event.open !== false, true); return; }
    if (event.type === 'state') { applyState(event.state); return; }
    if (event.type === 'speech') { onSpeechEvent(event.state); return; }
    if (event.type === 'message' && UI.belongsToSession(event.message, state)) {
      messages.set(event.message.id, event.message); renderBubble();
      if (event.message.origin === 'proactive') { setExpression('notice'); clearTimeout(noticeTimer); noticeTimer = setTimeout(refreshExpression, 2500); }
    }
    if (event.type === 'tool' && UI.belongsToSession(event, state)) { tools.set(`${event.requestId}:${event.tool.id}`, event); renderTasks(); }
    if (event.type === 'request' && UI.belongsToSession(event, state)) {
      requests.set(event.requestId, event);
      if (['cancelled', 'error'].includes(event.status)) {
        for (const [key, task] of tools) if (task.requestId === event.requestId && task.tool.status === 'running') tools.set(key, { ...task, tool:{ ...task.tool, status:event.status } });
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
    $('message').value = ''; resetDraftNote(); resizeComposer(); followLatest = true;
    showError('');
    try {
      unwrap(await api.sendMessage({ text, conversationId:context.sessionId, generation:context.epoch }));
      if (!UI.belongsToSession(context, state)) return;
      refreshExpression();
    } catch (error) {
      if (!UI.belongsToSession(context, state)) return;
      if (!$('message').value) $('message').value = text;
      resizeComposer(); showError(error.message);
    }
  }

  function providerEntries(kind) { return Array.isArray(speechInfo?.[kind]) ? speechInfo[kind] : []; }
  async function refreshSpeechCapabilities() {
    try { speechInfo = unwrap(await api.speechCapabilities()); }
    catch { speechInfo = null; }
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
    const provider = preferences().sttProvider;
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
      setComposer(true, true);
      resizeComposer();
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
      const result = unwrap(await api.speak({ ...operation.context, text:reply.text, provider:preferences().ttsProvider }));
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
    if (action === 'click') setComposer($('chat-form').hidden, true);
    if ($('pet').hasPointerCapture?.(event.pointerId)) $('pet').releasePointerCapture(event.pointerId);
  }

  function bindEvents() {
    $('chat-form').addEventListener('submit', send);
    $('message').addEventListener('compositionstart', () => { composing = true; });
    $('message').addEventListener('compositionend', () => { composing = false; });
    $('message').addEventListener('keydown', event => { if (UI.shouldSubmitText(event, composing)) { event.preventDefault(); send(); } });
    $('message').addEventListener('input', resizeComposer);
    $('previous-message').addEventListener('click', () => navigateMessage(-1));
    $('next-message').addEventListener('click', () => navigateMessage(1));
    $('cancel-voice').addEventListener('click', () => cancelVoice());
    $('read-last').addEventListener('click', speakLast);
    $('stop-speech').addEventListener('click', () => cancelVoice('播报已停止'));
    $('pet').addEventListener('contextmenu', event => { event.preventDefault(); clearTimeout(holdTimer); call(() => api.showContextMenu()); });
    $('pet').addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault(); gesture.begin({ id:event.pointerId, x:event.screenX, y:event.screenY, time:performance.now() });
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
    $('pet').addEventListener('keydown', event => { if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) { event.preventDefault(); setComposer($('chat-form').hidden, true); } });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { clearTimeout(holdTimer); cancelVoice(''); setComposer(false); } });
    document.addEventListener('toggle', updateRects, true);
    window.addEventListener('resize', () => { resizeComposer(); updateRects(); });
    window.addEventListener('blur', () => { clearTimeout(holdTimer); if (recording) stopRecording(true); });
    window.addEventListener('beforeunload', () => { cancelVoice(''); unsubscribe?.(); });
    const observer = new ResizeObserver(updateRects);
    [$('compact-bubble'), $('chat-form')].forEach(element => observer.observe(element));
  }

  let unsubscribe;
  if (!api || !UI) { $('compact-text').textContent = '桌宠桥接未就绪，请从应用打开。'; return; }
  bindEvents();
  unsubscribe = api.subscribe(onRuntimeEvent);
  call(() => api.getState()).then(value => { if (value) applyState(value); });
  refreshSpeechCapabilities();
  updateRects();
})();
