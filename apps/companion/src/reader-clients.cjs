'use strict';
const { matchView, matchCard } = require('./match-reader.cjs');
const { calendarEndpoint } = require('./offseason-calendar.cjs');
const { validateImport, asksImportedDiagnostic, diagnosticReply } = require('./windows-discovery.cjs');

const MOCK_LIMITATIONS = Object.freeze([
  '这是前端模拟数据，没有连接游戏、Reader 或模型服务。',
  '原始 UI 可能包含缓存文本；本示例不确认球员身份、属性或字段含义。',
]);

function metadata(sessionId, extra = {}) {
  return {
    source: 'mock', sourceLabel: '模拟适配器', sessionId,
    sampledAt: new Date().toISOString(), partial: true,
    limitations: [...MOCK_LIMITATIONS], synthetic: true, freshness: 'unknown', ...extra,
  };
}

function abortError() { return Object.assign(new Error('请求已取消。'), { name: 'AbortError' }); }
function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const cancel = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve(); }, ms);
    signal?.addEventListener('abort', cancel, { once: true });
  });
}

class MockReaderClient {
  constructor(options = {}) { this.delay = options.delay ?? 300; }
  capabilities() {
    return ['status', 'snapshot', 'raw-ui', 'events', 'native'].map(id => ({ id, available: true, synthetic: true }));
  }
  async status({ sessionId, signal } = {}) {
    await pause(this.delay, signal);
    return { connection: 'simulated', metadata: metadata(sessionId), capabilities: this.capabilities() };
  }
  async snapshot({ sessionId, signal, kind = 'default' } = {}) {
    await pause(this.delay, signal);
    const meta = metadata(sessionId, kind === 'stale' ? { freshness: 'stale', sampledAt: new Date(Date.now() - 15 * 60_000).toISOString() } : {});
    return {
      metadata: meta,
      cards: [{ id: 'mock-observation', title: '模拟观测 · 信息边界', metadata: meta, fields: [
        { label: '示例 UI 原文', value: '训练概览（模拟文本）', status: 'observed' },
        { label: '当前球员', value: null, status: 'unknown' },
        { label: '球员属性', value: null, status: 'unknown' },
        { label: '原生数据', value: '仅包头诊断示例，未解码足球字段', status: 'observed' },
      ] }],
    };
  }
  async rawUi(options) { return this.snapshot(options); }
  async native(options) { return this.snapshot(options); }
  async events(options) { return this.snapshot(options); }
  // A subscription is owned by the client, never exposed as a model tool call.
  watch(callback, { sessionId, signal, intervalMs = 10_000 } = {}) {
    if (typeof callback !== 'function') throw new Error('监听回调无效。');
    let closed = false;
    const timer = setInterval(() => { if (!closed) callback({ kind: 'mock-observation', metadata: metadata(sessionId) }); }, Math.max(1_000, intervalMs));
    timer.unref?.();
    const stop = () => { closed = true; clearInterval(timer); signal?.removeEventListener('abort', stop); };
    if (signal?.aborted) stop(); else signal?.addEventListener('abort', stop, { once: true });
    return stop;
  }
}

class DisconnectedReaderClient {
  capabilities() {
    return ['status', 'snapshot', 'raw-ui', 'events', 'native', 'player-query'].map(id => ({ id, available: false, synthetic: false, reason: '真实后端尚未接入，能力未知。' }));
  }
  async status() { return { connection: 'unavailable', capabilities: this.capabilities(), synthetic: false, limitations: ['真实后端尚未接入；没有发起网络请求。'] }; }
  async snapshot() { throw new Error('真实后端尚未接入，无法读取游戏信息。'); }
  async rawUi(options) { return this.snapshot(options); }
  async native(options) { return this.snapshot(options); }
  async events(options) { return this.snapshot(options); }
  watch() { throw new Error('真实后端尚未接入，无法订阅。'); }
}

module.exports = { MockReaderClient, DisconnectedReaderClient, metadata, MOCK_LIMITATIONS };

