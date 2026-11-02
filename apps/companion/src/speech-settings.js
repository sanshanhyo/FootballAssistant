(function (root) {
  'use strict';
  function bind({ root: container, api, onError = () => {}, onNotice = () => {} }) {
    const document = container.ownerDocument;
    let disposed = false, busy = false;
    const elements = {};
    const make = (tag, text) => { const node = document.createElement(tag); if (text) node.textContent = text; return node; };
    const form = make('form');
    form.append(make('h3', '语音朗读（默认关闭）'));
    form.append(make('p', '在线朗读会将回复文字发送到所选服务。Edge 使用第三方客户端，服务可能受网络或上游变更影响，不保证永久免费；失败时仍显示文字。'));
    function field(key, label, type = 'text') {
      const wrapper = make('label', label); const input = make('input'); input.type = type; input.id = `tts-${key}`; input.name = key;
      wrapper.htmlFor = input.id; wrapper.append(input); form.append(wrapper); elements[key] = input; return input;
    }
    field('enabled', '启用回复自动朗读', 'checkbox');
    const providerLabel = make('label', '朗读服务');
    const select = make('select'); select.id = 'tts-provider'; providerLabel.htmlFor = select.id;
    for (const [value, label] of [['system', '系统语音（本机）'], ['edge', 'Edge TTS（在线）'], ['openai', 'OpenAI 兼容 TTS（在线）']]) { const item = make('option', label); item.value = value; select.append(item); }
    providerLabel.append(select); form.append(providerLabel); elements.provider = select;
    field('networkConsent', '我同意将待朗读回复文字发送到上面选定的在线服务', 'checkbox');
    field('voice', '音色 ID（留空使用默认）');
    const speed = field('speed', '语速（0.5–2）', 'number'); speed.min = '0.5'; speed.max = '2'; speed.step = '0.05';
    const volume = field('volume', '音量（0–1）', 'number'); volume.min = '0'; volume.max = '1'; volume.step = '0.05';
    field('baseUrl', '语音 API HTTPS 基址（由服务商提供，不含 /audio/speech）', 'url');
    field('model', '语音模型 ID');
    const key = field('apiKey', '语音专用 API Key', 'password'); key.autocomplete = 'new-password';
    field('removeKey', '清除保存的语音密钥', 'checkbox');
    const storage = make('p'); storage.setAttribute('aria-live', 'polite'); form.append(storage);
    const submit = make('button', '保存语音设置'); submit.type = 'submit'; form.append(submit);
    const stop = make('button', '停止当前朗读'); stop.type = 'button'; form.append(stop);
    container.append(form);
    const unwrap = result => { if (!result?.ok) throw Error(result?.error || '语音设置操作失败。'); return result.value; };
    function state() {
      const online = select.value !== 'system'; const compatible = select.value === 'openai';
      for (const input of Object.values(elements)) input.disabled = busy;
      for (const name of ['voice', 'speed', 'volume']) elements[name].disabled = busy || !online;
      elements.networkConsent.disabled = busy || !online;
      for (const name of ['baseUrl', 'model', 'apiKey', 'removeKey']) elements[name].parentElement.hidden = !compatible;
      submit.disabled = busy;
    }
    function render(value) {
      for (const name of ['enabled', 'networkConsent']) elements[name].checked = value[name] === true;
      for (const name of ['provider', 'voice', 'speed', 'volume', 'baseUrl', 'model']) elements[name].value = value[name] ?? '';
      key.value = ''; elements.removeKey.checked = false;
      key.placeholder = value.hasApiKey ? '已配置；留空保留现有密钥' : '输入语音服务密钥';
      storage.textContent = value.storage === 'encrypted' ? '密钥由本机安全存储加密保存，不与聊天密钥共用。' : value.storage === 'session' ? '系统安全存储不可用：密钥仅本次会话有效，退出后需重新输入。' : '未保存语音密钥；不会自动复用聊天密钥。';
      state();
    }
    async function load() {
      busy = true; state();
      try { const value = unwrap(await api.getSpeechConfig()); if (!disposed) render(value); }
      catch (error) { if (!disposed) onError(error.message); }
      finally { busy = false; if (!disposed) state(); }
    }
    select.addEventListener('change', () => { elements.networkConsent.checked = false; elements.voice.value = ''; state(); });
    elements.baseUrl.addEventListener('input', () => { elements.networkConsent.checked = false; });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || disposed) return;
      const input = { enabled: elements.enabled.checked, networkConsent: elements.networkConsent.checked, provider: select.value, voice: elements.voice.value.trim(), speed: Number(speed.value), volume: Number(volume.value), baseUrl: elements.baseUrl.value.trim(), model: elements.model.value.trim(), removeKey: elements.removeKey.checked };
      if (key.value) input.apiKey = key.value;
      busy = true; state();
      try { const value = unwrap(await api.saveSpeechConfig(input)); if (!disposed) { render(value); onNotice('语音设置已保存。'); } }
      catch (error) { if (!disposed) onError(error.message); }
      finally { key.value = ''; busy = false; if (!disposed) state(); }
    });
    stop.addEventListener('click', async () => { try { unwrap(await api.stopSpeech()); if (!disposed) onNotice('已停止朗读。'); } catch (error) { if (!disposed) onError(error.message); } });
    const ready = load();
    return { ready, reload: load, dispose() { disposed = true; key.value = ''; form.remove(); } };
  }
  root.FootballSpeechSettings = { bind };
})(typeof globalThis === 'object' ? globalThis : this);
