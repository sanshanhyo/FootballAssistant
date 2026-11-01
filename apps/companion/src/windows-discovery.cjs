'use strict';

const LIMIT = 32768;
const WARNING = '仅手动导入的部分显示诊断；来源身份、页面身份与球员身份未验证，时效未知。不是当前游戏事实，不用于球员建议。';
function plain(value) { return value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype; }
function validateImport(input) {
  if (!plain(input) || Object.keys(input).some(key => !['capture', 'expected_source', 'operator_context', 'projection_mode'].includes(key)) || !plain(input.capture) || !plain(input.expected_source)) throw Error('请粘贴单个 capture 和 expected_source JSON 对象，不接受文件路径。');
  if (Object.hasOwn(input, 'projection_mode') && input.projection_mode !== 'goalkeeper_row0') throw Error('不支持的显式诊断投影模式。');
  const encoded = JSON.stringify(input);
  if (Buffer.byteLength(encoded, 'utf8') > LIMIT) throw Error('诊断导入超过 32 KiB。');
  return JSON.parse(encoded); // Own a JSON-only immutable-in-flight snapshot, not renderer object references.
}
function asksImportedDiagnostic(message) {
  return typeof message === 'string' && /导入.{0,8}诊断|诊断.{0,8}导入|imported\s+(?:windows\s+)?diagnostic/i.test(message);
}
function canonicalPath(value) {
  return typeof value === 'string' && value.length <= 127 && value.split('/').length <= 33 && /^(?:0|[1-9]\d{0,2})(?:\/(?:0|[1-9]\d{0,2}))*$/.test(value) && value.split('/').every(part => Number(part) <= 511);
}
const ROW_FOCUS = '0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0';
const ROW_ROOT = ROW_FOCUS + '/2/0/0/0/0';
const ROW_TITLE = ROW_FOCUS + '/0';
const ROW_LABEL = ROW_ROOT + '/0/0/0/0/0/0/0/0/0';
const ROW_VALUE = ROW_ROOT + '/0/0/0/0/0/0/1/1/0/0/0/0/0/0';
const ROW_LABELS = new Set(['出击(倾向)', '传球', '大脚开球', '反应', '拦截传中', '拳击球(倾向)', '手控球', '手抛球', '停球', '一对一', '意外性', '指挥防守', '制空范围']);
function rowDisplay(p) {
  const row = p?.fields?.displayed_attribute, provenance = p?.field_provenance?.displayed_attribute;
  return p?.projection_mode === 'goalkeeper_row0' && Object.keys(p.fields || {}).join() === 'displayed_attribute' &&
    Object.keys(p.field_provenance || {}).join() === 'displayed_attribute' && row?.category_display === '守门' &&
    ROW_LABELS.has(row.label_display) && row.row_index === 0 && Number.isInteger(row.value) && row.value >= 1 && row.value <= 20 &&
    typeof row.value_display === 'string' && row.value_display === String(row.value) &&
    provenance?.semantic_identity_verified === false && provenance.association === 'fixed_same_row_same_event' &&
    provenance.panel_index === 0 && provenance.category_title_path === ROW_TITLE && provenance.label_path === ROW_LABEL &&
    provenance.value_path === ROW_VALUE && provenance.row_root === ROW_ROOT && provenance.container_path === ROW_FOCUS &&
    typeof provenance.nonce === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(provenance.nonce) &&
    provenance.nonce !== '00000000-0000-0000-0000-000000000000' && p.source?.nonce === provenance.nonce &&
    p.source.panel_index === 0 && p.source.focus_path === ROW_FOCUS;
}
function diagnosticReply(envelope, conversationId) {
  const p = envelope?.projection;
  const field = p?.field_provenance?.displayed_position;
  const value = p?.fields?.displayed_position;
  const common = envelope?.status === 'manual_import_snapshot' && envelope.import_mode === 'manual_single_event' &&
    p?.status === 'partial_display_state' && p.partial === true && p.source_identity_unverified === true &&
    p.page_identity_verified === false && p.business_identity_known === false && p.entity_id === null &&
    p.snapshot_atomic === false && p.source_freshness === 'unknown' && p.captured_at === null;
  const available = common && !Object.hasOwn(p, 'projection_mode') &&
    !Object.hasOwn(p.fields || {}, 'displayed_attribute') && !Object.hasOwn(p.field_provenance || {}, 'displayed_attribute') &&
    typeof value === 'string' && value.length > 0 && value.length <= 128 && field?.semantic_identity_verified === false &&
    field.association === 'fixed_same_container_same_event' && field.panel_index === 0 &&
    canonicalPath(field.label_path) && canonicalPath(field.value_path) && canonicalPath(field.container_path);
  const metadata = { source: 'manual_import', sourceLabel: 'Windows 手动导入诊断 · 非实时',
    sessionId: null, sampledAt: null, partial: true, synthetic: null, freshness: 'unknown',
    identity: null, limitations: [WARNING], readiness: { production_ready: false, mode: 'manual_import' } };
  if (common && rowDisplay(p)) {
    const row = p.fields.displayed_attribute, provenance = p.field_provenance.displayed_attribute;
    const fields = [
      { label: '分类显示（非球员事实）', value: row.category_display, status: 'observed' },
      { label: '属性标签显示', value: row.label_display, status: 'observed' },
      { label: '属性值显示', value: row.value_display, status: 'observed' },
      { label: '分类标题来源路径', value: provenance.category_title_path, status: 'observed' },
      { label: '属性标签来源路径', value: provenance.label_path, status: 'observed' },
      { label: '属性值来源路径', value: provenance.value_path, status: 'observed' },
      { label: '球员身份', value: null, status: 'unknown' },
    ];
    return { conversationId, text: `导入诊断中的单行显示：${row.category_display} · ${row.label_display} ${row.value_display}。\n${WARNING}`,
      metadata, cards: [{ id: 'windows-discovery-import', title: '手动导入 · 单行属性显示', metadata, identity: null, fields }] };
  }
  const fields = available ? [
    { label: '位置显示（非球员事实）', value, status: 'observed' },
    { label: '标签来源路径', value: field.label_path, status: 'observed' },
    { label: '值来源路径', value: field.value_path, status: 'observed' },
    { label: '共同容器路径', value: field.container_path, status: 'observed' },
    { label: '球员身份', value: null, status: 'unknown' },
  ] : [];
  return { conversationId, text: available ? `导入诊断中的位置显示：${value}。\n${WARNING}` : `没有可用的手动导入显示诊断。\n${WARNING}`,
    metadata, cards: available ? [{ id: 'windows-discovery-import', title: '手动导入 · 部分位置显示', metadata, identity: null, fields }] : [] };
}
module.exports = { validateImport, asksImportedDiagnostic, diagnosticReply, WARNING, LIMIT };
