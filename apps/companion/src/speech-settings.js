(function (root) {
  'use strict';
  function bind({ root: container, api, onError = () => {} }) {
    const document = container.ownerDocument;
    let disposed = false, loading = true, dirty = false, timer, pending, revision = 0, credentialConfig = null;
    const elements = {};
    const make = (tag, text, className) => { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; };
    const form = make('form', '', 'card tts-form');
    form.append(make('h2', '语音朗读'));
    function field(key, label, type = 'text', parent = form) {
      const wrapper = make('div', '', type === 'checkbox' ? 'switch-row' : 'setting-row');
      const caption = make('label', label), input = make('input'); input.type = type; input.id = `tts-${key}`; input.name = key;
      caption.htmlFor = input.id; wrapper.append(caption); wrapper.append(input); parent.append(wrapper); elements[key] = input; return input;
    }
    field('enabled', '在线自动朗读', 'checkbox');
    const providerRow = make('div', '', 'setting-row tts-provider-row');
    const select = make('select'); select.id = 'tts-provider'; select.setAttribute('aria-label', '语音服务');
    for (const [value, label] of [['edge', 'Edge TTS'], ['openai', 'OpenAI 兼容语音']]) { const item = make('option', label); item.value = value; if (value === 'openai') { item.hidden = true; item.disabled = true; } select.append(item); }
    providerRow.append(select); form.append(providerRow); elements.provider = select;
    field('baseUrl', 'API 地址', 'url');
    field('model', '模型');
    field('voice', '音色');
    const key = field('apiKey', 'API Key', 'password'); key.autocomplete = 'new-password'; key.maxLength = 8192;
    field('removeKey', '清除密钥', 'checkbox');
    const sliders = make('div', '', 'tts-sliders'); form.append(sliders);
    const speed = field('speed', '语速', 'range', sliders); speed.min = '0.5'; speed.max = '2'; speed.step = '0.05';
    const volume = field('volume', '音量', 'range', sliders); volume.min = '0'; volume.max = '1'; volume.step = '0.05';
    const actions = make('div', '', 'card-actions'); const stop = make('button', '停止朗读', 'secondary-button'); stop.type = 'button'; actions.append(stop); form.append(actions);
    container.append(form);
    const unwrap = result => { if (!result?.ok) throw Error('语音设置保存失败'); return result.value; };
    const normalizedUrl = value => (value || '').trim().replace(/\/+$/, '');
    function state() {
      key.placeholder = select.value === 'openai' && credentialConfig?.hasApiKey && normalizedUrl(elements.baseUrl.value) === normalizedUrl(credentialConfig.baseUrl) ? '••••••••' : '';
      for (const input of Object.values(elements)) input.disabled = loading;
      for (const name of ['voice', 'baseUrl', 'model', 'apiKey', 'removeKey']) elements[name].parentElement.hidden = true;
    }
    function render(value) {
      // A legacy local provider is displayed as an OFF online configuration, never silently opted in.
      const online = ['edge', 'openai'].includes(value.provider);
      elements.enabled.checked = online && value.enabled === true && value.networkConsent === true;
      select.value = online ? value.provider : 'edge';
      for (const name of ['voice', 'speed', 'volume', 'baseUrl', 'model']) elements[name].value = value[name] ?? '';
      credentialConfig = value;
      state();
    }
    async function load() {
      loading = true; state();
      try { const value = unwrap(await api.getSpeechConfig()); if (!disposed) render(value); }
      catch { if (!disposed) onError('语音设置读取失败'); }
      finally { loading = false; if (!disposed) state(); }
    }
    function snapshot() {
      const compatible = select.value === 'openai';
      const input = { enabled: elements.enabled.checked, networkConsent: elements.enabled.checked, provider: select.value, voice: compatible ? elements.voice.value.trim() : 'zh-CN-XiaoxiaoNeural', speed: Number(speed.value), volume: Number(volume.value) };
      if (compatible) {
        input.baseUrl = elements.baseUrl.value.trim(); input.model = elements.model.value.trim();
        if (elements.removeKey.checked) input.removeKey = true;
        else if (key.value) input.apiKey = key.value;
      }
      return input;
    }
    function flush() {
      clearTimeout(timer);
      if (pending) {
        const waitingRevision = revision;
        return pending.then(ok => pending || (dirty && (ok || revision > waitingRevision)) ? flush() : ok);
      }
      if (!dirty || disposed || loading) return Promise.resolve(true);
      dirty = false; const version = revision, input = snapshot(), password = key.value;
      pending = (async () => {
        try {
          const value = unwrap(await api.saveSpeechConfig(input));
          if (!disposed) {
            if (select.value === input.provider && normalizedUrl(elements.baseUrl.value) === normalizedUrl(input.baseUrl) && key.value === password && (input.apiKey || input.removeKey)) key.value = '';
            if (version === revision) elements.removeKey.checked = false;
            credentialConfig = value; state();
            onError('');
          }
          return true;
        } catch { if (!disposed) { dirty = true; onError('语音设置保存失败'); } return false; }
        finally { delete input.apiKey; pending = null; }
      })();
      return pending.then(ok => dirty && (ok || revision > version) ? flush() : ok);
    }
    function changed() { if (loading || disposed) return; dirty = true; revision++; clearTimeout(timer); timer = setTimeout(flush, 350); }
    for (const [name, input] of Object.entries(elements)) {
      const event = input.type === 'checkbox' || name === 'provider' ? 'change' : 'input';
      input.addEventListener(event, () => {
        if (name === 'provider' || name === 'baseUrl') { elements.enabled.checked = false; }
        if (name === 'provider') { elements.voice.value = ''; key.value = ''; elements.removeKey.checked = false; }
        state(); changed();
      });
      input.addEventListener('blur', () => { if (dirty) flush(); });
    }
    form.addEventListener('submit', event => { event.preventDefault(); return flush(); });
    stop.addEventListener('click', async () => { try { unwrap(await api.stopSpeech()); } catch { if (!disposed) onError('停止朗读失败'); } });
    const ready = load();
    return { ready, reload: load, flush, hasPendingChanges: () => dirty || Boolean(pending), dispose() { disposed = true; clearTimeout(timer); key.value = ''; form.remove(); } };
  }
  root.FootballSpeechSettings = { bind };
})(typeof globalThis === 'object' ? globalThis : this);
