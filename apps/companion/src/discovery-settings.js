'use strict';
// Manual JSON import only. This renderer neither selects files nor reads the game.
(function (root) {
  const WARNING = '手动导入、局部显示；身份未验证，新鲜度未知。不能据此确认当前球员、完整资料或提供个体建议。';
  const MAX_INPUT_BYTES = 32768;
  function parseInput(captureText, sourceText) {
    if (typeof captureText !== 'string' || typeof sourceText !== 'string' ||
        captureText.length + sourceText.length > MAX_INPUT_BYTES ||
        new TextEncoder().encode(captureText + sourceText).byteLength > MAX_INPUT_BYTES) throw Error('两段 JSON 合计不得超过 32 KiB。');
    let capture, expected_source;
    try { capture = JSON.parse(captureText); expected_source = JSON.parse(sourceText); }
    catch { throw Error('请粘贴两个有效的 JSON 对象；不接受文件路径。'); }
    if (![capture, expected_source].every(value => value && typeof value === 'object' && !Array.isArray(value))) throw Error('采集与预期来源都必须是单个 JSON 对象。');
    // Preserve raw JSON (including duplicate keys) for the backend's strict parser.
    const input = `{"capture":${captureText},"expected_source":${sourceText}}`;
    if (new TextEncoder().encode(input).byteLength > MAX_INPUT_BYTES) throw Error('请求 JSON 不得超过 32 KiB。');
    return input;
  }
  function mountDiscoverySettings({ document, api }) {
    const $ = id => document.getElementById(id);
    let busy = false;
    const buttons = ['discovery-import', 'discovery-refresh', 'discovery-clear'];
    function controls() { for (const id of buttons) $(id).disabled = busy; }
    function field(label, text) {
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = label; detail.textContent = text;
      $('discovery-fields').append(term, detail);
    }
    function render(value) {
      $('discovery-fields').replaceChildren();
      $('discovery-warning').textContent = WARNING;
      if (value?.status !== 'manual_import_snapshot' || value.import_mode !== 'manual_single_event') {
        $('discovery-status').textContent = '没有可显示的已导入诊断；未读取游戏。'; return;
      }
      $('discovery-status').textContent = '已导入一次手动诊断，仅展示已校验的局部显示字段。';
      const projection = value.projection;
      if (projection?.status !== 'partial_display_state' || projection.partial !== true ||
          projection.source_identity_unverified !== true || projection.page_identity_verified !== false ||
          projection.business_identity_known !== false || projection.entity_id !== null ||
          projection.snapshot_atomic !== false || projection.source_freshness !== 'unknown' || projection.captured_at !== null) {
        $('discovery-status').textContent = '诊断响应不符合局部显示契约，未展示字段。'; return;
      }
      const position = projection.fields?.displayed_position;
      const provenance = projection.field_provenance?.displayed_position;
      const pathKeys = [['container_path', '同容器来源路径'], ['label_path', '位置标签来源路径'], ['value_path', '位置显示值来源路径']];
      const validPath = path => typeof path === 'string' && path.length <= 127 &&
        /^(?:0|[1-9][0-9]{0,2})(?:\/(?:0|[1-9][0-9]{0,2})){0,32}$/.test(path) &&
        path.split('/').every(index => Number(index) <= 511);
      const verifiedDisplay = typeof position === 'string' && position.length > 0 && position.length <= 128 &&
        provenance?.semantic_identity_verified === false && provenance.association === 'fixed_same_container_same_event' &&
        provenance.panel_index === 0 && pathKeys.every(([key]) => validPath(provenance[key]));
      if (verifiedDisplay) {
        field('位置显示（不绑定球员）', position);
        for (const [key, label] of pathKeys) field(label, provenance[key]);
      } else field('位置显示', '未知 / 本次导入没有完整的字段来源');
      field('身份 / 新鲜度', '未验证 / 未知');
    }
    async function run(action, clearInputs = false) {
      if (busy) return;
      busy = true; controls();
      // Never leave previous output displayed as the result of a failed new operation.
      $('discovery-fields').replaceChildren();
      $('discovery-status').textContent = '正在处理本机手动诊断…';
      try {
        const result = await action();
        if (!result?.ok) throw Error(result?.error || '诊断操作失败。');
        render(result.value);
        if (clearInputs) { $('discovery-capture').value = ''; $('discovery-source').value = ''; }
      } catch (error) {
        $('discovery-status').textContent = (typeof error?.message === 'string' ? error.message : '诊断操作失败。').slice(0, 400);
      } finally { busy = false; controls(); }
    }
    $('discovery-import').addEventListener('click', () => run(async () => {
      let input;
      try { input = parseInput($('discovery-capture').value, $('discovery-source').value); }
      catch (validation) {
        // Explicit replacement intent invalidates the previous imported snapshot even
        // when this renderer cannot send the malformed/oversized replacement body.
        try {
          const cleared = await api.windowsDiscoveryClear();
          if (!cleared?.ok) throw Error('clear_failed');
        } catch { throw Error(`${validation.message} 清除旧导入失败，服务器上先前的导入可能仍然存在；请手动清除。`); }
        throw Error(`${validation.message} 先前的导入已清除；没有发送导入请求。`);
      }
      return api.windowsDiscoveryImport(input);
    }, true));
    $('discovery-refresh').addEventListener('click', () => run(() => api.windowsDiscoveryGet()));
    $('discovery-clear').addEventListener('click', () => run(() => api.windowsDiscoveryClear(), true));
    controls();
    // No startup fetch, timer, subscription, automatic import or model request.
    return { get busy() { return busy; } };
  }
  if (typeof module === 'object' && module.exports) module.exports = { mountDiscoverySettings, parseInput, WARNING, MAX_INPUT_BYTES };
  else root.CompanionDiscoverySettings = { mountDiscoverySettings };
})(typeof window === 'object' ? window : globalThis);
