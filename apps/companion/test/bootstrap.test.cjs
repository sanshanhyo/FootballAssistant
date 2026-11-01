'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { loadSettings, validateSettings, detectGame, BackendSupervisor } = require('../src/bootstrap.cjs');
test('creates versioned non-secret settings once, rejects future/corrupt without overwriting', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-bootstrap-')); t.after(() => fs.rm(dir,{recursive:true,force:true}));
  assert.equal((await loadSettings(dir)).version,1);
  await fs.writeFile(path.join(dir,'settings.json'),'{"version":2}');
  await assert.rejects(loadSettings(dir));
  assert.equal(await fs.readFile(path.join(dir,'settings.json'),'utf8'),'{"version":2}');
  assert.throws(() => validateSettings({version:1,backend:{port:17827},bridgePrivateRoot:'',backendEnvFile:'',apiKey:'secret'}));
});
test('process detection is not data connectivity and never mutates process state', async () => {
  let command;
  const value = await detectGame('win32', async (cmd) => { command=cmd; return {stdout:'"fm.exe","123","Console"'}; });
  assert.equal(command,'tasklist.exe');assert.equal(value.state,'running');assert.equal(value.dataConnected,false);
  assert.equal((await detectGame('darwin',async()=>({stdout:'/Applications/FM.app/Contents/MacOS/fm\n'}))).state,'running');
  assert.equal((await detectGame('darwin',async()=>{throw Error();})).state,'unknown');
});
test('existing authenticated backend is reused and never killed', async () => {
  const supervisor = new BackendSupervisor({probe:async()=>({modelConfigured:false}),spawnProcess:()=>{throw Error('must not spawn');}});
  assert.deepEqual(await supervisor.start(),{state:'ready',owned:false}); await supervisor.stop();
});
test('explicit external runtime failure never starts a replacement', async () => {
  const supervisor = new BackendSupervisor({external:true,probe:async()=>{throw Error();},spawnProcess:()=>{throw Error('must not spawn');}});
  assert.equal((await supervisor.start()).state,'unavailable');
});
test('missing embedded backend yields honest failure, not uv fallback', async () => {
  const supervisor = new BackendSupervisor({packaged:true,resourcesPath:'/not-present',probe:async()=>{throw Error();}});
  assert.equal((await supervisor.start()).state,'missing');
});
test('owned child starts and receives only explicit paths; shutdown kills only child', async t => {
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fa-child-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  await fs.mkdir(path.join(dir,'backend'));await fs.writeFile(path.join(dir,'backend',process.platform==='win32'?'football-assistant-backend.exe':'football-assistant-backend'),'');
  let probes=0,options,kills=0;const child=new EventEmitter();child.exitCode=null;child.signalCode=null;child.kill=()=>{kills++;child.exitCode=0;setImmediate(()=>child.emit('exit'));};
  const supervisor=new BackendSupervisor({userData:dir,resourcesPath:dir,packaged:true,runtimeFile:path.join(dir,'backend','runtime.json'),settings:{backend:{port:17827},backendEnvFile:'',bridgePrivateRoot:''},probe:async()=>{if(++probes===1)throw Error();return {modelConfigured:false};},spawnProcess:(_binary,_args,opts)=>{options=opts;return child;}});
  assert.equal((await supervisor.start()).owned,true);assert.equal(options.env.FOOTBALL_ASSISTANT_DESKTOP,'1');assert.equal(options.env.FOOTBALL_ASSISTANT_PRIVATE_ROOT,undefined);
  await supervisor.stop();assert.equal(kills,1);await supervisor.stop();assert.equal(kills,1);
});
test('failed readiness terminates only the launched child and never reports ready', async t => {
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fa-timeout-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  await fs.mkdir(path.join(dir,'backend'));await fs.writeFile(path.join(dir,'backend',process.platform==='win32'?'football-assistant-backend.exe':'football-assistant-backend'),'');
  let killed=0;const child=new EventEmitter();child.exitCode=null;child.signalCode=null;child.kill=()=>{killed++;child.exitCode=0;setImmediate(()=>child.emit('exit'));};
  const supervisor=new BackendSupervisor({userData:dir,resourcesPath:dir,packaged:true,runtimeFile:path.join(dir,'runtime.json'),settings:{backend:{port:17827}},timeoutMs:1,probe:async()=>{throw Error();},spawnProcess:()=>child});
  assert.equal((await supervisor.start()).state,'failed');assert.equal(killed,1);assert.equal(supervisor.child,null);
});
test('unsupported platform stays unknown without executing a command', async () => {
  const result = await detectGame('linux', async () => { throw Error('must not execute'); });
  assert.equal(result.state, 'unknown'); assert.equal(result.dataConnected, false);
});
test('trusted pet can read game status but not full bootstrap or model settings', () => {
  const { allowsWindowIpc } = require('../src/companion-security.cjs');
  const trusted = { role: 'pet', trustedMainFrame: true, currentUrl: 'file:///pet.html', pageUrl: 'file:///pet.html' };
  assert.equal(allowsWindowIpc(trusted, 'game-status'), true);
  for (const method of ['bootstrap-status', 'model-config-get', 'model-config-save']) assert.equal(allowsWindowIpc(trusted, method), false);
  assert.equal(allowsWindowIpc({ ...trusted, trustedMainFrame: false }, 'game-status'), false);
});
