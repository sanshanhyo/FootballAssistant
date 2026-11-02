(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CompanionBubbles = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const segmenter = new Intl.Segmenter('zh', { granularity: 'grapheme' });
  const graphemes = text => Array.from(segmenter.segment(String(text ?? '')), part => part.segment);
  const sentenceEnd = /[。！？!?\n\r]/u;
  const closer = /^[。！？!?」』”’"'）)\]】]+$/u;
  const softBreak = /[，,、；;：:\s]/u;

  function splitReply(text, maxCharacters = 40) {
    if (!Number.isSafeInteger(maxCharacters) || maxCharacters < 1) throw new Error('分段长度无效。');
    const parts = graphemes(text);
    const result = [];
    let start = 0;
    while (start < parts.length) {
      const limit = Math.min(start + maxCharacters, parts.length);
      let end = limit;
      let sentence = false;
      for (let i = start; i < limit; i++) {
        if (sentenceEnd.test(parts[i]) || (parts[i] === '.' && (i + 1 === parts.length || /\s/u.test(parts[i + 1])))) {
          end = i + 1;
          while (end < limit && closer.test(parts[end])) end++;
          sentence = true; break;
        }
      }
      if (!sentence && limit < parts.length) {
        for (let i = limit - 1; i >= start + Math.floor(maxCharacters / 2); i--) {
          if (softBreak.test(parts[i])) { end = i + 1; break; }
        }
      }
      // Forty is a reading target, not a cut through closing punctuation.
      // Bound the allowance so malformed punctuation cannot create a huge page.
      while (end < parts.length && end < limit + 4 && (closer.test(parts[end]) || /^[.,，、；;：:…]+$/u.test(parts[end]))) end++;
      const chunk = parts.slice(start, end).join('').trim();
      if (chunk) result.push(chunk);
      start = end;
    }
    return result;
  }
  function latestReply(messages, session) {
    const entries = Array.from(messages || []).filter(message => message && session && message.sessionId === session.sessionId && message.epoch === session.epoch);
    const userIndex = entries.findLastIndex(message => message.role === 'user');
    const user = entries[userIndex];
    return entries.filter((message, index) => message.role === 'assistant' && index > userIndex &&
      (!user || message.origin === 'proactive' || message.requestId === user.requestId)).at(-1) || null;
  }
  function dwellMs(text) { return Math.min(8000, Math.max(2200, 1200 + graphemes(text).length * 140)); }

  function createQueue({ onChange = () => {}, setTimer = setTimeout, clearTimer = clearTimeout, maxCharacters = 40 } = {}) {
    let key = null, fullText = '', chunks = [], index = 0, timer = null, version = 0, paused = false, disposed = false, hidden = true;
    let reading = false, durationMode = 'auto', durationSeconds = 8;
    const state = () => ({ key, text: chunks[index] || '', index, count: chunks.length, hasNext: index + 1 < chunks.length, hidden });
    function stopTimer() { version++; if (timer !== null) clearTimer(timer); timer = null; }
    function hide() {
      stopTimer();
      if (disposed || hidden) return false;
      hidden = true; onChange(state()); return true;
    }
    function schedule() {
      stopTimer();
      if (disposed || paused || reading || hidden || !chunks.length) return;
      const fence = version;
      // Reading time dismisses this page; it never consumes an unread page.
      timer = setTimer(() => { if (disposed || paused || version !== fence) return; timer = null; hide(); }, durationMode === 'fixed' ? durationSeconds * 1000 : dwellMs(chunks[index]));
    }
    function next() {
      if (disposed || paused || hidden || index + 1 >= chunks.length) return false;
      index++; onChange(state()); schedule(); return true;
    }
    function reopen() {
      if (disposed || paused || !hidden || !chunks.length) return false;
      hidden = false; onChange(state()); schedule(); return true;
    }
    return {
      replace(nextKey, text) {
        if (disposed) return state();
        text = String(text ?? '');
        if (key === nextKey && fullText === text) return state(); // Polling never resurrects a timed-out reply.
        const previous = state();
        const append = key === nextKey && fullText.length > 0 && text.startsWith(fullText);
        if (!append) { stopTimer(); index = 0; hidden = false; }
        key = nextKey; fullText = text; chunks = splitReply(text, maxCharacters);
        index = Math.min(index, Math.max(0, chunks.length - 1));
        if (!chunks.length) hidden = true;
        const current = state(); onChange(current);
        // Streaming append retains page and visibility, including unread pending pages.
        if (timer === null || previous.text !== current.text || !append) schedule();
        return current;
      },
      next, hide, reopen,
      configure({ bubbleDurationMode, bubbleDurationSeconds } = {}) {
        const mode = bubbleDurationMode === 'fixed' ? 'fixed' : 'auto';
        const seconds = Number.isInteger(Number(bubbleDurationSeconds)) && Number(bubbleDurationSeconds) >= 2 && Number(bubbleDurationSeconds) <= 60 ? Number(bubbleDurationSeconds) : 8;
        if (mode === durationMode && seconds === durationSeconds) return;
        durationMode = mode; durationSeconds = seconds; schedule();
      },
      setReading(value) { if (reading !== Boolean(value)) { reading = Boolean(value); schedule(); } },
      clear() { stopTimer(); key = null; fullText = ''; chunks = []; index = 0; hidden = true; if (!disposed) onChange(state()); },
      pause() { paused = true; stopTimer(); },
      resume() { if (!disposed && paused) { paused = false; schedule(); } },
      dispose() { stopTimer(); disposed = true; },
      state,
    };
  }
  return { splitReply, graphemes, dwellMs, createQueue, latestReply };
});
