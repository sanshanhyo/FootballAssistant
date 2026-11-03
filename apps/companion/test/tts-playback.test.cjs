'use strict';
const test = require('node:test'); const assert = require('node:assert/strict');
const { createPlayback } = require('../src/tts-playback.js');
const { createTtsQueue } = require('../src/tts-queue.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const audio = [], revoked = [];
  const playback = createPlayback({ makeBlob: bytes => bytes, createUrl: () => `blob:${audio.length}`, revokeUrl: url => revoked.push(url), makeAudio: url => {
    const value = { url, listeners: {}, play: async () => {}, pause() { this.paused = true; }, load() {}, removeAttribute() {}, addEventListener(k, fn) { this.listeners[k] = fn; }, removeEventListener(k) { delete this.listeners[k]; } }; audio.push(value); return value;
  } });
  return { audio, revoked, playback };
}
test('renderer playback waits for ended and applies volume exactly once', async () => {
  const f = fixture(); let done = false;
  const task = f.playback.play({ playback: 'renderer', audio: new ArrayBuffer(4), volume: 0.25 }, new AbortController().signal).then(() => { done = true; });
  await flush(); assert.equal(done, false); assert.equal(f.audio[0].volume, 0.25);
  f.audio[0].listeners.ended(); await task; assert.equal(done, true); assert.deepEqual(f.revoked, ['blob:0']);
});
test('character/session switch cancels current audio and queued synthesis with no later playback', async () => {
  const f = fixture(); let syntheses = 0; const cancelled = [];
  const queue = createTtsQueue({ synthesize: async () => { syntheses++; return { playback: 'renderer', audio: new ArrayBuffer(4) }; }, play: f.playback.play, cancel: id => cancelled.push(id), stopPlayback: f.playback.stop });
  const a = queue.enqueue({ operationId: 'a' }).catch(error => error.code); const b = queue.enqueue({ operationId: 'b' }).catch(error => error.code);
  await flush(); assert.equal(syntheses, 1); queue.switchContext();
  assert.equal(await a, 'cancelled'); assert.equal(await b, 'cancelled'); assert.equal(f.audio[0].paused, true);
  await flush(); assert.equal(syntheses, 1); assert.deepEqual(cancelled, ['a']); assert.equal(f.revoked.length, 1);
});
test('aborted playback revokes its URL and rejects without erasing displayed text', async () => {
  const f = fixture(), controller = new AbortController(); const displayedText = 'Already displayed response';
  const task = f.playback.play({ playback: 'renderer', audio: new ArrayBuffer(4) }, controller.signal);
  controller.abort(); await assert.rejects(task, /cancelled/); assert.equal(f.revoked.length, 1); assert.equal(displayedText, 'Already displayed response');
});
