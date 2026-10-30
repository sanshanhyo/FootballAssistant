'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createGesture, createFence, shouldSubmitText, belongsToSession, valueLabel, observationLabels, timestampLabel } = require('../src/ui-state.js');

test('pet gesture distinguishes click, long hold and drag without starting voice while dragging', () => {
  const gesture = createGesture();
  gesture.begin({ id:1, x:10, y:10, time:0 });
  assert.equal(gesture.end(1), 'click');
  gesture.begin({ id:2, x:10, y:10, time:0 });
  assert.equal(gesture.hold(459), false);
  assert.equal(gesture.hold(460), true);
  assert.equal(gesture.move({ id:2, x:100, y:100 }), null);
  assert.equal(gesture.end(2), 'voice-stop');
  gesture.begin({ id:3, x:10, y:10, time:0 });
  assert.equal(gesture.move({ id:3, x:30, y:10 }), 'drag-start');
  assert.equal(gesture.hold(1000), false);
  assert.equal(gesture.end(3), 'drag-end');
});

test('cancelled hold does not submit transcription and unrelated pointer cannot end gesture', () => {
  const gesture = createGesture();
  gesture.begin({ id:1, x:0, y:0, time:0 });
  assert.equal(gesture.end(2), null);
  gesture.hold(500);
  assert.equal(gesture.end(1, true), 'voice-cancel');
  assert.equal(gesture.end(1), null);
});

test('old request results are fenced after session or provider changes', () => {
  const fence = createFence(); const token = fence.capture();
  assert.equal(fence.accepts(token), true);
  fence.invalidate(); assert.equal(fence.accepts(token), false);
  const state = { sessionId:'new', epoch:2 };
  assert.equal(belongsToSession({ sessionId:'old', epoch:2 }, state), false);
  assert.equal(belongsToSession({ sessionId:'new', epoch:1 }, state), false);
  assert.equal(belongsToSession({ sessionId:'new', epoch:2 }, state), true);
});

test('unknown values never become zero, but an explicitly observed zero stays zero', () => {
  assert.equal(valueLabel({ value:null }), '未知');
  assert.equal(valueLabel({ value:undefined }), '未知');
  assert.equal(valueLabel({ value:0, status:'unknown' }), '未知');
  assert.equal(valueLabel({ value:0, status:'observed' }), '0');
  assert.equal(valueLabel({ value:NaN, status:'observed' }), '未知');
  assert.equal(valueLabel({ value:Infinity, status:'observed' }), '未知');
  assert.equal(valueLabel({ value:'', status:'observed' }), '未知');
});

test('observation labels preserve synthetic, stale, partial and missing metadata', () => {
  assert.deepEqual(observationLabels({ synthetic:true, freshness:'stale', partial:true }), ['模拟数据', '已过期', '数据不完整']);
  assert.deepEqual(observationLabels({}), ['来源待确认', '时效未知', '完整性未知']);
  assert.equal(timestampLabel('not-a-date'), '采样时间未知');
  assert.equal(timestampLabel(null), '采样时间未知');
});


test('composer Enter respects Chinese IME and Shift+Enter drafts', () => {
  assert.equal(shouldSubmitText({ key:'Enter' }), true);
  assert.equal(shouldSubmitText({ key:'Enter', shiftKey:true }), false);
  assert.equal(shouldSubmitText({ key:'Enter', isComposing:true }), false);
  assert.equal(shouldSubmitText({ key:'Enter' }, true), false);
  assert.equal(shouldSubmitText({ key:'Enter', keyCode:229 }), false);
  assert.equal(shouldSubmitText({ key:'a' }), false);
});
