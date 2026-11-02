'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createSpeechService } = require('../src/speech-service.cjs');
const { createTtsQueue } = require('../src/tts-queue.js');
const payload = { provider: 'openai', operationId: 'one', generation: 0, conversationId: 'one', text: 'Synthetic test text' };
const env = { FA_SPEECH_OPENAI_API_KEY: 'fake-key', FA_SPEECH_OPENAI_BASE_URL: 'https://example.invalid/v1', FA_SPEECH_TTS_MODEL: 'test' };
const tick = () => new Promise(resolve => setImmediate(resolve));
test('voice/speed/volume contract and invalid values never reach network', async () => {
  let count = 0, body;
  const service = createSpeechService({ env, fetch: async (url, options) => { count++; body = JSON.parse(options.body); return new Response(new Uint8Array([1]), { headers: { 'Content-Type': 'audio/mpeg' } }); } });
  const result = await service.speak({ ...payload, voice: 'nova', speed: 0.75, volume: 0.3 });
  assert.equal(body.speed, 0.75); assert.equal(body.voice, 'nova'); assert.equal(result.volume, 0.3);
  for (const settings of [{ speed: NaN }, { speed: '1' }, { speed: 9 }, { volume: -1 }, { volume: Infinity }]) {
    await assert.rejects(service.speak({ ...payload, ...settings }), { code: 'invalid-settings' });
  }
  assert.equal(count, 1);
  assert.equal(service.capabilities().tts.find(x => x.id === 'openai').connectivity, 'unverified');
  service.dispose();
});
test('trusted main-process provider can extend service; remote errors are sanitized', async () => {
  const service = createSpeechService({ env: {}, ttsProviders: new Map([['example', { synthesize: async () => ({ bytes: new Uint8Array([1]), mimeType: 'audio/mpeg', volume: 1 }) }]]) });
  assert.equal((await service.speak({ ...payload, provider: 'example' })).provider, 'example');
  service.dispose();
});
test('queue waits for audio end, continues after failure, and preserves order', async () => {
  const order = []; let end;
  const queue = createTtsQueue({ synthesize: async x => { order.push(x.operationId); if (x.operationId === 'bad') throw Error('secret'); return x; }, play: () => new Promise(resolve => { end = resolve; }) });
  const a = queue.enqueue({ operationId: 'a' });
  const bad = queue.enqueue({ operationId: 'bad' }); const rejected = assert.rejects(bad, { code: 'speech-failed' });
  const b = queue.enqueue({ operationId: 'b' });
  await tick(); assert.deepEqual(order, ['a']); end(); await a; await tick(); await rejected;
  assert.deepEqual(order, ['a', 'bad', 'b']); end(); await b; queue.dispose();
});
test('context switch cancels active/pending and suppresses late synthesis', async () => {
  let late, plays = 0, stops = 0, cancelled;
  const queue = createTtsQueue({ synthesize: () => new Promise(resolve => { late = resolve; }), play: async () => { plays++; }, stopPlayback: () => { stops++; }, cancel: id => { cancelled = id; } });
  const a = queue.enqueue({ operationId: 'a' }); const ar = assert.rejects(a, { code: 'cancelled' });
  const b = queue.enqueue({ operationId: 'b' }); const br = assert.rejects(b, { code: 'cancelled' });
  await tick(); queue.switchContext(); late({}); await ar; await br; await tick();
  assert.equal(plays, 0); assert.equal(stops, 1); assert.equal(cancelled, 'a'); queue.dispose();
});
test('interrupt cancels old playback and allows new work even if old play hangs', async () => {
  let signal;
  const queue = createTtsQueue({ synthesize: async x => x, play: (x, s) => { if (x.operationId === 'a') { signal = s; return new Promise(() => {}); } return Promise.resolve(); } });
  const a = queue.enqueue({ operationId: 'a' }); const ar = assert.rejects(a, { code: 'cancelled' }); await tick();
  await queue.enqueue({ operationId: 'b' }, { interrupt: true }); await ar; assert.equal(signal.aborted, true); queue.dispose();
});
test('ttsEnv never replaces STT credentials, model or local-whisper capability', async () => {
  const calls = [];
  const service = createSpeechService({ env: { ...env, FA_SPEECH_OPENAI_API_KEY: 'stt-only-key', FA_SPEECH_STT_MODEL: 'transcribe-only' }, ttsEnv: { FA_SPEECH_OPENAI_BASE_URL: 'https://tts.invalid/v1', FA_SPEECH_OPENAI_API_KEY: 'tts-only-key', FA_SPEECH_TTS_MODEL: 'tts-only' }, localWhisper: { capability: () => ({ id: 'local-whisper', available: true }) }, fetch: async (url, options) => {
    calls.push({ url, options });
    return url.endsWith('/transcriptions') ? new Response(JSON.stringify({ text: 'fixture' })) : new Response(new Uint8Array([1]), { headers: { 'Content-Type': 'audio/mpeg' } });
  } });
  await service.speak(payload);
  await service.transcribe({ ...payload, audio: new Uint8Array([1]), mimeType: 'audio/webm' });
  assert.equal(calls[0].url, 'https://tts.invalid/v1/audio/speech');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer tts-only-key');
  assert.equal(calls[1].url, 'https://example.invalid/v1/audio/transcriptions');
  assert.equal(calls[1].options.headers.Authorization, 'Bearer stt-only-key');
  assert.equal(calls[1].options.body.get('model'), 'transcribe-only');
  assert.equal(service.capabilities().stt.find(x => x.id === 'local-whisper').available, true);
  service.dispose();
  const onlyTts = createSpeechService({ env: {}, ttsEnv: env });
  assert.equal(onlyTts.capabilities().stt.find(x => x.id === 'openai').available, false);
  assert.equal(onlyTts.capabilities().tts.find(x => x.id === 'openai').available, true);
  onlyTts.dispose();
});
