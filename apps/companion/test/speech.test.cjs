'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { createSpeechService, validateEndpoint, MAX_AUDIO_BYTES } = require('../src/speech-service.cjs');

const cloudEnv = {
  FA_SPEECH_OPENAI_BASE_URL: 'https://speech.example/v1',
  FA_SPEECH_OPENAI_API_KEY: 'test-only-key',
  FA_SPEECH_STT_MODEL: 'configured-transcription-model',
  FA_SPEECH_TTS_MODEL: 'configured-speech-model',
};
const operation = (extra = {}) => ({ operationId: 'speech-1', generation: 3, conversationId: 'conversation-1', ...extra });
const recording = (extra = {}) => operation({ provider: 'openai', audio: new Uint8Array([1, 2, 3]).buffer, mimeType: 'audio/webm;codecs=opus', language: 'zh', ...extra });
const replyAudio = () => new Response(new Uint8Array([0x49, 0x44, 0x33, 1]), { headers: { 'Content-Type': 'audio/mpeg' } });

test('speech capabilities expose availability without credentials and never fall back to mock', async () => {
  let requests = 0;
  const service = createSpeechService({ env: {}, platform: 'linux', fetch: async () => { requests++; throw new Error('should not run'); } });
  const capabilities = service.capabilities();
  assert.equal(capabilities.stt.find(item => item.id === 'openai').available, false);
  assert.equal(capabilities.tts.find(item => item.id === 'edge').available, false);
  assert.equal(capabilities.tts.find(item => item.id === 'system').available, false);
  await assert.rejects(service.transcribe(recording()), { code: 'not-configured' });
  await assert.rejects(service.speak(operation({ provider: 'edge', text: 'hello' })), { code: 'not-configured' });
  assert.equal(requests, 0);
  const configured = createSpeechService({ env: cloudEnv });
  assert.equal(JSON.stringify(configured.capabilities()).includes('test-only-key'), false);
  assert.equal(JSON.stringify(configured.capabilities()).includes('speech.example'), false);
  service.dispose(); configured.dispose();
});

test('explicit mock labels transcript as unrecognized and creates no fake audio', async () => {
  const service = createSpeechService({ env: {}, fetch: () => { throw new Error('no network'); } });
  const result = await service.transcribe(recording({ provider: 'mock' }));
  assert.equal(result.synthetic, true);
  assert.match(result.text, /未识别实际录音/u);
  assert.match(result.limitations.join(''), /未识别录音/u);
  assert.equal(result.sessionId, 'conversation-1');
  assert.equal(result.partial, false);
  assert.ok(Date.parse(result.sampledAt));
  const speech = await service.speak(operation({ provider: 'mock', text: 'hello' }));
  assert.equal(speech.playback, 'none');
  assert.equal(speech.audio, undefined);
  service.dispose();
});

test('STT sends actual recorder MIME and multipart model without custom multipart boundaries', async () => {
  let request;
  const service = createSpeechService({ env: cloudEnv, fetch: async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ text: '转写草稿' }), { headers: { 'Content-Type': 'application/json' } });
  } });
  const result = await service.transcribe(recording());
  assert.equal(request.url, 'https://speech.example/v1/audio/transcriptions');
  assert.equal(request.options.redirect, 'error');
  assert.equal(request.options.headers.Authorization, 'Bearer test-only-key');
  assert.equal(request.options.headers['Content-Type'], undefined);
  assert.equal(request.options.body.get('model'), cloudEnv.FA_SPEECH_STT_MODEL);
  assert.equal(request.options.body.get('language'), 'zh');
  const file = request.options.body.get('file');
  assert.equal(file.name, 'recording.webm');
  assert.equal(file.type, 'audio/webm');
  assert.equal(file.size, 3);
  assert.equal(result.text, '转写草稿');
  assert.equal(result.operationId, 'speech-1');
  assert.equal(result.generation, 3);
  assert.equal(result.synthetic, false);
  service.dispose();
});

test('TTS cloud requests keep models in main config and return bounded audio for renderer playback', async () => {
  let request;
  const service = createSpeechService({ env: cloudEnv, fetch: async (url, options) => { request = { url, options }; return replyAudio(); } });
  const result = await service.speak(operation({ provider: 'openai', text: '你好', voice: 'alloy', model: 'renderer-cannot-override' }));
  assert.equal(request.url, 'https://speech.example/v1/audio/speech');
  assert.deepEqual(JSON.parse(request.options.body), { model: cloudEnv.FA_SPEECH_TTS_MODEL, input: '你好', voice: 'alloy', response_format: 'mp3' });
  assert.equal(result.playback, 'renderer');
  assert.ok(result.audio instanceof ArrayBuffer);
  assert.equal(result.mimeType, 'audio/mpeg');
  assert.equal(result.audio.byteLength, 4);
  service.dispose();
});

