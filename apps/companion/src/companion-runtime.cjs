'use strict';
const { asksImportedDiagnostic } = require('./windows-discovery.cjs');

const { UiChangeTracker } = require('./ui-changes.cjs');
const { matchView, matchCard, MatchChangeTracker } = require('./match-reader.cjs');
const { CharacterSession } = require('./character-session.cjs');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const { MockReaderClient, DisconnectedReaderClient, metadata, MOCK_LIMITATIONS, businessMetadata, adviceCapability } = require('./reader-clients.cjs');
const { DEFAULT_CHARACTER_ID, storedCharacterId, characterPresentation } = require('./character.cjs');
const PREFERENCE_VALUES = Object.freeze({
  expression: ['auto', 'idle', 'listening', 'transcribing', 'thinking', 'speaking', 'notice', 'happy', 'puzzled', 'error'],
  sttProvider: ['local-whisper', 'openai', 'mock'],
  ttsProvider: ['system', 'edge', 'openai', 'azure', 'mock'],
});

function text(value, max, label) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`${label}为空或过长。`);
  return value.trim();
}

class CompanionRuntime extends EventEmitter {
  constructor(options = {}) {
    super();
    this.file = options.file;
    this.characterLibrary = options.characterLibrary || null;
    this.cancelCharacterEffects = options.cancelCharacterEffects || (() => {});
    this.saveId = `session:${randomUUID()}`; this.verifiedSave = false;
    this.temporaryScopes = new Map(); this.temporarySelections = new Map();
    this.memoryControllers = new Set(); this.scopeStorageWarning = null;
    if (this.characterLibrary) {
      const library = this.characterLibrary;
      // Unknown game identity is never a persistent save or selection bucket.
      const sessions = {
        resolve: id => library.resolve(id),
        selected: saveId => saveId.startsWith('session:') ? library.resolve(this.temporarySelections.get(saveId)) : library.selected(saveId),
        select: (saveId, id) => {
          if (!saveId.startsWith('session:')) return library.select(saveId, id);
          const selected = library.resolve(id); if (selected.fallback) throw Error('Selected character is unavailable');
          this.temporarySelections.set(saveId, selected.characterId); return selected;
        },
      };
      this.characterSession = new CharacterSession({ library: sessions, cancel: [() => {
        this.cancelAll(); for (const controller of this.memoryControllers) controller.abort();
        this.memoryControllers.clear(); this.cancelCharacterEffects();
      }] });
    }
    this.mockClient = options.mockClient || new MockReaderClient();
    this.realClient = options.realClient || new DisconnectedReaderClient();
    this.captureRequest = null; this.captureController = null;
    this.uiChanges = new UiChangeTracker();
    this.matchChanges = new MatchChangeTracker();
    this.readerPreviews = []; this.previewController = null; this.previewTimer = null; this.previewExpiryTimer = null;
    this.realConnection = null; this.connectionController = null;
    this.mode = 'mock'; this.backendId = 'mock'; this.epoch = 1; this.sessionId = randomUUID(); this.mockDisconnected = false;
    this.proactivity = 80; this.historyEnabled = false;
    this.characterId = DEFAULT_CHARACTER_ID;
    this.preferences = { expression: 'auto', sttProvider: 'local-whisper', ttsProvider: 'system' };
    this.savedEnvelope = {};
    this.messages = []; this.memories = []; this.pending = new Map();
    this.tools = new Map();
    this.writeQueue = Promise.resolve(); this.storageRevision = null; this.closed = false;
  }
  async init() {
    if (!this.file) return this.initializeCharacter();
    try {
      const stored = await readStateFile(this.file);
      this.storageRevision = stored.revision;
      if (!stored.bytes) return this.initializeCharacter();
      const saved = JSON.parse(stored.bytes.toString('utf8'));
      if (saved.version !== 1) {
        this.storageWarning = '本地记录版本暂不支持；原文件保持不变，当前更改不会写入该文件。';
        return this.initializeCharacter();
      }
      this.savedEnvelope = saved;
      this.characterId = storedCharacterId(saved.characterId);
      if (Number.isInteger(saved.proactivity) && saved.proactivity >= 0 && saved.proactivity <= 100) this.proactivity = saved.proactivity;
      this.historyEnabled = saved.historyEnabled === true;
      if (saved.preferences && typeof saved.preferences === 'object' && !Array.isArray(saved.preferences)) {
        for (const [key, values] of Object.entries(PREFERENCE_VALUES)) {
          if (values.includes(saved.preferences[key])) this.preferences[key] = saved.preferences[key];
        }
      }
      this.memories = Array.isArray(saved.memories) ? saved.memories.filter(item => item && typeof item.id === 'string' && typeof item.text === 'string' && item.text.length <= 2_000).slice(-200) : [];
      if (this.historyEnabled && Array.isArray(saved.messages)) this.messages = saved.messages.filter(item => item && typeof item.id === 'string' && typeof item.text === 'string' && item.text.length <= 12_000).slice(-500);
    } catch (error) {
      if (error.code !== 'ENOENT') this.storageWarning = '本地记录无法读取；原文件未被删除。';
    }
    return this.initializeCharacter();
  }
  initializeCharacter() {
    if (this.characterLibrary && !this.characterSession.current) this.activateCharacter(undefined, false);
    return this.state();
  }
  characterContext() {
    const token = this.characterSession?.current;
    return token ? { save_id: token.scope.saveId, character_id: token.scope.characterId, persona: token.character.persona } : undefined;
  }
  currentCharacter() {
    const value = this.characterSession?.current?.character;
    if (!value) return characterPresentation(this.characterId);
    const useBuiltinScenes = value.characterId === DEFAULT_CHARACTER_ID && path.resolve(value.portraitPath) === path.join(__dirname, 'assets/characters/official.eckera/default.png');
    return { characterId: value.characterId, requestedCharacterId: value.requestedCharacterId,
      name: value.name, displayName: value.name, englishName: value.characterId === DEFAULT_CHARACTER_ID ? 'Eckera' : value.name,
      fallback: value.fallback, warnings: value.warnings, voice: value.voice, useBuiltinScenes,
      visual: { kind: 'character-image', source: pathToFileURL(value.portraitPath).href, label: value.name } };
  }
  saveCharacterScope() {
    const token = this.characterSession?.current;
    if (!token || this.scopeStorageWarning) return;
    const value = { messages: this.historyEnabled ? structuredClone(this.messages) : [], memories: structuredClone(this.memories) };
    if (!this.verifiedSave) this.temporaryScopes.set(token.scope.key, value);
    else {
      try { this.characterLibrary.writeScope(token.scope.saveId, token.scope.characterId, value); }
      catch (error) { this.scopeStorageWarning = '角色记录保存失败；原记录保持不变。'; throw error; }
    }
  }
  activateCharacter(id, savePrevious = true) {
    if (!this.characterLibrary) throw Error('角色库尚未启用。');
    if (savePrevious) this.saveCharacterScope();
    const token = this.characterSession.activate(this.saveId, id);
    this.characterId = token.scope.characterId; this.scopeStorageWarning = null;
    this.tools.clear(); this.epoch += 1; this.sessionId = randomUUID();
    let saved = { messages: [], memories: [] };
    try { saved = this.verifiedSave ? this.characterLibrary.readScope(this.saveId, this.characterId) : this.temporaryScopes.get(token.scope.key) || saved; }
    catch { this.scopeStorageWarning = '角色记录无法读取；不会覆盖原记录。'; }
    this.messages = this.historyEnabled && Array.isArray(saved.messages) ? saved.messages.filter(item => item && typeof item.text === 'string' && item.text.length <= 12000).slice(-500).map(item => ({ ...item, sessionId: this.sessionId, epoch: this.epoch })) : [];
    this.memories = Array.isArray(saved.memories) ? saved.memories.filter(item => item && typeof item.id === 'string' && typeof item.text === 'string' && item.text.length <= 2000).slice(-200).map(item => ({ ...item })) : [];
    this.refreshConnection(); this.changed(); return this.state();
  }
  listCharacters() { return this.characterLibrary ? this.characterLibrary.list().map(value => ({ characterId: value.characterId, name: value.name, version: value.version, fallback: value.fallback, warnings: value.warnings })) : [this.currentCharacter()]; }
  selectCharacter(id) { return this.activateCharacter(id); }
  refreshCharacter() { return this.activateCharacter(this.characterId); }
  // Internal adapter boundary only: never derive a save identity from UI labels or scores.
  bindSaveContext(verifiedSaveId) {
    if (!this.characterLibrary || typeof verifiedSaveId !== 'string' || !verifiedSaveId.trim() || verifiedSaveId.startsWith('session:') || verifiedSaveId.includes('\0') || Buffer.byteLength(verifiedSaveId) > 512) throw Error('需要已验证的存档标识。');
    if (this.verifiedSave && this.saveId === verifiedSaveId) return this.state();
    this.saveCharacterScope(); const previous = { saveId: this.saveId, verifiedSave: this.verifiedSave };
    this.saveId = verifiedSaveId; this.verifiedSave = true;
    try { return this.activateCharacter(undefined, false); }
    catch (error) { this.saveId = previous.saveId; this.verifiedSave = previous.verifiedSave; throw error; }
  }
  client() { return this.mode === 'mock' ? this.mockClient : this.realClient; }
  state() {
    const mock = this.mode === 'mock';
    return {
      canSend: mock ? !this.mockDisconnected : typeof this.realClient.reply === 'function',
      mode: this.mode, epoch: this.epoch, sessionId: this.sessionId, proactivity: this.proactivity,
      preferences: { ...this.preferences },
      character: this.currentCharacter(),
      characterScope: this.characterSession?.current ? { ...this.characterSession.current.scope, verifiedSave: this.verifiedSave, generation: this.characterSession.current.epoch } : null,
      connection: !mock && this.realConnection ? { ...this.realConnection, backendId: this.backendId } : { state: mock ? (this.mockDisconnected ? 'disconnected' : 'simulated') : 'unavailable', label: mock ? (this.mockDisconnected ? '模拟模式 · 连接已失效（模拟）' : '模拟模式 · 未连接游戏或模型') : '真实模式 · 后端尚未接入', reason: mock ? (this.mockDisconnected ? '模拟断线场景；恢复其他示例后可继续演示。' : null) : '真实后端由另一开发线提供；当前未发起网络请求。', backendId: this.backendId },
      captureRequest: mock ? null : this.captureRequest,
      readerPreviews: mock ? [] : this.readerPreviews.map(card => card.status === 'available' && Date.now() - Date.parse(card.metadata?.sampledAt) > 15_000
        ? { ...card, status: 'stale', fields: [], metadata: { ...card.metadata, freshness: 'stale' } } : card),
      historyEnabled: this.historyEnabled, capabilities: this.client().capabilities(this.realConnection?.readiness), synthetic: mock,
      limitations: mock ? [...MOCK_LIMITATIONS] : ['真实模式不会自动回退到模拟数据。', 'Alpha 默认依据部分 UI 采样文本给出有条件建议；页面与可见性未验证，可能含隐藏或缓存文本，不代表后台全量事实。', '原生业务建议仍须通过独立的服务端业务就绪检查；UI 采样不会使原生能力就绪。'],
      messages: this.messages.filter(item => item.sessionId === this.sessionId),
      pendingRequests: [...this.pending.values()].map(item => ({ requestId: item.id, sessionId: item.sessionId, epoch: item.epoch, text: item.text })),
      tools: [...this.tools.values()].filter(item => item.sessionId === this.sessionId && item.epoch === this.epoch),
      memoryCount: this.memories.length, storageWarning: this.scopeStorageWarning || this.storageWarning || null,
    };
  }
  publish(event) { if (!this.closed) this.emit('event', event); }
  changed() { this.publish({ type: 'state', state: this.state() }); }
  persist() {
    try { this.saveCharacterScope(); } catch { this.changed(); return Promise.resolve(); }
    if (!this.file || this.storageWarning) return Promise.resolve();
    const value = JSON.stringify({ ...this.savedEnvelope, version: 1, characterId: this.characterId, proactivity: this.proactivity, preferences: { ...this.savedEnvelope.preferences, ...this.preferences }, historyEnabled: this.historyEnabled, memories: this.characterLibrary ? [] : this.memories, messages: !this.characterLibrary && this.historyEnabled ? this.messages : [] });
    this.writeQueue = this.writeQueue.catch(() => {}).then(async () => {
      if (this.storageWarning) return;
      this.storageRevision = await writeStateFile(this.file, value, this.storageRevision);
    }).catch(() => { this.storageWarning = '本地记录保存失败。'; this.changed(); });
    return this.writeQueue;
  }
  cancelAll() { for (const id of [...this.pending.keys()]) this.cancelRequest(id); }
  async setCaptureProfile(profile) {
    if (!['schedule', 'current_page_attributes', 'tactics', 'next_match'].includes(profile)) throw new Error('不支持的页面读取类型。');
    if (this.mode !== 'real' || typeof this.realClient.setCaptureProfile !== 'function') throw new Error('请先连接真实本机服务。');
    if (this.captureController) return this.state(); // One write at a time; repeated clicks do not queue.
    this.previewController?.abort(); this.previewController = null;
    clearTimeout(this.previewTimer); clearTimeout(this.previewExpiryTimer);
    this.readerPreviews = []; this.uiChanges.reset();
    const controller = this.captureController = new AbortController();
    const epoch = this.epoch;
    this.captureRequest = { profile, status: 'requesting', sequence: null, reason: null }; this.changed();
    try {
      const result = await this.realClient.setCaptureProfile(profile, { signal: controller.signal });
      if (controller.signal.aborted || epoch !== this.epoch || this.closed) return this.state();
      if (!result || !['pending', 'applied', 'unavailable', 'not_configured'].includes(result.status) || (result.profile !== profile && !(['unavailable', 'not_configured'].includes(result.status) && result.profile === null))) throw new Error('读取请求响应不匹配，尚未确认生效。');
      if (['pending', 'applied'].includes(result.status) && !Number.isSafeInteger(result.sequence)) throw new Error('读取请求缺少确认序号，尚未确认生效。');
      this.captureRequest = { profile, status: result.status, sequence: result.sequence, reason: result.reason || null };
    } catch (error) {
      if (!controller.signal.aborted && epoch === this.epoch && !this.closed) this.captureRequest = { profile, status: 'failed', sequence: null, reason: error.message };
    } finally {
      if (this.captureController === controller) {
        this.captureController = null; this.changed(); this.refreshReaderPreviews();
      }
    }
    return this.state();
  }
  async refreshReaderPreviews() {
    if (this.mode !== 'real' || typeof this.realClient.previews !== 'function' || this.closed || this.captureController) return this.state();
    if (this.previewController) return this.state();
    clearTimeout(this.previewTimer);
    const controller = this.previewController = new AbortController();
    const epoch = this.epoch;
    try {
      if (this.captureRequest && ['pending', 'applied'].includes(this.captureRequest.status)) {
        const expected = this.captureRequest;
        const result = await this.realClient.captureProfileStatus({ signal: controller.signal });
        if (controller.signal.aborted || epoch !== this.epoch || this.closed || expected !== this.captureRequest) return this.state();
        if (result?.profile === null && result.sequence === null && ['unavailable', 'not_configured'].includes(result.status)) {
          this.captureRequest = { ...expected, status: result.status, reason: result.reason || null };
        } else if (result?.profile === expected.profile && result.sequence === expected.sequence && ['pending', 'applied', 'ready', 'unavailable', 'not_configured'].includes(result.status)) {
          this.captureRequest = { ...expected, status: result.status, reason: result.reason || null };
        }
        if (this.captureRequest.status !== 'ready') { this.readerPreviews = []; this.changed(); return this.state(); }
        // Fetch previews only AFTER applied + fresh-scope confirmation, never from a pre-switch parallel response.
      }
      const [cards, change, match] = await Promise.all([
        this.realClient.previews({ signal: controller.signal }),
        typeof this.realClient.uiChangePreview === 'function' && this.proactivity > 0
          ? this.realClient.uiChangePreview({ signal: controller.signal }).catch(() => null) : null,
        typeof this.realClient.match === 'function' ? this.realClient.match({ signal: controller.signal }).catch(() => null) : null,
      ]);
      if (!controller.signal.aborted && !this.closed && epoch === this.epoch) {
        const view = matchView(match);
        this.readerPreviews = view ? [matchCard(view), ...cards] : cards;
        // Service reachability is independent of supported page projections and model configuration.
        if (cards.some(card => card.transport === 'connected')) {
          this.connectionController?.abort();
          this.realConnection = { state: 'connected', label: '真实模式 · 服务已连接', reason: null, readiness: this.realConnection?.readiness };
        } else if (cards.length && cards.every(card => card.transport === 'unavailable')) {
          this.connectionController?.abort(); this.uiChanges.reset();
          this.realConnection = { state: 'unavailable', label: '真实模式 · 服务连接失败', reason: cards[0].error || '无法读取本机服务，请检查服务是否仍在运行。' };
        }
        clearTimeout(this.previewExpiryTimer);
        const expiry = Math.min(...cards.filter(card => card.status === 'available').map(card => Date.parse(card.metadata?.sampledAt) + 15_001));
        if (Number.isFinite(expiry)) {
          this.previewExpiryTimer = setTimeout(() => this.changed(), Math.max(0, expiry - Date.now()));
          this.previewExpiryTimer.unref?.();
        }
        const notice = this.uiChanges.observe(change, { enabled: this.proactivity > 0 });
        if (notice) this.addMessage({ ...notice, id: randomUUID(), role: 'assistant', origin: 'proactive',
          createdAt: new Date().toISOString(), sessionId: this.sessionId, epoch: this.epoch });
        const matchNotice = this.matchChanges.observe(view, this.proactivity > 0);
        if (matchNotice) this.addMessage({ ...matchNotice, id: randomUUID(), role: 'assistant', origin: 'proactive',
          createdAt: new Date().toISOString(), sessionId: this.sessionId, epoch: this.epoch });
        this.changed();
      }
    } catch (error) {
      if (!controller.signal.aborted && epoch === this.epoch) {
        this.readerPreviews = []; this.uiChanges.reset(); this.connectionController?.abort();
        if (this.captureRequest && ['pending', 'applied'].includes(this.captureRequest.status)) this.captureRequest = { ...this.captureRequest, status: 'failed', reason: error.message };
        this.realConnection = { state: 'unavailable', label: '真实模式 · 服务连接失败', reason: error.message || '无法读取本机服务。' }; this.changed();
      }
    } finally {
      if (this.previewController === controller) {
        this.previewController = null;
        if (!this.closed && this.mode === 'real') { this.previewTimer = setTimeout(() => this.refreshReaderPreviews(), 5_000); this.previewTimer.unref?.(); }
      }
    }
    return this.state();
  }
  refreshConnection() {
    this.captureController?.abort(); this.captureController = null; this.captureRequest = null;
    this.previewController?.abort(); this.previewController = null;
    clearTimeout(this.previewTimer); clearTimeout(this.previewExpiryTimer); this.readerPreviews = []; this.uiChanges.reset(); this.matchChanges.reset();
    this.refreshReaderPreviews();
    this.connectionController?.abort();
    if (this.mode !== 'real' || typeof this.realClient.reply !== 'function') return;
    const controller = this.connectionController = new AbortController();
    const epoch = this.epoch;
    this.realConnection = { state: 'loading', label: '真实模式 · 正在连接', reason: null };
    this.realClient.status({ signal: controller.signal }).then(result => {
      if (controller.signal.aborted || this.closed || epoch !== this.epoch) return;
      this.realConnection = { state: 'connected', label: '真实模式 · 服务已连接', reason: result.metadata.limitations.join('、') || null, readiness: result.readiness }; this.changed();
    }).catch(error => {
      if (controller.signal.aborted || this.closed || epoch !== this.epoch) return;
      this.realConnection = { state: 'unavailable', label: '真实模式 · 服务不可用', reason: error.message }; this.changed();
    });
  }
  switchSession() {
    if (this.characterLibrary) { this.saveCharacterScope(); this.characterSession.activate(this.saveId, this.characterId); }
    this.cancelAll(); this.tools.clear(); this.epoch += 1; this.sessionId = randomUUID(); this.refreshConnection(); this.changed();
    return this.state();
  }
  setMode(input) {
    const mode = typeof input === 'string' ? input : input?.mode;
    if (!['mock', 'real'].includes(mode)) throw new Error('模式无效。');
    const backendId = typeof input === 'object' && input.backendId !== undefined ? text(input.backendId, 80, '后端标识') : mode === 'mock' ? 'mock' : 'local-service';
    if (this.characterLibrary) this.saveCharacterScope();
    this.cancelAll(); this.tools.clear(); this.mode = mode; this.backendId = backendId; this.mockDisconnected = false; this.epoch += 1; this.sessionId = randomUUID();
    if (this.characterLibrary) { this.saveId = `session:${randomUUID()}`; this.verifiedSave = false; this.activateCharacter(this.characterId, false); }
    else { this.refreshConnection(); this.changed(); }
    return this.state();
  }
  setProactivity(value) {
    if (!Number.isInteger(value) || value < 0 || value > 100) throw new Error('主动性必须是 0–100 的整数。');
    if (value !== this.proactivity) {
      this.uiChanges.reset();
      // A response begun before mute/unmute must not become a new comparison.
      this.previewController?.abort(); this.previewController = null;
      clearTimeout(this.previewTimer);
    }
    this.proactivity = value; this.refreshReaderPreviews(); this.persist(); this.changed(); return this.state();
  }
  setPreferences(patch) {
    if (!patch || typeof patch !== 'object' || Array.isArray(patch) || Object.keys(patch).length === 0) throw new Error('偏好设置无效。');
    for (const [key, value] of Object.entries(patch)) {
      if (!Object.hasOwn(PREFERENCE_VALUES, key) || !PREFERENCE_VALUES[key].includes(value)) throw new Error('偏好设置包含不支持的选项。');
    }
    this.preferences = { ...this.preferences, ...patch }; this.persist(); this.changed(); return this.state();
  }
  setHistoryEnabled(value) {
    if (typeof value !== 'boolean') throw new Error('历史记录设置无效。');
    this.historyEnabled = value; this.persist(); this.changed(); return this.getHistory();
  }
  addMessage(message) {
    this.messages.push(message); this.messages = this.messages.slice(-500); this.persist();
    this.publish({ type: 'message', message });
  }
  active(request) { return !this.closed && !request.controller.signal.aborted && this.pending.get(request.id) === request && request.epoch === this.epoch && request.sessionId === this.sessionId && (!this.characterSession || this.characterSession.accepts(request.characterToken)); }
  tool(request, status, meta) {
    if (!this.active(request)) return;
    const id = `${request.id}:snapshot`;
    const labels = { running: '读取模拟观测', completed: '模拟观测读取完成', cancelled: '模拟读取已取消', error: '模拟读取失败' };
    if (this.mode === 'real') Object.assign(labels, { running: '请求真实服务', completed: '真实服务已回复', cancelled: '真实请求已取消', error: '真实请求失败' });
    const event = { type: 'tool', requestId: request.id, sessionId: request.sessionId, epoch: request.epoch, tool: { id, name: request.mode === 'real' ? (request.diagnostic ? 'reader.windows-discovery' : request.capability ? (request.adviceMode === 'ui_evidence' ? 'agent.ui-advice' : 'agent.business-advice') : 'agent.chat') : 'reader.snapshot', status, label: labels[status] || status, metadata: meta || this.tools.get(id)?.tool.metadata || (this.mode === 'mock' ? metadata(request.sessionId) : businessMetadata()) } };
    this.tools.set(id, event);
    if (this.tools.size > 100) this.tools.delete(this.tools.keys().next().value);
    this.publish(event);
  }
  sendMessage(input) {
    const message = text(input?.text ?? input?.message, 4_000, '消息');
    if (input?.generation !== undefined && input.generation !== this.epoch) throw new Error('会话已切换，请重新发送。');
    if (input?.conversationId !== undefined && input.conversationId !== this.sessionId) throw new Error('会话已切换，请重新发送。');
    if (this.mode !== 'mock' && typeof this.realClient.reply !== 'function') throw new Error('真实后端尚未接入，消息没有发送；可显式切换到模拟模式演示。');
    if (this.mockDisconnected) throw new Error('模拟连接已失效；请选择其他模拟场景恢复连接。');
    if (this.pending.size >= 4) throw new Error('已有 4 个请求在处理，请稍候或取消。');
    const diagnostic = this.mode === 'real' && asksImportedDiagnostic(message);
    const capability = this.mode === 'real' && !diagnostic ? adviceCapability(message, input?.capability) : null;
    const adviceMode = input?.adviceMode ?? 'ui_evidence';
    if (!['ui_evidence', 'native'].includes(adviceMode)) throw new Error('不支持的建议模式。');
    const request = { characterToken: this.characterSession?.current, characterContext: this.characterContext(), diagnostic, capability, adviceMode, mode: this.mode, id: randomUUID(), epoch: this.epoch, sessionId: this.sessionId, text: message, controller: new AbortController() };
    if (this.mode === 'real') {
      // Previous cards are historical, not current values after a new read or failure.
      for (const item of this.messages) if (item.sessionId === this.sessionId && item.role === 'assistant') item.cards = [];
    }
    this.pending.set(request.id, request);
    this.addMessage({ id: randomUUID(), role: 'user', origin: 'user', text: message, createdAt: new Date().toISOString(), requestId: request.id, sessionId: this.sessionId, epoch: this.epoch, metadata: { source: 'user', sourceLabel: '用户输入', sessionId: this.sessionId, sampledAt: new Date().toISOString(), partial: false, limitations: [], synthetic: false, freshness: 'current' }, cards: [] });
    this.changed();
    queueMicrotask(() => this.complete(request));
    return { requestId: request.id, sessionId: request.sessionId, epoch: request.epoch };
  }
  async complete(request) {
    try {
      this.tool(request, 'running');
      const result = request.mode === 'real'
        ? await this.realClient.reply({ message: request.text, conversationId: request.sessionId, capability: request.capability, adviceMode: request.adviceMode, characterContext: request.characterContext, signal: request.controller.signal })
        : await this.mockClient.snapshot({ sessionId: request.sessionId, signal: request.controller.signal });
      if (!this.active(request)) return;
      if (request.mode === 'real') {
        this.connectionController?.abort();
        this.realConnection = { state: 'connected', label: '真实模式 · 服务已连接', reason: request.capability ? result.metadata.limitations.join('、') || null : null, readiness: request.capability ? result.metadata.readiness : this.realConnection?.readiness };
      }
      this.tool(request, 'completed', result.metadata);
      this.addMessage({ id: randomUUID(), role: 'assistant', origin: 'reply', text: request.mode === 'real' ? result.text : '【模拟回复】已收到你的消息。这是前端交互演示，尚未调用 AI 或读取游戏。下面的信息卡展示来源、未知值和数据限制。', createdAt: new Date().toISOString(), requestId: request.id, sessionId: request.sessionId, epoch: request.epoch, metadata: result.metadata, cards: result.cards });
      this.pending.delete(request.id);
      this.publish({ type: 'request', requestId: request.id, status: 'completed', sessionId: request.sessionId, epoch: request.epoch });
      this.changed();
    } catch (error) {
      if (!this.active(request)) return;
      this.tool(request, 'error');
      if (request.mode === 'real') this.realConnection = { state: 'unavailable', label: '真实模式 · 请求失败', reason: error.message };
      this.pending.delete(request.id);
      this.publish({ type: 'request', requestId: request.id, status: 'error', error: error.message, sessionId: request.sessionId, epoch: request.epoch });
      this.changed();
    }
  }
  cancelRequest(id) {
    if (typeof id !== 'string' || id.length > 128) throw new Error('请求标识无效。');
    const request = this.pending.get(id);
    if (!request) return { cancelled: false };
    this.tool(request, 'cancelled');
    request.controller.abort(); this.pending.delete(id);
    this.publish({ type: 'request', requestId: id, status: 'cancelled', sessionId: request.sessionId, epoch: request.epoch });
    this.changed(); return { cancelled: true };
  }
  async simulateEvent(kind = 'default') {
    if (!['default', 'stale', 'missing', 'partial', 'disconnected'].includes(kind)) throw new Error('模拟事件类型无效。');
    if (this.mode !== 'mock') throw new Error('只有明确选择模拟模式时才能生成模拟事件。');
    if ((kind === 'disconnected') !== this.mockDisconnected) {
      this.cancelAll(); this.tools.clear(); this.mockDisconnected = kind === 'disconnected'; this.epoch += 1; this.changed();
    }
    const epoch = this.epoch; const sessionId = this.sessionId;
    const result = await this.mockClient.snapshot({ sessionId, kind });
    if (this.closed || epoch !== this.epoch || sessionId !== this.sessionId) return { discarded: true };
    if (kind === 'missing') result.cards[0].fields = result.cards[0].fields.map(field => ({ ...field, value: null, status: 'unknown' }));
    if (kind === 'partial') result.metadata.limitations.push('本示例只包含部分观测，不能据此推断未展示字段。');
    if (kind === 'disconnected') result.metadata.limitations.push('此卡是断线前保留的模拟观测，不代表当前可用数据。');
    const message = { id: randomUUID(), role: 'assistant', origin: 'proactive', text: kind === 'disconnected' ? '【模拟断线】连接已失效，当前请求已取消。下面保留的模拟观测不代表当前数据；请选择其他示例恢复。' : `【模拟主动消息】收到一条${kind === 'stale' ? '过期' : kind === 'missing' ? '缺失字段的' : kind === 'partial' ? '部分' : ''}观测示例。主动性当前为 ${this.proactivity}%；具体触发策略等待后端接入后确定。`, createdAt: new Date().toISOString(), sessionId, epoch, metadata: result.metadata, cards: result.cards };
    this.addMessage(message); this.changed(); return { messageId: message.id };
  }
  getHistory() { return { enabled: this.historyEnabled, messages: [...this.messages] }; }
  async clearHistory() { this.characterSession?.activate(this.saveId, this.characterId); this.cancelAll(); this.tools.clear(); this.messages = []; this.epoch += 1; this.sessionId = randomUUID(); this.refreshConnection(); await this.persist(); this.changed(); return this.getHistory(); }
  getMemories() {
    if (this.characterLibrary && this.mode === 'real') return this.syncRealMemories();
    return { entries: [...this.memories] };
  }
  async memoryOperation(operation) {
    const token = this.characterSession.current, epoch = this.epoch;
    const context = this.characterContext(), controller = new AbortController();
    this.memoryControllers.add(controller);
    try {
      const result = await operation(context, controller.signal);
      if (controller.signal.aborted || epoch !== this.epoch || !this.characterSession.accepts(token)) throw Error('角色或会话已切换，旧记忆响应已丢弃。');
      return result;
    } finally { this.memoryControllers.delete(controller); }
  }
  memoryRecord(value) {
    if (!value || typeof value.id !== 'string' || typeof value.content !== 'string' || value.content.length > 2000) throw Error('记忆服务返回了无效记录。');
    return { id: value.id, text: value.content, createdAt: value.created_at, source: 'user-confirmed' };
  }
  async syncRealMemories() {
    const epoch = this.epoch;
    const result = await this.memoryOperation((characterContext, signal) => this.realClient.memories({ characterContext, signal }));
    if (!Array.isArray(result.memories) || result.memories.length > 200) throw Error('记忆服务返回了无效列表。');
    this.memories = result.memories.map(value => this.memoryRecord(value));
    await this.persist(); if (epoch !== this.epoch) throw Error('会话已切换。'); this.changed(); return { entries: [...this.memories] };
  }
  async saveMemory(input) {
    const epoch = this.epoch;
    const memory = { id: randomUUID(), text: text(input?.text, 2_000, '记忆内容'), createdAt: new Date().toISOString(), source: 'user-confirmed' };
    if (this.memories.length >= 200) throw new Error('已保存 200 条记忆，请先删除不再需要的内容。');
    if (this.characterLibrary && this.mode === 'real') {
      const result = await this.memoryOperation((characterContext, signal) => this.realClient.addMemory({ content: memory.text, characterContext, signal }));
      const saved = this.memoryRecord(result); this.memories.push(saved);
      await this.persist(); if (epoch !== this.epoch) throw Error('会话已切换。'); this.changed(); return saved;
    }
    this.memories.push(memory); await this.persist(); this.changed(); return memory;
  }
  async deleteMemory(id) {
    const epoch = this.epoch;
    if (typeof id !== 'string' || id.length > 128) throw new Error('记忆标识无效。');
    if (this.characterLibrary && this.mode === 'real') await this.memoryOperation((characterContext, signal) => this.realClient.deleteMemory({ id, characterContext, signal }));
    const before = this.memories.length; this.memories = this.memories.filter(item => item.id !== id);
    await this.persist(); if (epoch !== this.epoch) throw Error('会话已切换。'); this.changed(); return { deleted: before !== this.memories.length };
  }
  async close() { try { this.saveCharacterScope(); } catch {} this.characterSession?.dispose(); this.captureController?.abort(); this.captureController = null; clearTimeout(this.previewTimer); clearTimeout(this.previewExpiryTimer); this.previewController?.abort(); this.closed = true; this.connectionController?.abort(); this.cancelAll(); await this.writeQueue; this.removeAllListeners(); }
}

module.exports = { CompanionRuntime };
