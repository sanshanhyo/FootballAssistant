'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { destination, normalizeModels, createModelDiscovery } = require('../src/model-providers.cjs');
const credentials = { getPublicConfig: () => ({ provider: 'openai', baseUrl: 'https://api.openai.com/v1' }), backendEnv: () => ({ FOOTBALL_ASSISTANT_API_KEY: 'saved-secret' }) };
const response = data => new Response(JSON.stringify({ data }), { status: 200 });
test('preset destinations cannot be overridden; unknown providers send no key', async () => {
  assert.equal(destination('opencode-go').modelsUrl, 'https://opencode.ai/inference/go/v1/models');
  assert.throws(() => destination('openai', 'https://other.test/v1'));
  assert.throws(() => destination('command-go'));
  for (const url of ['http://example.test', 'https://key@example.test', 'https://example.test/?key=x']) assert.throws(() => destination('openai-compatible', url));
});
test('normalize, deduplicate and sort real provider IDs without inventing entries', () => {
  assert.deepEqual(normalizeModels({ data: [{id:' z '},{id:'a',name:'Alpha'},{id:'z'},{id:''},{id:'bad id'},{}] }), [{id:'a',name:'Alpha'},{id:'z',name:'z'}]);
  assert.deepEqual(normalizeModels({data:[]}), []);
  assert.throws(() => normalizeModels({models:['invented']}));
});
test('key only reused at exact destination; explicit blank means no key', async () => {
  const calls=[]; const service=createModelDiscovery({credentials,fetchImpl:async (...args)=>{calls.push(args);return response([{id:'x'}]);}});
  await service.list({provider:'openai'}); await service.list({provider:'deepseek'}); await service.list({provider:'openai',apiKey:''});
  assert.equal(calls[0][1].headers.Authorization,'Bearer saved-secret'); assert.equal(calls[1][1].headers.Authorization,undefined); assert.equal(calls[2][1].headers.Authorization,undefined);
  assert.equal(calls[0][1].redirect,'error'); assert.equal(calls[0][1].method,'GET');
});
test('unsupported and invalid listings are errors, never static fallback', async () => {
  const service=createModelDiscovery({credentials,fetchImpl:async()=>new Response('key=secret',{status:404})});
  await assert.rejects(service.list({provider:'openai'}), /不支持读取/);
  const malformed=createModelDiscovery({credentials,fetchImpl:async()=>new Response('secret',{status:200})});
  await assert.rejects(malformed.list({provider:'openai'}), /无法连接/);
});
test('superseding, cancel and timeout abort pending requests', async () => {
  const signals=[];
  const service=createModelDiscovery({credentials,timeoutMs:20,fetchImpl:async (_,opts)=>{signals.push(opts.signal);return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('transport key secret'))));}});
  const first=assert.rejects(service.list({provider:'openai'}),/取消或超时/);
  const second=assert.rejects(service.list({provider:'deepseek'}),/取消或超时/);
  assert.equal(signals[0].aborted,true); await Promise.all([first,second]); assert.equal(signals[1].aborted,true);
});
test('late response cannot overwrite a newer query even if transport ignores abort', async () => {
  const pending=[]; const service=createModelDiscovery({credentials,fetchImpl:()=>new Promise(resolve=>pending.push(resolve))});
  const first=assert.rejects(service.list({provider:'openai'}),/取消/);
  const second=service.list({provider:'deepseek'});
  pending[1](response([{id:'new'}])); assert.equal((await second).models[0].id,'new');
  pending[0](response([{id:'old'}])); await first;
});
test('response bytes are bounded and transport errors do not expose keys', async () => {
  const large=createModelDiscovery({credentials,fetchImpl:async()=>new Response('x'.repeat(4*1024*1024+1))});
  await assert.rejects(large.list({provider:'openai'}),/大小限制/);
  const failed=createModelDiscovery({credentials,fetchImpl:async()=>{throw Error('https://test secret saved-secret');}});
  await assert.rejects(failed.list({provider:'openai'}),error=>!error.message.includes('saved-secret'));
});

test('Command Code GOAT uses official URL and excludes unsupported protocol models', async () => {
  assert.equal(destination('commandcode-goat').modelsUrl,'https://api.commandcode.ai/provider/v1/models');
  const data=[{id:'deepseek/example',supported_endpoints:['/v1/chat/completions']},{id:'claude',supported_endpoints:['/v1/messages']},{id:'unknown'},{id:'decision',supported_endpoints:['/v1/systemone']}];
  const service=createModelDiscovery({credentials,fetchImpl:async()=>response(data)});
  assert.deepEqual((await service.list({provider:'commandcode-goat'})).models,[{id:'deepseek/example',name:'deepseek/example'}]);
});