test('Azure SSML escapes game text and rejects injectable voice values', async () => {
  let request; let count = 0;
  const service = createSpeechService({ env: { FA_SPEECH_AZURE_KEY: 'azure-test-key', FA_SPEECH_AZURE_REGION: 'eastasia' }, fetch: async (url, options) => {
    count++; request = { url, options }; return replyAudio();
  } });
  await service.speak(operation({ provider: 'azure', text: '<voice name="evil"> & \'quoted\'' }));
  assert.equal(request.url, 'https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1');
  assert.equal(request.options.headers['Ocp-Apim-Subscription-Key'], 'azure-test-key');
  assert.equal(request.options.headers['Content-Type'], 'application/ssml+xml');
  assert.match(request.options.body, /&lt;voice name=&quot;evil&quot;&gt; &amp; &apos;quoted&apos;/u);
  assert.equal(request.options.redirect, 'error');
  await assert.rejects(service.speak(operation({ provider: 'azure', text: 'hello', voice: '\"><audio src="https://evil">' })), { code: 'invalid-voice' });
  assert.equal(count, 1);
  service.dispose();
});

test('input and response limits reject unsupported media, oversized data and invalid transcriptions', async () => {
  let requests = 0;
  const service = createSpeechService({ env: cloudEnv, fetch: async () => { requests++; return new Response('{"text":42}'); } });
  await assert.rejects(service.transcribe(recording({ mimeType: 'video/webm' })), { code: 'invalid-audio' });
  await assert.rejects(service.transcribe(recording({ audio: new ArrayBuffer(MAX_AUDIO_BYTES + 1) })), { code: 'invalid-audio' });
  await assert.rejects(service.transcribe(recording({ conversationId: '' })), { code: 'invalid-request' });
  assert.equal(requests, 0);
  await assert.rejects(service.transcribe(recording()), { code: 'invalid-response' });
  const oversized = createSpeechService({ env: cloudEnv, fetch: async () => new Response('tiny', { headers: { 'content-type': 'audio/mpeg', 'content-length': String(MAX_AUDIO_BYTES + 1) } }) });
  await assert.rejects(oversized.speak(operation({ provider: 'openai', text: 'hello' })), { code: 'response-too-large' });
  service.dispose(); oversized.dispose();
});

test('a successful JSON error response cannot be represented as playable TTS audio', async () => {
  const service = createSpeechService({ env: cloudEnv, fetch: async () => new Response('{"error":"bad voice"}', { headers: { 'content-type': 'application/json' } }) });
  await assert.rejects(service.speak(operation({ provider: 'openai', text: 'hello' })), { code: 'invalid-response' });
  service.dispose();
});

test('early response rejection cancels unread bodies and aborts fetch without masking the original error', async () => {
  const cases = [
    { status: 200, headers: { 'content-type': 'audio/mpeg', 'content-length': String(MAX_AUDIO_BYTES + 1) }, code: 'response-too-large' },
    { status: 200, headers: { 'content-type': 'application/json' }, code: 'invalid-response' },
    { status: 401, headers: { 'content-type': 'application/json' }, code: 'authentication-failed' },
  ];
  for (const scenario of cases) {
    let cancelled = false; let signal;
    const service = createSpeechService({ env: cloudEnv, fetch: async (_url, options) => {
      signal = options.signal;
      return new Response(new ReadableStream({ cancel() { cancelled = true; throw new Error('cleanup error must be ignored'); } }), scenario);
    } });
    await assert.rejects(service.speak(operation({ provider: 'openai', text: 'hello' })), { code: scenario.code });
    assert.equal(cancelled, true, scenario.code);
    assert.equal(signal.aborted, true, scenario.code);
    service.dispose();
  }
});

test('a streamed size overflow cancels its reader even when cancellation fails', async () => {
  let cancelled = false;
  const service = createSpeechService({ env: cloudEnv, fetch: async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(64 * 1024 + 1)); },
    cancel() { cancelled = true; return Promise.reject(new Error('cleanup failure')); },
  })) });
  await assert.rejects(service.transcribe(recording()), { code: 'response-too-large' });
  assert.equal(cancelled, true);
  service.dispose();
});

