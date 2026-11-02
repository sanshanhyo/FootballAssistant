'use strict';
// Only explicit club-scoped ranges are supported; loaded buckets are not a complete calendar.
function calendarEndpoint(clubUid, start, end) {
  if (!Number.isSafeInteger(clubUid) || clubUid <= 0 || clubUid >= 4294967295) throw new Error('Invalid club UID');
  const parse = value => {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error('Invalid calendar date');
    const date = new Date(value + 'T00:00:00Z');
    if (!Number.isFinite(date.valueOf()) || date.toISOString().slice(0, 10) !== value || date.getUTCFullYear() < 1901 || date.getUTCFullYear() > 2100) throw new Error('Invalid calendar date');
    return date;
  };
  const first = parse(start), last = parse(end);
  const days = (last - first) / 86400000;
  if (first.getUTCFullYear() !== last.getUTCFullYear() || days < 0 || days >= 30) throw new Error('Invalid calendar range');
  return `/v1/reader/offseason?club_uid=${clubUid}&start=${start}&end=${end}`;
}
function isCalendarEndpoint(endpoint) {
  if (typeof endpoint !== 'string') return false;
  const match = /^\/v1\/reader\/offseason\?club_uid=([1-9]\d{0,9})&start=(\d{4}-\d{2}-\d{2})&end=(\d{4}-\d{2}-\d{2})$/.exec(endpoint);
  if (!match) return false;
  try { return calendarEndpoint(Number(match[1]), match[2], match[3]) === endpoint; } catch { return false; }
}
module.exports = { calendarEndpoint, isCalendarEndpoint };

