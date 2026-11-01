'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { createLocalWhisper } = require('../src/local-whisper.cjs');
const { createSpeechService } = require('../src/speech-service.cjs');
function wav() {
  const b = Buffer.alloc(44 + 3200);
  b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(3200, 40); return b;
}
async function assets(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-stt-test-'));
  await fs.writeFile(path.join(root, 'whisper-cli'), '', { mode: 0o700 });
  const file = await fs.open(path.join(root, 'ggml-tiny-q5_1.bin'), 'w'); await file.truncate(32152673); await file.close();
  t.after(() => fs.rm(root, { recursive: true, force: true })); return root;
}
test('missing local assets unavailable, never silently downloads or falls back', () => {
  const service = createLocalWhisper({ assetRoot: '/does-not-exist' });
  assert.equal(service.capability().available, false); assert.equal(service.capability().local, true);
});
test('local PCM invokes fixed binary CPU-only without shell and deletes temporary audio', async t => {
  const root = await assets(t); let input;
  const service = createLocalWhisper({ assetRoot: root, platform: 'linux', spawn(exe, args, options) {
    assert.equal(exe, path.join(root, 'whisper-cli')); assert.equal(options.shell, false); assert.ok(args.includes('-ng'));
    assert.equal(args[args.indexOf('-l') + 1], 'zh'); input = args[args.indexOf('-f') + 1];
    const child = new EventEmitter();
    setImmediate(async () => { await fs.writeFile(args[args.indexOf('-of') + 1] + '.txt', '  这是本地转写。\n'); child.emit('close', 0); });
    return child;
  } });
  assert.equal(service.capability().available, true);
  assert.equal(await service.transcribe(wav(), 'zh-CN', new AbortController().signal), '这是本地转写。');
  await assert.rejects(fs.stat(input), { code: 'ENOENT' });
});
test('invalid WAV does not spawn', async t => {
  const root = await assets(t);
  const service = createLocalWhisper({ assetRoot: root, platform: 'linux', spawn() { throw new Error('must not spawn'); } });
  await assert.rejects(service.transcribe(Buffer.alloc(100), 'zh', new AbortController().signal), /PCM WAV/);
});
test('cancel kills subprocess and cleans files after close', async t => {
  const root = await assets(t); const controller = new AbortController(); let input; let killed = false;
  const service = createLocalWhisper({ assetRoot: root, platform: 'linux', spawn(exe, args) {
    input = args[args.indexOf('-f') + 1]; const child = new EventEmitter();
    child.kill = signal => { killed = signal === 'SIGKILL'; setImmediate(() => child.emit('close', null)); };
    setImmediate(() => controller.abort(new Error('cancelled-test'))); return child;
  } });
  await assert.rejects(service.transcribe(wav(), 'zh', controller.signal), /cancelled-test/);
  assert.equal(killed, true); await assert.rejects(fs.stat(input), { code: 'ENOENT' });
});
test('speech integration returns local draft metadata and never calls network', async () => {
  let calls = 0;
  const service = createSpeechService({ env: {}, fetch() { throw new Error('network forbidden'); }, localWhisper: {
    capability: () => ({ id: 'local-whisper', available: true }),
    transcribe: async (bytes, language, signal) => { calls++; assert.equal(language, 'zh'); assert.equal(signal.aborted, false); return '草稿'; },
  } });
  const result = await service.transcribe({ operationId: 'local-1', generation: 1, conversationId: 'session', provider: 'local-whisper', audio: wav(), mimeType: 'audio/wav', language: 'zh' });
  assert.equal(result.text, '草稿'); assert.equal(result.synthetic, false); assert.equal(result.provider, 'local-whisper'); assert.equal(calls, 1);
  service.dispose();
});
