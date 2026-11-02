'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const api = window.companion;
  const UI = window.CompanionUI;
  const Bubbles = window.CompanionBubbles;
  const Scenes = window.CompanionScenes;
  const motion = window.CompanionMotion?.bind({ image: $('character-image'), media: window.matchMedia?.('(prefers-reduced-motion: reduce)') });
  let gameStatus = { state: 'unknown' };
  let gamePollTimer;
  let sceneClosed = false;
  const failedScenes = new Set();
  let state = null;
  let messages = new Map();
  const tools = new Map();
  const requests = new Map();
  let lastReply = null;
  let blockedReplyId = null;
  let noticeTimer;
  let speechInfo = null;
  let speechPreferences = { enabled: false };
  const systemSpeechResults = new Map();
  const systemSpeechWaiters = new Map();
  const queuedPlayback = window.FootballTtsPlayback?.createPlayback();
  let recording = null;
  let speechOperation = null;
  let player = null;
  let playerUrl = null;
  let speechPhase = 'idle';
  let holdTimer;
  let dragReady = Promise.resolve();
  let dragMovePending = false;
  let composing = false;
  const gesture = UI?.createGesture();
  const voiceFence = UI?.createFence();
  const operationId = prefix => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  const unwrap = result => {
    if (!result?.ok) throw new Error(result?.error || '桌宠请求失败，请重试。');
    return result.value;
  };
  const ttsQueue = window.FootballTtsQueue?.createTtsQueue({
    synthesize: async payload => {
      if (!speechPreferences.enabled || payload.generation !== state?.epoch || payload.conversationId !== state?.sessionId) throw Error('cancelled');
      return unwrap(await api.speak(payload));
    },
    play: (result, signal) => {
      if (result.generation !== state?.epoch || result.conversationId !== state?.sessionId || signal.aborted) return Promise.reject(Error('cancelled'));
      setVoiceStatus('正在播报…', 'speaking');
      if (result.playback === 'renderer') return queuedPlayback.play(result, signal);
      if (result.playback !== 'system') return Promise.resolve();
      return new Promise((resolve, reject) => {
        const finish = value => { signal.removeEventListener('abort', abort); systemSpeechWaiters.delete(result.operationId); systemSpeechResults.delete(result.operationId); value === 'finished' ? resolve() : reject(Error('cancelled')); };
        const abort = () => finish('cancelled');
        if (systemSpeechResults.has(result.operationId)) { finish(systemSpeechResults.get(result.operationId)); return; }
        systemSpeechWaiters.set(result.operationId, finish); signal.addEventListener('abort', abort, { once: true });
      });
    },
    cancel: id => api.cancelSpeechOperation(id), stopPlayback: () => queuedPlayback?.stop(),
  });
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };
  const preferences = () => ({ expression:'auto', sttProvider:'local-whisper', ttsProvider:'system', ...state?.preferences });

  const bubbleQueue = Bubbles?.createQueue({ onChange: part => {
    $('compact-text').textContent = part.text;
    $('compact-bubble').hidden = part.hidden || !part.text;
    $('bubble-progress').hidden = part.count < 2;
    $('bubble-progress').textContent = part.count > 1 ? `${part.index + 1} / ${part.count}` : '';
    $('bubble-content').dataset.hasNext = String(part.hasNext);
    $('compact-bubble').setAttribute('aria-label', part.hasNext ? `对白 ${part.index + 1} / ${part.count}，点击或按回车查看下一段` : '对白最后一段');
    $('compact-bubble').setAttribute('aria-disabled', String(!part.hasNext));
    $('compact-text').title = '';
    $('bubble-body').scrollTop = 0;
    refreshExpression();
    updateRects();
  } });

  function updateRects() {
    if (!api?.inputRects) return;
    // The full bubble is clickable; hidden ancestors must never leave a stale input region.
    const rects = [$('pet'), $('compact-bubble'), $('chat-form'), $('interaction-feedback'), $('draft-note')].filter(item => item && !item.hidden && item.getClientRects().length).map(element => {
      const rect = element.getBoundingClientRect();
      return { x:rect.x, y:rect.y, width:rect.width, height:rect.height };
    });
    api.inputRects(rects);
  }

  function showError(message) {
    $('error').textContent = message || '';
    $('error').hidden = !message;
    if (message) setComposer(true);
    updateInteractionFeedback();
    refreshExpression(); updateRects();
  }

  function updateInteractionFeedback() {
    const active = speechPhase !== 'idle';
    $('voice-status').hidden = !active;
    $('cancel-voice').hidden = !active;
    $('interaction-feedback').hidden = !active && $('error').hidden;
  }

  function resizeComposer() {
    const textarea = $('message');
    textarea.style.height = '30px';
    textarea.style.height = `${Math.min(66, Math.max(30, textarea.scrollHeight))}px`;
    updateSendAvailability(); updateRects();
  }

  function updateSendAvailability() {
    $('send').disabled = !state || !state.canSend || state.connection?.state === 'disconnected' || !$('message').value.trim();
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
    motion?.setState($('pet').dataset.expression);
  }

  function refreshExpression() {
    if (!$('error').hidden) return setExpression('error');
    if (speechPhase !== 'idle') return setExpression(({ recording:'listening', permission:'listening', transcribing:'transcribing', speaking:'speaking' })[speechPhase] || 'idle');
    if ([...requests.values()].some(item => ['pending', 'running', 'accepted', 'queued'].includes(item.status))) return setExpression('thinking');
    if (!$('compact-bubble').hidden) return setExpression('speaking');
    setExpression('idle');
  }

  function setVoiceStatus(message, phase = 'idle') {
    speechPhase = phase;
    $('voice-status').textContent = message || '';
    if (['permission', 'recording', 'transcribing'].includes(phase)) setComposer(true);
    updateInteractionFeedback();
    refreshExpression(); updateRects();
  }


  function renderCharacter() {
    const character = state?.character;
    if (!character) return;
    const pet = $('pet');
    pet.dataset.characterId = character.characterId;
    // Only the built-in resolver supplies this local image reference.
    pet.dataset.visualResource = character.visual?.resourceKey || '';
    const image = $('character-image');
    const visual = character.visual;
    const scene = Scenes.selectScene({ game: gameStatus, messages: messages.values(), sessionId: state.sessionId, epoch: state.epoch });
    pet.dataset.scene = failedScenes.has(scene) ? 'default' : scene;
    const localSource = (character.useBuiltinScenes === true || (!('useBuiltinScenes' in character) && character.characterId === 'official.eckera')) ? Scenes.sourceFor(scene, failedScenes) : visual?.source;
    const source = ['builtin-image', 'character-image'].includes(visual?.kind) && typeof localSource === 'string' ? new URL(localSource, document.baseURI).href : '';
    if (source && image.src !== source) {
      image.hidden = false;
      $('character-visual-error').hidden = true;
      image.src = source;
    } else if (!source) {
      image.hidden = true;
      $('character-visual-error').hidden = false;
    }
    pet.setAttribute('aria-label', `${character.displayName}：单击打字，长按说话，拖动移动，右键设置`);
    pet.title = `${character.displayName} / ${character.englishName} · ${character.visual?.label || '视觉待确认'}`;
    $('chat-form').setAttribute('aria-label', `给${character.displayName}发消息`);
  }

  $('character-image').addEventListener('load', () => {
    $('character-image').hidden = false;
    $('character-visual-error').hidden = true;
    updateRects();
  });
  $('character-image').addEventListener('error', () => {
    const scene = $('pet').dataset.scene;
    if (scene && scene !== 'default') { failedScenes.add(scene); renderCharacter(); return; }
    $('character-image').hidden = true;
    $('character-visual-error').hidden = false;
    updateRects();
  });

  function renderBubble() {
    lastReply = Bubbles.latestReply(messages.values(), state);
    // Pagination is presentation-only: messages/history retain the entire original reply.
    if (!lastReply || lastReply.id === blockedReplyId) { bubbleQueue?.clear(); return; }
    bubbleQueue?.replace(`${state.epoch}:${state.sessionId}:${lastReply.id}`, lastReply.text);
    updateRects();
  }

  function renderTasks() { refreshExpression(); }

  function applyState(next) {
    if (!next || !Number.isSafeInteger(next.epoch) || typeof next.sessionId !== 'string') return;
    if (state && next.epoch < state.epoch) return;
    const switched = !state || next.epoch !== state.epoch || next.sessionId !== state.sessionId;
    const oldPreferences = preferences();
    const providersChanged = next.preferences && (next.preferences.sttProvider !== oldPreferences.sttProvider || next.preferences.ttsProvider !== oldPreferences.ttsProvider);
    if (switched || providersChanged) cancelVoice(providersChanged && state ? '语音服务已切换' : '');
    if (switched) {
      clearTimeout(noticeTimer); motion?.reset();
      messages = new Map(); tools.clear(); requests.clear(); blockedReplyId = null; bubbleQueue?.clear();
      $('message').value = ''; resetDraftNote(); resizeComposer();
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
    $('message').placeholder = !next.canSend ? '后端未接入，暂不能发送' : next.connection?.state === 'disconnected' ? '连接已中断' : '输入消息…';
    renderCharacter(); renderBubble(); renderTasks();
    if (next.storageWarning) showError(next.storageWarning);
  }

  function onRuntimeEvent(event) {
    if (!event || typeof event !== 'object') return;
    if (event.type === 'visibility') { motion?.setVisible(event.visible !== false); if (event.visible === false) { bubbleQueue?.pause(); cancelVoice('桌宠已隐藏，语音操作已停止', false); } else bubbleQueue?.resume(); return; }
    if (event.type === 'stop-speech') { cancelVoice('语音操作已停止', false); return; }
    if (event.type === 'composer') { setComposer(event.open !== false, true); return; }
    if (event.type === 'read-last-reply') { speakLast(); return; }
    if (event.type === 'state') { applyState(event.state); return; }
    if (event.type === 'speech') { onSpeechEvent(event.state); return; }
    if (event.type === 'speech-config') { speechPreferences = event.config || { enabled: false }; cancelVoice('', false); return; }
    if (event.type === 'pet-motion') { if (event.epoch === state?.epoch && event.sessionId === state?.sessionId) motion?.setState(event.state); return; }
    if (event.type === 'message' && UI.belongsToSession(event.message, state)) {
      const isNew = !messages.has(event.message.id);
      messages.set(event.message.id, event.message); renderCharacter(); renderBubble();
      if (isNew && event.message.role === 'assistant' && event.message.metadata?.synthetic !== true && speechPreferences.enabled) enqueueSpeech(event.message);
      if (isNew && event.message.origin === 'proactive' && speechPhase === 'idle' && $('error').hidden &&
          ![...requests.values()].some(item => ['pending', 'running', 'accepted', 'queued'].includes(item.status))) {
        setExpression('notice'); clearTimeout(noticeTimer); noticeTimer = setTimeout(refreshExpression, 2500);
      }
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
    if (!text || !state || !state.canSend || state.connection?.state === 'disconnected') return;
    const context = { sessionId:state.sessionId, epoch:state.epoch };
    blockedReplyId = lastReply?.id || null; bubbleQueue?.clear();
    $('message').value = ''; resetDraftNote(); resizeComposer();
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
    try { speechPreferences = unwrap(await api.getSpeechConfig()); } catch { speechPreferences = { enabled: false }; }
    try { speechInfo = unwrap(await api.speechCapabilities()); }
    catch { speechInfo = null; }
  }
  function stopPlayer() {
    if (player) { player.pause(); player.removeAttribute('src'); player.load(); player = null; }
    if (playerUrl) { URL.revokeObjectURL(playerUrl); playerUrl = null; }
  }

  function cancelVoice(message = '语音操作已取消', notifyMain = true) {
    voiceFence.invalidate();
    ttsQueue?.switchContext();
    for (const finish of [...systemSpeechWaiters.values()]) finish('cancelled');
    systemSpeechResults.clear();
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

  async function localRecordingWav(blob) {
    const context = new AudioContext();
    let decoded;
    try { decoded = await context.decodeAudioData(await blob.arrayBuffer()); }
    finally { await context.close(); }
    if (!decoded.length || decoded.duration > 65) throw new Error('录音长度无效。');
    const frames = Math.ceil(decoded.duration * 16000);
    const offline = new OfflineAudioContext(1, frames, 16000);
    const source = offline.createBufferSource();
    source.buffer = decoded; source.connect(offline.destination); source.start();
    const pcm = (await offline.startRendering()).getChannelData(0);
    const wav = new ArrayBuffer(44 + pcm.length * 2);
    const view = new DataView(wav);
    const tag = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    tag(0, 'RIFF'); view.setUint32(4, wav.byteLength - 8, true); tag(8, 'WAVE'); tag(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); tag(36, 'data'); view.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const value = Math.max(-1, Math.min(1, pcm[i]));
      view.setInt16(44 + i * 2, value * (value < 0 ? 32768 : 32767), true);
    }
    return wav;
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
      const audio = operation.provider === 'local-whisper' ? await localRecordingWav(blob) : await blob.arrayBuffer();
      if (!speechResultCurrent({}, operation)) return;
      const result = unwrap(await api.transcribe({ ...operation.context, provider:operation.provider, audio, mimeType:operation.provider === 'local-whisper' ? 'audio/wav' : blob.type, language:'zh' }));
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

  function enqueueSpeech(reply, interrupt = false) {
    if (!state || !speechPreferences.enabled || !ttsQueue) return;
    const context = speechContext(operationId('tts'));
    setVoiceStatus('正在准备播报…', 'speaking');
    ttsQueue.enqueue({ ...context, text: reply.text }, { interrupt }).then(() => {
      if (context.generation === state?.epoch && context.conversationId === state?.sessionId) setVoiceStatus('播报完成');
    }).catch(error => {
      if (error.code !== 'cancelled' && context.generation === state?.epoch && context.conversationId === state?.sessionId) { setVoiceStatus('语音失败，文字仍可阅读'); }
    });
  }
  async function speakLast() {
    if (!lastReply || !state) return;
    if (!speechPreferences.enabled) { showError('请先在语音设置中启用朗读。'); return; }
    cancelVoice(''); enqueueSpeech(lastReply, true);
  }

  function onSpeechEvent(event) {
    if (event?.operationId && event.generation === state?.epoch && event.conversationId === state?.sessionId && ['finished', 'stopped', 'cancelled', 'error'].includes(event.state)) {
      if (systemSpeechWaiters.has(event.operationId)) systemSpeechWaiters.get(event.operationId)(event.state);
      else { systemSpeechResults.set(event.operationId, event.state); if (systemSpeechResults.size > 30) systemSpeechResults.delete(systemSpeechResults.keys().next().value); }
    }
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
    if (action === 'click') { bubbleQueue?.reopen(); setComposer($('chat-form').hidden, true); }
    if ($('pet').hasPointerCapture?.(event.pointerId)) $('pet').releasePointerCapture(event.pointerId);
  }

  function bindEvents() {
    $('chat-form').addEventListener('submit', send);
    let bubbleHovered = false, bubbleFocused = false;
    const reading = () => bubbleQueue?.setReading(bubbleHovered || bubbleFocused);
    $('compact-bubble').addEventListener('pointerenter', () => { bubbleHovered = true; reading(); });
    $('compact-bubble').addEventListener('pointerleave', () => { bubbleHovered = false; reading(); });
    $('compact-bubble').addEventListener('focus', () => { bubbleFocused = true; reading(); });
    $('compact-bubble').addEventListener('blur', () => { bubbleFocused = false; reading(); });
    let bubblePointer = null;
    $('compact-bubble').addEventListener('pointerdown', event => {
      bubblePointer = event.button === 0 ? { id:event.pointerId, x:event.clientX, y:event.clientY, moved:false } : null;
    });
    $('compact-bubble').addEventListener('pointermove', event => {
      if (bubblePointer?.id === event.pointerId && Math.hypot(event.clientX - bubblePointer.x, event.clientY - bubblePointer.y) > 5) bubblePointer.moved = true;
    });
    $('compact-bubble').addEventListener('pointercancel', () => { bubblePointer = null; });
    $('compact-bubble').addEventListener('click', event => {
      const isClick = event.detail === 0 || (bubblePointer && !bubblePointer.moved);
      bubblePointer = null;
      if (isClick && !window.getSelection()?.toString()) bubbleQueue?.next();
    });
    $('compact-bubble').addEventListener('keydown', event => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) { event.preventDefault(); bubbleQueue?.next(); }
    });
    $('message').addEventListener('compositionstart', () => { composing = true; });
    $('message').addEventListener('compositionend', () => { composing = false; });
    $('message').addEventListener('keydown', event => { if (UI.shouldSubmitText(event, composing)) { event.preventDefault(); send(); } });
    $('message').addEventListener('input', () => { if ($('message').value.trim()) { blockedReplyId = lastReply?.id || null; bubbleQueue?.clear(); } resizeComposer(); });
    $('cancel-voice').addEventListener('click', () => cancelVoice());
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
    $('pet').addEventListener('keydown', event => { if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) { event.preventDefault(); bubbleQueue?.reopen(); setComposer($('chat-form').hidden, true); } });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { clearTimeout(holdTimer); cancelVoice(''); bubbleQueue?.hide(); setComposer(false); } });
    document.addEventListener('toggle', updateRects, true);
    window.addEventListener('resize', () => { resizeComposer(); updateRects(); });
    window.addEventListener('blur', () => { clearTimeout(holdTimer); if (recording) stopRecording(true); });
    window.addEventListener('beforeunload', () => { sceneClosed = true; ttsQueue?.dispose(); queuedPlayback?.stop(); motion?.dispose(); clearTimeout(noticeTimer); disposeAppearance?.(); clearTimeout(gamePollTimer); cancelVoice(''); bubbleQueue?.dispose(); unsubscribe?.(); });
    const observer = new ResizeObserver(updateRects);
    [$('compact-bubble'), $('chat-form')].forEach(element => observer.observe(element));
  }

  async function pollGameStatus() {
    if (sceneClosed || !api.gameStatus) return;
    try { gameStatus = unwrap(await api.gameStatus()) || { state: 'unknown' }; }
    catch { gameStatus = { state: 'unknown' }; }
    if (sceneClosed) return;
    renderCharacter();
    gamePollTimer = setTimeout(pollGameStatus, 10000);
  }

  let unsubscribe;
  let disposeAppearance;
  if (!api || !UI || !Bubbles || !Scenes) {
    $('error').textContent = '桌宠桥接未就绪，请从应用打开。';
    $('error').hidden = false; $('interaction-feedback').hidden = false;
    return;
  }
  bindEvents();
  disposeAppearance = window.CompanionAppearance?.bindPet({window, document, storage: window.localStorage, onChange: prefs => { bubbleQueue?.configure(prefs); motion?.setEnabled(prefs.lightMotion); resizeComposer(); updateRects(); }});
  unsubscribe = api.subscribe(onRuntimeEvent);
  call(() => api.getState()).then(value => { if (value) applyState(value); });
  refreshSpeechCapabilities();
  pollGameStatus();
  updateRects();
})();
