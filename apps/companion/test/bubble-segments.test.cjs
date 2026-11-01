'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { splitReply, graphemes, dwellMs, createQueue, latestReply } = require('../src/bubble-segments.js');
function fixture() {
  const timers = new Map(); const changes = []; let id = 0;
  const queue = createQueue({ onChange: part => changes.push({ ...part }),
    setTimer: (callback, ms) => { timers.set(++id, { callback, ms }); return id; }, clearTimer: key => timers.delete(key) });
  const fire = () => { const [key, timer] = timers.entries().next().value || []; if (!timer) return false; timers.delete(key); timer.callback(); return true; };
  return { queue, timers, changes, fire };
}
test('sentences and natural pauses split to at most forty visible graphemes without losing content', () => {
  assert.deepEqual(splitReply('先稳住。再看轮换！这场怎么打？'), ['先稳住。', '再看轮换！', '这场怎么打？']);
  assert.deepEqual(splitReply('他说：“先稳住。”再看下一场。'), ['他说：“先稳住。”', '再看下一场。']);
  const text = '先看中场的衔接和传球路线，再看看边路与中路能不能配合起来，最后才决定是否要调整前锋和后卫。';
  const parts = splitReply(text);
  assert.equal(parts.join(''), text); assert.ok(parts.every(part => graphemes(part).length <= 40));
  assert.ok(parts[0].endsWith('，'));
  assert.deepEqual(splitReply('Hello. Next step. 最后一句。'), ['Hello.', 'Next step.', '最后一句。']);
  assert.deepEqual(splitReply('数值1.5，不改小数。'), ['数值1.5，不改小数。']);
  assert.deepEqual(splitReply(' \n\n '), []);
  assert.deepEqual(splitReply('连接失败，请稍后重试。'), ['连接失败，请稍后重试。']);
});
test('hard cuts never split emoji ZWJ families, flags, combining accents or variation selectors', () => {
  const symbols = ['👩🏽‍💻', '👨‍👩‍👧‍👦', '🇨🇳', 'e\u0301', '✈️'];
  const text = symbols.join('').repeat(21);
  const chunks = splitReply(text);
  assert.equal(chunks.join(''), text);
  for (const chunk of chunks) { assert.ok(graphemes(chunk).length <= 40); assert.ok(graphemes(chunk).every(value => symbols.includes(value))); }
  assert.equal(splitReply('球'.repeat(81)).length, 3);
});
test('each segment times out without auto advancing; clicking alone advances and resets clock', () => {
  const f = fixture(); f.queue.replace('a', '第一句。第二句。第三句。');
  assert.equal(f.queue.state().hidden, false); assert.equal(f.timers.size, 1);
  f.fire(); assert.equal(f.queue.state().index, 0); assert.equal(f.queue.state().hidden, true);
  assert.equal(f.queue.state().count, 3); assert.equal(f.queue.next(), false);
  f.queue.reopen(); assert.equal(f.queue.state().text, '第一句。');
  const stale = [...f.timers.values()][0].callback;
  f.queue.next(); stale(); assert.equal(f.queue.state().index, 1); assert.equal(f.queue.state().hidden, false);
  f.queue.next(); assert.equal(f.queue.state().index, 2); assert.equal(f.timers.size, 1);
  f.fire(); assert.equal(f.queue.state().hidden, true); assert.equal(f.queue.state().text, '第三句。');
});
test('single and final pages disappear with grapheme-based bounded reading time', () => {
  const f = fixture(); f.queue.replace('single', '一段。'); f.fire(); assert.equal(f.queue.state().hidden, true);
  assert.equal(dwellMs('短句'), 2200); assert.equal(dwellMs('球'.repeat(40)), 6800);
  assert.equal(dwellMs('球'.repeat(100)), 8000);
  assert.equal(dwellMs('👨‍👩‍👧‍👦'.repeat(20)), dwellMs('球'.repeat(20)));
});
test('new messages, clear and dispose fence stale timer callbacks', () => {
  const f = fixture(); f.queue.replace('old', '旧一。旧二。'); const late = [...f.timers.values()][0].callback;
  f.queue.replace('new', '新一。新二。新三。'); late(); assert.equal(f.queue.state().hidden, false);
  for (let i = 0; i < 20; i++) f.queue.next();
  assert.equal(f.queue.state().text, '新三。'); assert.equal(f.timers.size, 1);
  const cancelled = [...f.timers.values()][0].callback;
  f.queue.clear(); cancelled(); assert.equal(f.queue.state().count, 0); assert.equal(f.timers.size, 0);
  f.queue.replace('third', '再一。再二。'); const closed = [...f.timers.values()][0].callback;
  f.queue.dispose(); const count = f.changes.length; closed(); f.queue.reopen(); f.queue.next(); f.queue.replace('x', '不显示');
  assert.equal(f.changes.length, count); assert.equal(f.timers.size, 0);
});
test('polling and streaming append never resurrect hidden pages or discard unread segments', () => {
  const f = fixture(); f.queue.replace('a', '第一句。第二句。'); const timer = [...f.timers.keys()][0];
  f.queue.replace('a', '第一句。第二句。'); assert.deepEqual([...f.timers.keys()], [timer]);
  f.fire(); f.queue.replace('a', '第一句。第二句。第三句。');
  assert.equal(f.queue.state().index, 0); assert.equal(f.queue.state().hidden, true); assert.equal(f.queue.state().count, 3);
  f.queue.reopen(); f.queue.next(); assert.equal(f.queue.state().text, '第二句。');
  f.queue.replace('a', '修正后的第一句。后续句。'); assert.equal(f.queue.state().index, 0); assert.equal(f.queue.state().hidden, false);
  f.queue.replace('a', ''); assert.equal(f.queue.state().count, 0); assert.equal(f.timers.size, 0);
  f.queue.replace('a', '恢复。下一段。'); assert.equal(f.queue.state().hidden, false);
});
test('streaming beyond displayed segment preserves its timer', () => {
  const f = fixture(); f.queue.replace('stream', '球'.repeat(40)); const timer = [...f.timers.keys()][0];
  f.queue.replace('stream', '球'.repeat(80)); assert.deepEqual([...f.timers.keys()], [timer]);
  f.fire(); assert.equal(f.queue.state().index, 0); assert.equal(f.queue.state().hidden, true);
});
test('window close pauses; reopening resumes the same visible page, never a hidden one', () => {
  const f = fixture(); f.queue.replace('a', '第一句。第二句。'); const late = [...f.timers.values()][0].callback;
  f.queue.pause(); late(); assert.equal(f.queue.state().index, 0); assert.equal(f.timers.size, 0);
  assert.equal(f.queue.next(), false); f.queue.resume(); assert.equal(f.timers.size, 1);
  f.fire(); assert.equal(f.queue.state().hidden, true);
  f.queue.pause(); f.queue.resume(); assert.equal(f.timers.size, 0);
  f.queue.reopen(); assert.equal(f.queue.state().index, 0); assert.equal(f.timers.size, 1);
  f.queue.hide(); assert.equal(f.timers.size, 0);
});
test('latest reply excludes previous input, old request responses and old sessions; full history is untouched', () => {
  const session = { sessionId: 's', epoch: 1 };
  const messages = [
    { ...session, id: 'u1', role: 'user', requestId: 'r1' },
    { ...session, id: 'a1', role: 'assistant', requestId: 'r1', text: '完整回复。需要分段。' },
  ];
  assert.equal(latestReply(messages, session).id, 'a1');
  const original = messages[1].text; splitReply(original); assert.equal(messages[1].text, original);
  messages.push({ ...session, id: 'u2', role: 'user', requestId: 'r2' }); assert.equal(latestReply(messages, session), null);
  messages.push({ ...session, id: 'late', role: 'assistant', requestId: 'r1', text: '迟到' }); assert.equal(latestReply(messages, session), null);
  messages.push({ ...session, id: 'a2', role: 'assistant', requestId: 'r2', text: '新回复' }); assert.equal(latestReply(messages, session).id, 'a2');
  assert.equal(latestReply(messages, { ...session, epoch: 2 }), null);
  messages.push({ ...session, id: 'notice', role: 'assistant', origin: 'proactive', text: '本地提示' }); assert.equal(latestReply(messages, session).id, 'notice');
});

test('approximate length keeps closing punctuation with its sentence at the boundary', () => {
  const text = '中'.repeat(39) + '。”下一段。';
  assert.deepEqual(splitReply(text), ['中'.repeat(39) + '。”', '下一段。']);
  const edge = '中'.repeat(40) + '！？下一段。';
  assert.deepEqual(splitReply(edge), ['中'.repeat(40) + '！？', '下一段。']);
  assert.deepEqual(splitReply('a'.repeat(40) + '. Next.'), ['a'.repeat(40) + '.', 'Next.']);
  assert.deepEqual(splitReply('中'.repeat(40) + '，下一段。'), ['中'.repeat(40) + '，', '下一段。']);
  const emoji = '👩🏽‍💻'.repeat(40) + '！';
  assert.deepEqual(splitReply(emoji), [emoji]);
  const malformed = splitReply('中'.repeat(40) + '！'.repeat(100));
  assert.ok(malformed.every(part => graphemes(part).length <= 44));
});
