/* Settings-only controller: textContent rendering, no renderer-supplied file paths. */
(function (root) {
  'use strict';
  root.FootballCharacterSettings = { bind({ root: container, api, onState = () => {}, onError = () => {}, onNotice = () => {} }) {
    let current = null, dirty = false, sequence = 0, closed = false;
    const make = (tag, text, parent = container) => { const el = document.createElement(tag); if (text) el.textContent = text; parent.append(el); return el; };
    const unwrap = result => { if (!result?.ok) throw Error(result?.error || '角色操作失败'); return result.value; };
    const section = make('section'); section.className = 'card'; make('h2', '角色库', section);
    const select = make('select', '', section); select.setAttribute('aria-label', '角色库');
    const info = make('p', '', section); info.setAttribute('role', 'status');
    const actions = make('div', '', section); actions.className = 'row-actions';
    const activate = make('button', '切换到此角色', actions), importButton = make('button', '导入 ZIP 角色包', actions);
    const editor = make('section'); editor.className = 'card'; make('h2', '角色覆写', editor);
    const field = (label, tag = 'input') => { const row = make('label', label, editor); row.className = 'setting-row'; return make(tag, '', row); };
    const name = field('显示名'); name.maxLength = 160;
    const persona = field('人设（最多 16 KiB）', 'textarea'); persona.rows = 10;
    const voiceProvider = field('角色默认语音服务'); voiceProvider.placeholder = '留空：跟随语音设置';
    const voiceId = field('角色默认声音 ID');
    const picture = make('img', '', editor); picture.alt = '当前角色立绘'; picture.width = 120;
    const edits = make('div', '', editor); edits.className = 'row-actions';
    const portrait = make('button', '选择 PNG 立绘', edits), save = make('button', '保存覆写', edits), reset = make('button', '恢复包默认值', edits);
    const archiveButton = make('button', '查看迁移前旧档案（只读）', section); const archive = make('pre', '', section); archive.hidden = true;
    const run = async action => { try { onError(''); return await action(); } catch (error) { onError(error.message); return undefined; } };
    const busy = value => { for (const el of [select, activate, importButton, portrait, save, reset, name, persona, voiceProvider, voiceId]) el.disabled = value; };
    const discard = () => !dirty || window.confirm('放弃尚未保存的角色修改？');
    function display(value) {
      current = value; dirty = false; name.value = value.name; persona.value = value.persona;
      voiceProvider.value = value.voice?.provider || ''; voiceId.value = value.voice?.voice_id || '';
      picture.src = value.portraitUrl; info.textContent = `${value.characterId} · v${value.version}${value.current ? ' · 当前角色' : ''}`;
      if (value.warnings?.length) info.textContent += ' · 部分数据不可用，已安全降级';
    }
    async function refresh(id) {
      const token = ++sequence; busy(true);
      try {
        const list = unwrap(await api.listCharacters()); if (closed || token !== sequence) return;
        const selected = id || list.activeId; select.replaceChildren();
        for (const character of list.characters) { const option = make('option', character.name, select); option.value = character.characterId; }
        select.value = selected;
        const value = unwrap(await api.getCharacter(selected)); if (closed || token !== sequence) return; display(value);
        if (list.scope && list.scope.verifiedSave !== true) info.textContent += ' · 存档未识别：当前会话临时隔离';
      } finally { if (token === sequence) busy(false); }
    }
    for (const el of [name, persona, voiceProvider, voiceId]) el.addEventListener('input', () => { dirty = true; });
    select.addEventListener('change', () => { if (!discard()) { select.value = current?.characterId || ''; return; } run(() => refresh(select.value)); });
    activate.addEventListener('click', () => run(async () => { if (!discard() || !current) return; busy(true); try { onState(unwrap(await api.selectCharacter(current.characterId))); await refresh(current.characterId); onNotice('角色已切换，旧语音和生成已取消'); } finally { busy(false); } }));
    importButton.addEventListener('click', () => run(async () => { if (!discard()) return; busy(true); try { const result = unwrap(await api.importCharacter()); if (!result.cancelled) { await refresh(result.character.characterId); onNotice('角色包已导入；选择切换后生效'); } } finally { busy(false); } }));
    save.addEventListener('click', () => run(async () => {
      if (!current) return; busy(true);
      try {
        if (Boolean(voiceProvider.value.trim()) !== Boolean(voiceId.value.trim())) throw Error('语音服务与声音 ID 必须一起填写，或同时留空。');
        const value = unwrap(await api.saveCharacter({ characterId: current.characterId, revision: current.revision, patch: { name: name.value, persona: persona.value, voice: voiceProvider.value.trim() ? { provider: voiceProvider.value.trim(), voice_id: voiceId.value.trim() } : null } }));
        display(value); onNotice('覆写已保存；更新角色包不会覆盖它');
      } finally { busy(false); }
    }));
    portrait.addEventListener('click', () => run(async () => { if (!current || !discard()) return; busy(true); try { const result = unwrap(await api.chooseCharacterPortrait(current.characterId)); if (!result.cancelled) display(result.character); } finally { busy(false); } }));
    reset.addEventListener('click', () => run(async () => { if (!current || !window.confirm('清除这个角色的人设、名字、语音与立绘覆写？聊天和记忆保留。')) return; busy(true); try { display(unwrap(await api.resetCharacter(current.characterId))); } finally { busy(false); } }));
    archiveButton.addEventListener('click', () => run(async () => { const value = unwrap(await api.getCharacterArchive()); archive.hidden = false; archive.textContent = JSON.stringify({ frontend: { messages: value.messages, memories: value.memories }, backend: value.backend || (value.backendUnavailable ? '后端旧档案暂不可读取，原数据保留。' : null) }, null, 2); }));
    const beforeClose = event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', beforeClose);
    run(() => refresh());
    return { hasUnsavedChanges: () => dirty, refresh: () => run(() => { if (discard()) return refresh(); }), dispose() { closed = true; sequence++; window.removeEventListener('beforeunload', beforeClose); } };
  } };
})(typeof window === 'object' ? window : globalThis);