function offseasonEndpoint(clubUid = 0, personUid = 0) {
  if (!Number.isSafeInteger(clubUid) || clubUid < 0 || clubUid >= 4294967295 ||
      !Number.isSafeInteger(personUid) || personUid < 0 || personUid > 2147483647) throw Error('Invalid offseason selector');
  return `/v1/reader/offseason?club_uid=${clubUid}&person_uid=${personUid}`;
}
function isOffseasonEndpoint(endpoint) {
  if (typeof endpoint !== 'string') return false;
  const match = /^\/v1\/reader\/offseason\?club_uid=(0|[1-9]\d{0,9})&person_uid=(0|[1-9]\d{0,9})$/.exec(endpoint);
  if (!match) return false;
  try { return offseasonEndpoint(Number(match[1]), Number(match[2])) === endpoint; } catch { return false; }
}
function offseasonIntent(message) {
  if (typeof message !== 'string') return null;
  // Existing explicit/automatic calendar routing owns schedule requests.
  if (/(赛程|schedule|fixtures?)/i.test(message)) return null;
  const readUid = (label, max) => {
    const markers = [...message.matchAll(new RegExp(label + '\\s*UID', 'gi'))];
    if (!markers.length) return 0;
    if (markers.length !== 1) return null;
    const rest = message.slice(markers[0].index + markers[0][0].length);
    const match = /^\s*[:：#]?\s*([1-9]\d{0,9})(?![\w.\-])/u.exec(rest);
    return match && Number(match[1]) <= max ? Number(match[1]) : null;
  };
  const namedMarkers = [...message.matchAll(/(?:球员|人物|person|player|俱乐部|club)\s*UID/gi)].length;
  if ([...message.matchAll(/UID/gi)].length !== namedMarkers) return { error: '请明确标注球员 UID 或俱乐部 UID，且每类只提供一个编号。' };
  const personUid = readUid('(?:球员|人物|person|player)', 2147483647);
  const clubUid = readUid('(?:俱乐部|club)', 4294967294);
  if (personUid === null || clubUid === null) return { error: '请只提供一个有效的球员 UID 和／或俱乐部 UID，不能用姓名或重复编号代替。' };
  if (personUid || clubUid) return { personUid, clubUid, kind: personUid ? 'player' : 'team' };
  if (/游戏日期|游戏.{0,6}(?:几号|日期)|存档.{0,6}(?:日期|几号)|(?:game|save)\s+date/i.test(message)) return { personUid: 0, clubUid: 0, kind: 'date' };
  if (/(?:球队|经理|俱乐部)候选|人类经理/.test(message) || /^(?:看看|查看|读取)?我的球队[？?。！!]*$/.test(message.trim())) return { personUid: 0, clubUid: 0, kind: 'team' };
  if (/(?:查看|看看|读取|查询|分析|显示).{0,20}(?:球员|属性|身高|生日|合同)/.test(message)) return { error: '请提供明确的球员 UID（例如“读取球员 UID: 123”）。不会按名字猜身份，也不会用旧页面文本充当当前球员数据。' };
  return null;
}
function offseasonReply(envelope, intent, conversationId, now = Date.now()) {
  const meta = { source: 'native_offseason_reader', sourceLabel: '赛外内存读取 · 实验', synthetic: false,
    partial: true, freshness: 'unknown', limitations: ['仅固定构建的有界读取；候选不等于当前执教身份或完整阵容。', '未观测字段保持未知；工资币种与周期未验证，不提供金额判断。'] };
  const result = (text, cards = []) => ({ text, conversationId, metadata: meta, cards });
  if (intent.error) return result(intent.error);
  const value = envelope?.snapshot;
  const fresh = time => typeof time === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(time) && Number.isFinite(Date.parse(time)) && now - Date.parse(time) >= -5000 && now - Date.parse(time) <= 30000;
  if (envelope?.producerVerified !== true || value?.synthetic !== false || value?.state !== 'fresh_partial' ||
      value?.producer?.id !== 'footballassistant.offseason-reader' || value?.producer?.version !== '0.1.0' || value?.producer?.protocol !== 'fa-offseason/0.1' ||
      !Number.isSafeInteger(value?.process?.pid) || value.process.pid <= 0 || !Number.isFinite(Date.parse(value?.process?.startedAt)) || Date.parse(value.process.startedAt) > Date.parse(value.capturedAt) ||
      !/^[a-f0-9]{64}$/.test(value?.process?.sessionId || '') || value?.binary?.module !== 'game_plugin.dll' || value.binary.matched !== true ||
      value.binary.sha256 !== 'bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f' ||
      envelope?.status !== 'partial' || value?.schema !== 'fa-offseason/0.1' || value.status !== 'partial' || !fresh(value.capturedAt)) {
    return result('当前没有可用的新鲜赛外数据。请先启用 Windows Reader，并在游戏载入存档后点击“验证连接”；不会回退到模拟数据或旧 UI 采样。');
  }
  const fields = [], label = (name, v) => fields.push({ label: name, value: v ?? null, status: v == null ? 'unknown' : 'observed' });
  const safeText = text => typeof text === 'string' && text.trim() && text.length <= 256 && !/[\u0000-\u001f]/.test(text) ? text : null;
  const uid = number => Number.isSafeInteger(number) && number > 0 && number < 4294967295;
  const date = text => typeof text === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(text) && Number.isFinite(Date.parse(text + 'T00:00:00Z')) && new Date(text + 'T00:00:00Z').toISOString().slice(0,10) === text ? text : null;
  if (intent.kind === 'date' && value.date?.status === 'experimental' && fresh(value.date.observedAt)) label('游戏日期（实验）', date(value.date.date));
  if (intent.personUid) {
    const player = value.player?.value;
    if (player?.status !== 'experimental' || player.uid !== intent.personUid || !fresh(value.player.observedAt)) return result('该球员 UID 当前没有可核验的新鲜结果；不会改查其他球员或猜测属性。');
    label('球员 UID', player.uid); label('姓名', safeText(player.displayName));
    for (const [key,name] of [['reflexesRaw','反应'],['handlingRaw','手控球'],['anticipationRaw','预判'],['jumpingRaw','弹跳']]) {
      const raw = player.details?.[key];
      label(name, Number.isInteger(raw) && raw > 0 && raw <= 100 ? `${Math.min(20,Math.max(1,Math.round(raw/5)))} / 20（原值 ${raw}）` : null);
    }
    const height = player.details?.heightCm;
    label('身高（cm）', Number.isInteger(height) && height >= 100 && height <= 250 ? height : null);
    label('出生日期', date(player.details?.dateOfBirth));
    if (player.contract?.status === 'experimental') { label('合同开始日期（实验）',date(player.contract.startDate)); label('合同结束日期（实验）',date(player.contract.endDate)); }
  } else if (intent.kind === 'team') {
    const candidates = value.managerCandidates;
    if (candidates?.status === 'experimental_candidates_incomplete' && Array.isArray(candidates.candidates) && candidates.candidates.length <= 4) {
      for (const candidate of candidates.candidates) if (uid(candidate.uid) && uid(candidate.clubUid) && safeText(candidate.name) && safeText(candidate.clubName) && (!intent.clubUid || candidate.clubUid === intent.clubUid)) {
        label('经理／俱乐部关联候选（非当前身份）', `${candidate.name}（UID ${candidate.uid}）— ${candidate.clubName}（俱乐部 UID ${candidate.clubUid}）`);
      }
    }
    const team = value.team;
    if (intent.clubUid && team?.status === 'experimental_candidates_incomplete' && fresh(team.observedAt) && Array.isArray(team.players) && team.players.length <= 256) {
      for (const player of team.players) if (player.clubUid === intent.clubUid && uid(player.uid) && safeText(player.name) && player.linkStatus === 'exact_types') label('球员关联候选', `${player.name}（UID ${player.uid}）`);
    }
  }
  if (!fields.some(field => field.status === 'observed')) return result('读取已返回，但所请求的数据仍未知或未验证；不能确认当前球队、完整阵容或球员属性。');
  meta.freshness = 'current'; meta.sampledAt = value.capturedAt; meta.sessionId = value.process.sessionId;
  meta.limitations.push('会话标识只表示进程启动实例，不是存档身份。');
  const card = { id: 'offseason-observation', title: '赛外读取结果（实验／部分）', status: 'available', metadata: meta, fields };
  const summary = intent.kind === 'date' ? `实验读取的游戏日期：${fields[0].value ?? '未知'}。` : intent.personUid ? `已返回球员 UID ${intent.personUid} 的部分实验字段，未知项未补全。` : '已返回经理／球队关联候选，不代表已确认当前执教身份或完整阵容。';
  return result(summary, [card]);
}
Object.assign(module.exports, { offseasonEndpoint, isOffseasonEndpoint, offseasonIntent, offseasonReply });
