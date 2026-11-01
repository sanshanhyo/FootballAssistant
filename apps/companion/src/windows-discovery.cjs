'use strict';

const LIMIT = 32768;
const WARNING = '仅手动导入的部分显示诊断；来源身份、页面身份与球员身份未验证，时效未知。不是当前游戏事实，不用于球员建议。';
function plain(value) { return value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype; }
function validateImport(input) {
  if (!plain(input) || Object.keys(input).some(key => !['capture', 'expected_source', 'operator_context'].includes(key)) || !plain(input.capture) || !plain(input.expected_source)) throw Error('请粘贴单个 capture 和 expected_source JSON 对象，不接受文件路径。');
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
function diagnosticReply(envelope, conversationId) {
  const p = envelope?.projection;
  const field = p?.field_provenance?.displayed_position;
  const value = p?.fields?.displayed_position;
  const available = envelope?.status === 'manual_import_snapshot' && envelope.import_mode === 'manual_single_event' &&
    p?.status === 'partial_display_state' && p.partial === true && p.source_identity_unverified === true &&
    p.page_identity_verified === false && p.business_identity_known === false && p.entity_id === null &&
    p.snapshot_atomic === false && p.source_freshness === 'unknown' && p.captured_at === null &&
    typeof value === 'string' && value.length > 0 && value.length <= 128 && field?.semantic_identity_verified === false &&
    field.association === 'fixed_same_container_same_event' && field.panel_index === 0 &&
    canonicalPath(field.label_path) && canonicalPath(field.value_path) && canonicalPath(field.container_path);
  const metadata = { source: 'manual_import', sourceLabel: 'Windows 手动导入诊断 · 非实时',
    sessionId: null, sampledAt: null, partial: true, synthetic: null, freshness: 'unknown',
    identity: null, limitations: [WARNING], readiness: { production_ready: false, mode: 'manual_import' } };
  const fields = available ? [
    { label: '位置显示（非球员事实）', value, status: 'observed' },
    { label: '标签来源路径', value: field.label_path, status: 'observed' },
    { label: '值来源路径', value: field.value_path, status: 'observed' },
    { label: '共同容器路径', value: field.container_path, status: 'observed' },
    { label: '球员身份', value: null, status: 'unknown' },
  ] : [];
  return { conversationId, text: available ? `导入诊断中的位置显示：${value}。\n${WARNING}` : `没有可用的手动导入位置诊断。\n${WARNING}`,
    metadata, cards: available ? [{ id: 'windows-discovery-import', title: '手动导入 · 部分位置显示', metadata, identity: null, fields }] : [] };
}
module.exports = { validateImport, asksImportedDiagnostic, diagnosticReply, WARNING, LIMIT };
