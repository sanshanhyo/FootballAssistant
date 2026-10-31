'use strict';
// UI never chooses filesystem paths for deployment; the main-process dialog does.
(function (root) {
  function mountBridgeSettings({ document, api }) {
    const $ = id => document.getElementById(id);
    let state = null, busy = false, generation = 0;
    const consentIds = ['bridge-consent-copy', 'bridge-consent-signing', 'bridge-consent-jit'];
    const blocked = new Set(['unsupported_platform', 'payload_unavailable', 'packaged_backend_required']);
    function resetConsent() { for (const id of [...consentIds, 'bridge-consent-rollback']) $(id).checked = false; }
    function buttons() {
      const unavailable = !state || blocked.has(state.state);
      $('bridge-refresh').disabled = busy;
      $('bridge-select').disabled = busy || unavailable;
      $('bridge-enable').disabled = busy || !state?.canEnable || !state.planId || !consentIds.every(id => $(id).checked === true);
      $('bridge-rollback').disabled = busy || state?.canRollback !== true || $('bridge-consent-rollback').checked !== true;
    }
    function appendField(label, value) {
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = label; detail.textContent = typeof value === 'string' ? value : '尚未确认';
      $('bridge-plan-fields').append(term, detail);
    }
    function render(value) {
      state = value; resetConsent();
      const labels = { packaged_backend_required: '桥接部署仅可在打包后的应用中使用；开发模式不会部署。', rollback_pending: '私有副本已撤销，后台配置尚待清理；可再次撤销以完成。', disabled: '桥接当前未启用；原始游戏未改动。', unsupported_platform: '当前平台不支持游戏桥接部署。Windows 不能启用真实页面读取。', payload_unavailable: '当前安装包缺少已审计桥接 payload，无法部署。', deployed: '私有副本桥接已部署；尚不代表游戏数据已连接。', rolled_back: '桥接部署已撤销；原始游戏未改动。' };
      $('bridge-status').textContent = labels[value.state] || value.message || '请先选择游戏 App 并验证部署条件。';
      $('bridge-candidates').replaceChildren();
      for (const candidate of Array.isArray(value.candidates) ? value.candidates : []) {
        const item = document.createElement('li'); item.textContent = `发现本机游戏：${String(candidate)}（仍需选择并验证）`; $('bridge-candidates').append(item);
      }
      $('bridge-plan').hidden = !value.planId;
      $('bridge-plan-fields').replaceChildren(); $('bridge-plan-changes').replaceChildren();
      if (value.planId) {
        appendField('原始游戏', value.gamePath); appendField('游戏版本', value.gameVersion); appendField('架构', value.architecture); appendField('私有副本位置', value.privateRoot);
        for (const change of Array.isArray(value.changes) ? value.changes : []) { const item = document.createElement('li'); item.textContent = String(change); $('bridge-plan-changes').append(item); }
      }
      $('bridge-result').textContent = value.privateRoot && !value.planId ? `私有副本位置：${value.privateRoot}。应用不会启动或结束 FM。` : '';
      if (value.restartRequired === true) $('bridge-result').textContent += ' 外部后台未被重启；请在该服务所在位置手动重启后生效。';
      $('bridge-rollback-section').hidden = value.canRollback !== true;
      buttons();
    }
    async function run(action) {
      if (busy) return;
      busy = true; const current = ++generation; buttons();
      try {
        const result = await action();
        if (current !== generation) return;
        if (!result?.ok) throw Error(result?.error || '桥接操作失败。');
        if (result.value?.cancelled) { resetConsent(); return; }
        render(result.value || { state: 'unavailable', message: '未获得部署状态，未执行启用。' });
      } catch (error) {
        resetConsent();
        // Failure invalidates the old plan. Retry must re-inspect/re-plan explicitly.
        state = { state: 'error', canEnable: false }; $('bridge-plan').hidden = true;
        $('bridge-status').textContent = error.message || '桥接操作失败，请重新检查。';
        $('bridge-rollback-section').hidden = true;
      } finally { busy = false; buttons(); }
    }
    $('bridge-refresh').addEventListener('click', () => run(() => api.bridgeInspect()));
    $('bridge-select').addEventListener('click', () => run(() => api.bridgePlan()));
    consentIds.forEach(id => $(id).addEventListener('change', buttons));
    $('bridge-consent-rollback').addEventListener('change', buttons);
    $('bridge-enable').addEventListener('click', () => {
      buttons(); if ($('bridge-enable').disabled) return;
      const input = { planId: state.planId, enable: true, allowShadowSigning: true, allowJit: true };
      return run(() => api.bridgeDeploy(input));
    });
    $('bridge-rollback').addEventListener('click', () => {
      buttons(); if ($('bridge-rollback').disabled) return;
      return run(() => api.bridgeRollback());
    });
    return { refresh: () => run(() => api.bridgeInspect()) };
  }
  if (typeof module === 'object' && module.exports) module.exports = { mountBridgeSettings };
  else root.CompanionBridgeSettings = { mountBridgeSettings };
})(typeof window === 'object' ? window : globalThis);