const BUSINESS_CAPABILITIES = Object.freeze(['player_info', 'transfer_analysis', 'tactical_analysis', 'schedule_analysis']);
function businessMetadata(envelope = {}) {
  const source = envelope.source || null;
  const reasons = Array.isArray(envelope.reasons) ? envelope.reasons : [];
  return {
    source: source?.kind || 'unknown', sourceLabel: source ? '业务 Reader · ' + source.kind : '业务来源未知',
    sessionId: source?.session_id ?? null, snapshotId: envelope.snapshot?.snapshot_id ?? null,
    sampledAt: source?.observed_at ?? source?.captured_at ?? null,
    partial: envelope.status !== 'available', limitations: [...reasons], synthetic: source?.synthetic === true,
    freshness: reasons.some(reason => ['capture_not_fresh', 'observation_not_fresh'].includes(reason)) ? 'stale' : !source?.observed_at || reasons.includes('observation_time_unknown') ? 'unknown' : 'current',
    provenance: source, readiness: envelope,
  };
}
function asksManagedTeam(message) {
  if (typeof message !== 'string') return false;
  const value = message.replace(/\s+/g, '');
  if (/适合|推荐|选择|挑选|该选|想去|开始执教/.test(value) || /\b(?:should|could|would|recommend)\b/i.test(message)) return false;
  const chinese = /我(?:们)?(?:现在|目前|当前|这会儿|正在|在|是|到底|究竟|已经|还|刚|正|的){0,4}(?:执掌|执教|带队|管理|主教练|教练)|我(?:们)?(?:现在|目前|当前)?(?:在|是)?哪|我(?:们)?的(?:球队|队|俱乐部)/.test(value) &&
    /球队|俱乐部|哪(?:一|个|支)?队|什么队|哪个队|我的队|我们的队/.test(value) && /哪(?:一|个|支|家)?(?:球队|俱乐部|队)|(?:球队|俱乐部|队)(?:叫|是什么|是谁|是哪|的?名字|名)|队名/.test(value);
  return chinese || /\b(?:which|what)\s+(?:team|club)\b.*\b(?:i|we)\b.*\b(?:manag\w*|coach\w*)\b|\b(?:which|what)\s+is\s+(?:my|our)\s+(?:team|club)\b/i.test(message);
}
function adviceCapability(message, explicit) {
  if (explicit !== undefined) {
    if (!BUSINESS_CAPABILITIES.includes(explicit)) throw new Error('不支持的业务建议能力。');
    return explicit;
  }
  // Explicit match decisions need current schedule evidence even without “我的/当前”.
  // Keep the match noun adjacent to the decision; “下场电影/放音乐” is not a game-data query.
  if (/(?:这场友谊赛|(?:下场|下一场)(?:比赛|球赛|友谊赛)?)[\s，,：:]*(?:我们|咱们)?(?:要不要|该不该|需不需要|能不能|是不是|是否|可以|应该|该|要|能)?(?:先|直接|适当|大幅)?(?:轮换|怎么打|练新人|放(?:不放|掉|弃|一放|一下)?(?=$|[\s？?。，,！!]|吗|呢|吧|还是))/.test(message)) return 'schedule_analysis';
  if (asksManagedTeam(message)) return 'player_info';
  if (!/我的|当前(?:存档|球队|阵容|球员|赛程|战术|页面|界面)|这(?:个球员|个页面|一页|页)|(?:看看|查看|分析)球队|给我引援建议|my (?:team|squad|save)|current save/i.test(message)) return null;
  if (/赛程|轮换|schedule|fixture|congestion/i.test(message)) return 'schedule_analysis';
  if (/转会|引援|预算|transfer|signing/i.test(message)) return 'transfer_analysis';
  if (/战术|阵型|阵容|首发|tactic|lineup|formation/i.test(message)) return 'tactical_analysis';
  if (/球员|属性|存档|页面|界面|这页|这一页|player|squad/i.test(message)) return 'player_info';
  return null;
}
const PREVIEWS = Object.freeze([
  { id: 'schedule', title: '实验性 UI 赛程', key: 'schedule_projection', status: 'experimental_ui_schedule' },
  { id: 'tactics', title: '实验性 UI 战术', key: 'tactics_projection', status: 'experimental_ui_tactics' },
  { id: 'current-page-attributes', title: '当前页面属性 · 身份未知', key: 'current_page_attributes', status: 'experimental_ui_current_page_attributes' },
]);
function previewCard(spec, envelope = {}, now = Date.now()) {
  const projection = envelope[spec.key];
  const nextMatch = spec.id === 'schedule' && envelope.kind === 'next_match' && projection?.kind === 'next_match';
  const expectedStatus = nextMatch ? 'experimental_ui_next_match' : spec.status;
  const title = nextMatch ? '下一场卡片 · 仅当前页面' : spec.title;
  const captured = Date.parse(envelope.provenance?.captured_at);
  const age = now - captured;
  const finiteSummary = spec.id === 'current-page-attributes' && envelope.provenance?.platform === 'windows-x64' && envelope.provenance?.adapter_id === 'footballassistant.windows-finite-ui' && projection?.retention === 'approved_finite_capture_summary' && projection?.snapshot_atomic === false;
  const expiry = Date.parse(envelope.provenance?.expires_at);
  const ageLimit = finiteSummary ? 120_000 : 15_000;
  const summaryExpired = finiteSummary && (!Number.isFinite(expiry) || now > expiry);
  const reasons = Array.isArray(envelope.reasons) ? envelope.reasons : [];
  const stale = reasons.includes('stale_ui_snapshot') || (Number.isFinite(age) && age > ageLimit) || summaryExpired;
  const available = !stale && age >= 0 && age <= ageLimit && envelope.source === 'ui' && envelope.synthetic !== true && projection?.synthetic !== true &&
    envelope.production_ready === false && envelope.status === expectedStatus && projection?.status === expectedStatus && (!nextMatch || (envelope.schedule_complete === false && projection.identity === null && projection.managed_team === null));
  const status = stale ? 'stale' : available ? 'available' : 'unknown';
  const fields = [];
  const add = (label, value, capture = {}) => { if (fields.length < 100 && (typeof value === 'string' || typeof value === 'number')) fields.push({ label, value: String(value).slice(0, 400), status: 'observed', ...capture }); };
  if (available) {
    if (nextMatch) {
      for (const [key, label] of [['date_display', '日期显示'], ['opponent_display', '对手显示'], ['competition_display', '赛事显示']]) add(label, projection[key]);
      for (const label of ['所属球队身份', '主客场', '开球时间', '完整赛程']) fields.push({ label, value: null, status: 'unknown' });
    }
    if (spec.id === 'schedule' && !nextMatch) for (const [i, row] of (Array.isArray(projection.rows) ? projection.rows : []).slice(0, 20).entries()) {
      for (const [key, label] of [['date_display','日期'], ['opponent_display','对手'], ['home_away_display','主客'], ['competition_display','赛事']]) add(`${i + 1} · ${label}`, row[key]);
    }
    if (spec.id === 'tactics') for (const [key, label] of [['formation_display','阵型显示'], ['style_display','风格显示'], ['mentality_display','心态显示']]) add(label, projection[key]);
    if (spec.id === 'current-page-attributes') {
      fields.push({ label: '球员身份（不可归属某球员）', value: null, status: 'unknown' });
      for (const group of (Array.isArray(projection.groups) ? projection.groups : []).slice(0, 5)) for (const row of (Array.isArray(group.rows) ? group.rows : []).slice(0, 50)) add(`${String(group.category_display).slice(0, 60)} · ${String(row.label_display).slice(0, 60)}`, row.value, finiteSummary ? { captureFreshness: row.capture_freshness, capturedAt: row.field_provenance?.capture_started_at, captureFinishedAt: row.field_provenance?.capture_finished_at, chunkIndex: row.field_provenance?.chunk_index } : {});
    }
  }
  return { id: spec.id, title, status, fields, identity: null, ...(nextMatch ? { kind: 'next_match', scheduleComplete: false } : {}), metadata: {
    source: 'ui', sourceLabel: title, sessionId: envelope.provenance?.session_id ?? null,
    sampledAt: envelope.provenance?.captured_at ?? null, partial: true, synthetic: false,
    freshness: status === 'available' ? (finiteSummary ? 'capture_summary' : 'current') : status, ...(finiteSummary ? { snapshotAtomic: false, captureProgress: projection.progress, expiresAt: envelope.provenance.expires_at } : {}), limitations: [
      '仅本机 UI 预览，不代表后台全量事实；不会自动调用模型。',
      ...(nextMatch ? ['仅俱乐部概况中下一场卡片的三项显示；所属球队身份未知，不绑定你的球队。', '主客场、开球时间与完整赛程未知，不能据此计算赛程密度。'] : []),
      ...(spec.id === 'current-page-attributes' ? ['身份未知，不绑定任何球员，不用于个体建议。'] : []),
      ...(Array.isArray(projection?.limitations) ? projection.limitations : []), ...reasons,
    ],
  } };
}
class RealReaderClient {
  constructor({ request } = {}) {
    if (typeof request !== 'function') throw new Error('需要受控主进程连接。');
    this.request = request;
  }
  capabilities(envelope = {}) {
    return BUSINESS_CAPABILITIES.map(id => ({ id, available: envelope.production_ready === true && envelope.capabilities?.[id]?.ready === true,
      synthetic: envelope.source?.synthetic === true, reason: (envelope.capabilities?.[id]?.missing_requirements || envelope.reasons || ['业务能力尚未验证']).join('、') }));
  }
  async status({ signal } = {}) {
    const envelope = await this.request('/v1/reader/business/status', undefined, { signal });
    return { connection: 'connected', metadata: businessMetadata(envelope), capabilities: this.capabilities(envelope), readiness: envelope };
  }
  async match({ signal } = {}) {
    return this.request('/v1/reader/match', undefined, { signal });
  }
  async offseasonCalendar({ clubUid, start, end, signal } = {}) {
    return this.request(calendarEndpoint(clubUid, start, end), undefined, { signal, timeoutMs: 45_000 });
  }
  async snapshot({ signal } = {}) {
    const envelope = await this.request('/v1/reader/business/snapshot', undefined, { signal });
    const meta = businessMetadata(envelope);
    // A partial verified snapshot may contain useful facts without satisfying every advice capability.
    const snapshot = envelope.snapshot;
    const fields = [];
    if (snapshot && envelope.production_ready === true && !meta.synthetic && meta.freshness === 'current') {
      const visit = (value, ref) => {
        if (fields.length >= 100) return;
        if (value !== null && typeof value === 'object') for (const [key, child] of Object.entries(value)) visit(child, ref + '/' + key);
        else fields.push({ label: ref, value, status: value === null ? 'unknown' : 'observed' });
      };
      for (const [key, value] of Object.entries(snapshot)) if (!['source', 'schema_version'].includes(key)) visit(value, '/' + key);
    }
    return { metadata: meta, readiness: envelope, cards: fields.length ? [{ id: snapshot.snapshot_id, title: '已读取业务事实', metadata: meta, fields }] : [] };
  }
  async windowsDiscovery({ signal } = {}) {
    return this.request('/v1/reader/windows-discovery', undefined, { signal });
  }
  async importWindowsDiscovery(input, { signal } = {}) {
    return this.request('/v1/reader/windows-discovery/import', validateImport(input), { signal, timeoutMs: 5_000 });
  }
  async importWindowsDiscoveryText(rawJson, { signal } = {}) {
    if (typeof rawJson !== 'string' || !rawJson.trimStart().startsWith('{') || Buffer.byteLength(rawJson, 'utf8') > 32768) {
      try { await this.clearWindowsDiscovery({ signal }); }
      catch { throw new Error('导入文本无效，且清除失败；服务端可能仍保留上次导入。'); }
      throw new Error('诊断导入仅接受不超过 32 KiB 的 JSON 文本，不接受文件路径；上次导入已清除。');
    }
    // Preserve duplicate keys exactly for the backend strict JSON parser.
    return this.request('/v1/reader/windows-discovery/import', undefined, { signal, timeoutMs: 5_000, rawJson });
  }
  async clearWindowsDiscovery({ signal } = {}) {
    return this.request('/v1/reader/windows-discovery', undefined, { signal, method: 'DELETE' });
  }
  async setCaptureProfile(profile, { signal } = {}) {
    if (!['schedule', 'current_page_attributes', 'tactics', 'next_match'].includes(profile)) throw new Error('不支持的页面读取类型。');
    return this.request('/v1/reader/capture-profile', { profile }, { signal, timeoutMs: 5_000 });
  }
  async captureProfileStatus({ signal } = {}) {
    return this.request('/v1/reader/capture-profile', undefined, { signal });
  }
  async uiChangePreview({ signal } = {}) {
    return this.request('/v1/reader/ui-change-preview', undefined, { signal });
  }
  async previews({ signal } = {}) {
    return Promise.all(PREVIEWS.map(async spec => {
      try {
        const card = previewCard(spec, await this.request(`/v1/reader/${spec.id}`, undefined, { signal }));
        return { ...card, transport: 'connected', statusReason: card.status === 'unknown' ? 'projection_unavailable' : null };
      }
      catch (error) {
        if (signal?.aborted) throw error;
        const card = previewCard(spec);
        card.transport = error.code === 'unsupported' ? 'connected' : 'unavailable';
        card.statusReason = error.code === 'unsupported' ? 'endpoint_unavailable' : 'connection_failed';
        card.error = error.message;
        card.metadata.limitations.push(error.message); return card;
      }
    }));
  }
  async reply({ message, conversationId, capability, adviceMode = 'native', signal }) {
    // Explicit diagnostic questions are deterministic read-only tooling, never model context.
    if (asksImportedDiagnostic(message)) return diagnosticReply(await this.windowsDiscovery({ signal }), conversationId);
    if (/(比分|比赛情况|比赛怎么样|比赛进展|score)/i.test(message)) {
      const view = matchView(await this.match({ signal }));
      if (!view) return { text: '当前没有可用的新鲜比赛快照。', conversationId, cards: [],
        metadata: { source: 'native_match_hook', synthetic: false, freshness: 'unknown', partial: true, limitations: ['比赛数据不可用或已过期。'] } };
      const card = matchCard(view);
      return { text: `当前比分：${view.home} ${view.h} : ${view.a} ${view.away}。`, conversationId,
        metadata: card.metadata, cards: [card] };
    }
    if (capability && adviceMode === 'ui_evidence') {
      const result = await this.request('/v1/agent/ui-advice', { message, conversation_id: conversationId, capability }, { signal });
      const provenance = result.provenance;
      return { text: result.reply, conversationId: result.conversation_id, cards: [], metadata: {
        source: 'ui', sourceLabel: 'Alpha · UI 采样建议（非后台全量数据）',
        sessionId: provenance?.session_id ?? null, snapshotId: provenance?.event_id ?? null,
        sampledAt: provenance?.captured_at ?? null, partial: true, synthetic: false,
        freshness: result.status === 'generated' ? (provenance?.platform === 'windows-x64' && provenance?.adapter_id === 'footballassistant.windows-finite-ui' ? 'capture_summary' : 'current') : 'unknown',
        page: result.page, provenance, limitations: [...(result.limitations || []), ...(result.reasons || [])],
        readiness: { production_ready: false, mode: 'ui_evidence' },
      } };
    }
    if (capability) {
      const result = await this.request('/v1/agent/business-advice', { message, conversation_id: conversationId, capability }, { signal });
      const meta = businessMetadata(result.readiness);
      meta.snapshotId = result.facts?.[0]?.snapshot_id ?? null;
      meta.limitations.push(...(result.missing_requirements || []));
      const facts = result.status === 'generated' && result.readiness?.production_ready === true && meta.freshness === 'current' && !meta.synthetic ? result.facts || [] : [];
      return { text: result.reply, conversationId: result.conversation_id, metadata: meta,
        cards: facts.length ? [{ id: 'business-facts', title: '已读取事实 · 建议见回复', metadata: meta,
          fields: facts.slice(0, 100).map(fact => ({ label: `${fact.snapshot_id} ${fact.field_ref}`, value: fact.value, status: 'observed' })) }] : [] };
    }
    const result = await this.request('/v1/chat', { message, conversation_id: conversationId }, { signal });
    return { text: result.reply, conversationId: result.conversation_id, metadata: { ...businessMetadata(), source: 'agent', sourceLabel: 'AI 对话 · 非当前存档事实', limitations: ['普通对话不代表已读取当前存档业务数据。'] }, cards: [] };
  }
}
module.exports.RealReaderClient = RealReaderClient;
module.exports.businessMetadata = businessMetadata;
module.exports.adviceCapability = adviceCapability;

module.exports.previewCard = previewCard;
module.exports.PREVIEWS = PREVIEWS;
