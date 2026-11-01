'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { validateRuntime, request } = require('../src/backend.cjs');
const { speechCommand, createSpeech } = require('../src/tts.cjs');
const { resolveRect, clampPointToRegion } = require('../src/vendor/displays.cjs');

test('runtime connection refuses remote hosts, credentials, paths and weak tokens', () => {
  const token = 'a'.repeat(32);
  assert.equal(validateRuntime({ base_url:'http://127.0.0.1:17827', token }).baseUrl, 'http://127.0.0.1:17827');
  for (const base_url of ['https://127.0.0.1', 'http://example.com', 'http://127.0.0.1/secret', 'http://user:pass@localhost', 'http://127.0.0.1?token=leak']) {
    assert.throws(() => validateRuntime({ base_url, token }));
  }
  assert.throws(() => validateRuntime({ base_url:'http://127.0.0.1:17827', token:'short' }));
});

test('backend requests re-read rotated tokens and preserve real model errors', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'football-companion-'));
  const file = path.join(dir, 'runtime.json');
  const tokens = [];
  try {
    for (const token of ['a'.repeat(32), 'b'.repeat(32)]) {
      await fs.writeFile(file, JSON.stringify({ base_url:'http://127.0.0.1:17827', token }));
      const result = await request(file, '/v1/status', undefined, { fetch:async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:17827/v1/status');
        assert.equal(options.redirect, 'error'); tokens.push(options.headers.Authorization);
        return { ok:true, text:async () => '{"modelConfigured":false}' };
      } });
      assert.equal(result.modelConfigured, false);
    }
    assert.deepEqual(tokens, ['Bearer ' + 'a'.repeat(32), 'Bearer ' + 'b'.repeat(32)]);
    await assert.rejects(request(file, '/v1/chat', { message:'hello' }, { fetch:async () => ({ ok:false, status:503, text:async () => '{"detail":{"code":"model_unconfigured","message":"模型尚未配置"}}' }) }), /模型尚未配置/);
    await assert.rejects(request(file, '/arbitrary', undefined), /不支持/);
  } finally { await fs.rm(dir, { recursive:true, force:true }); }
});

test('TTS passes untrusted text only through stdin and can stop its own child', () => {
  let command; let input=''; let killed=false; const states=[];
  const child = new EventEmitter(); child.stdin = new PassThrough(); child.stderr = new PassThrough();
  child.stdin.on('data', data => { input += data.toString(); }); child.kill = () => { killed=true; };
  const speech = createSpeech(state => states.push(state.state), { platform:'win32', spawn:(file,args,options) => { command={file,args,options}; return child; } });
  const text = '你好 " ; $(touch should-not-exist) ` 不应执行';
  speech.speak(text);
  assert.equal(input, text); assert.equal(command.file, 'powershell.exe'); assert.equal(command.options.shell, undefined);
  assert.ok(command.args.includes('-EncodedCommand')); assert.ok(!command.args.some(arg => arg.includes(text)));
  speech.stop(); assert.ok(killed); assert.deepEqual(states, ['stopped','speaking','stopped']);
  assert.equal(speechCommand('darwin').file, '/usr/bin/say'); assert.throws(() => speechCommand('linux'));
});

test('monitoring accepts only fixed read-only routes and canonical event queries', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'football-monitor-'));
  const file = path.join(dir, 'runtime.json');
  try {
    await fs.writeFile(file, JSON.stringify({base_url:'http://127.0.0.1:17827',token:'m'.repeat(32)}));
    for (const endpoint of ['/v1/monitoring','/v1/events?after=10&limit=100']) {
      await request(file, endpoint, undefined, {fetch:async (_url, options) => {
        assert.equal(options.method, 'GET'); assert.equal(options.body, undefined);
        return {ok:true,text:async ()=>'{}'};
      }});
    }
    for (const endpoint of ['/v1/events?after=1&limit=100&token=leak','/v1/events?after=-1&limit=100','/v1/events?after=1;shutdown&limit=100']) {
      await assert.rejects(request(file, endpoint, undefined), /不支持/);
    }
  } finally { await fs.rm(dir,{recursive:true,force:true}); }
});

test('dsh-pet geometry resolves disconnected monitor gaps rather than leaving pet invisible', () => {
  const areas = [{x:-1920,y:0,width:1920,height:1080},{x:0,y:500,width:1440,height:900}];
  assert.deepEqual(resolveRect(areas, 500, 100), areas[1]);
  assert.deepEqual(clampPointToRegion(areas,500,100), {x:500,y:500});
  assert.deepEqual(clampPointToRegion(areas,-100,100), {x:-100,y:100});
});

test('explicit packaged runtime path avoids package-relative discovery and preserves env override', () => {
  const { defaultRuntimeFile } = require('../src/backend.cjs');
  const selected = path.resolve('repo with spaces/local-data/runtime.json');
  assert.equal(defaultRuntimeFile({}, ['FootballAssistant.exe', '--runtime-file', selected]), selected);
  assert.equal(defaultRuntimeFile({ FOOTBALL_ASSISTANT_RUNTIME_FILE: selected }, ['--runtime-file', 'ignored.json']), selected);
  assert.equal(defaultRuntimeFile({ FOOTBALL_ASSISTANT_DATA_DIR: path.dirname(selected) }), selected);
  assert.equal(defaultRuntimeFile({}), path.resolve(__dirname, '../../..', 'local-data/runtime.json'));
  for (const argv of [['--runtime-file'], ['--runtime-file', '--other'], ['--runtime-file', 'a', '--runtime-file', 'b']]) {
    assert.throws(() => defaultRuntimeFile({}, argv), /明确的连接文件路径/);
  }
});

test('missing runtime gives startup/config guidance without fetching or mock fallback', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'football-missing-runtime-'));
  try {
    await assert.rejects(request(path.join(dir, 'missing.json'), '/v1/status', undefined, {
      fetch: async () => { assert.fail('missing config must not send a request'); },
    }), /scripts\/run_mvp.py.*FOOTBALL_ASSISTANT_RUNTIME_FILE.*不会回退到模拟/);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