test('only HTTPS or loopback speech endpoints are allowed and HTTP failures hide remote error bodies', async () => {
  assert.equal(validateEndpoint('https://speech.example/v1/'), 'https://speech.example/v1');
  assert.equal(validateEndpoint('http://127.0.0.1:3000/v1'), 'http://127.0.0.1:3000/v1');
  for (const url of ['http://speech.example/v1', 'https://user:key@speech.example', 'https://speech.example?key=secret', 'file:///tmp/audio', 'https://speech.example/#token']) assert.equal(validateEndpoint(url), null);
  const service = createSpeechService({ env: cloudEnv, fetch: async () => new Response('secret remote error body test-only-key', { status: 401 }) });
  await assert.rejects(service.transcribe(recording()), error => error.code === 'authentication-failed' && !error.message.includes('test-only-key'));
  service.dispose();
});

test('cancel and timeout reject immediately even if a service ignores abort and delayed data cannot complete old operations', async () => {
  const pending = [];
  const service = createSpeechService({ env: cloudEnv, timeoutMs: 1000, fetch: (_url, options) => new Promise(resolve => pending.push({ resolve, signal: options.signal })) });
  const old = service.transcribe(recording());
  const oldRejected = assert.rejects(old, { code: 'cancelled' });
  const current = service.transcribe(recording({ generation: 4 }));
  assert.equal(pending[0].signal.aborted, true);
  pending[0].resolve(new Response('{"text":"old"}'));
  pending[1].resolve(new Response('{"text":"current"}'));
  await oldRejected;
  assert.equal((await current).text, 'current');
  const cancelled = service.transcribe(recording({ operationId: 'cancel-me' }));
  const cancellation = assert.rejects(cancelled, { code: 'cancelled' });
  assert.equal(service.cancel('cancel-me').cancelled, true);
  await cancellation;
  service.dispose();
  const timeout = createSpeechService({ env: cloudEnv, timeoutMs: 10, fetch: () => new Promise(() => {}) });
  await assert.rejects(timeout.transcribe(recording()), { code: 'timeout' });
  timeout.dispose();
});

test('Edge uses fixed executable with text file input and removes temporary audio after returning', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'speech-edge-test-'));
  const executable = path.join(directory, 'edge-tts');
  await fs.writeFile(executable, '# test fixture', { mode: 0o700 });
  let invocation; let temporaryInput;
  const text = '不执行 $(touch unwanted) `shell` <xml>';
  const service = createSpeechService({ env: { FA_SPEECH_EDGE_PATH: executable }, platform: 'darwin', spawn: (file, args, options) => {
    invocation = { file, args, options };
    const child = new EventEmitter(); child.kill = () => {};
    temporaryInput = args[args.indexOf('--file') + 1];
    const output = args[args.indexOf('--write-media') + 1];
    void fs.readFile(temporaryInput, 'utf8').then(input => {
      assert.equal(input, text);
      return fs.writeFile(output, new Uint8Array([0x49, 0x44, 0x33]));
    }).then(() => child.emit('exit', 0));
    return child;
  } });
  try {
    const result = await service.speak(operation({ provider: 'edge', text }));
    assert.equal(invocation.file, await fs.realpath(executable));
    assert.equal(invocation.options.shell, false);
    assert.equal(invocation.args.some(arg => arg.includes(text)), false);
    assert.equal(result.audio.byteLength, 3);
    await assert.rejects(fs.access(temporaryInput), { code: 'ENOENT' });
  } finally { service.dispose(); await fs.rm(directory, { recursive: true, force: true }); }
});

test('system speech preserves fixed stdin command handling and operation metadata for stop', async () => {
  let input = ''; let command; let killed = false;
  const events = [];
  const child = new EventEmitter(); child.stdin = new PassThrough(); child.stderr = new PassThrough();
  child.stdin.on('data', chunk => { input += chunk.toString(); }); child.kill = () => { killed = true; };
  const service = createSpeechService({ env: {}, platform: 'win32', onState: event => events.push(event), spawn: (file, args, options) => { command = { file, args, options }; return child; } });
  const text = 'Text $(never-run) " ; ` malicious';
  const result = await service.speak(operation({ provider: 'system', text }));
  assert.equal(result.playback, 'system');
  assert.equal(command.file, 'powershell.exe');
  assert.equal(command.args.includes(text), false);
  assert.equal(input, text);
  assert.equal(events.at(-1).operationId, 'speech-1');
  assert.equal(service.cancel('speech-1').cancelled, true);
  assert.equal(killed, true);
  assert.equal(events.at(-1).state, 'stopped');
  service.dispose();
});
