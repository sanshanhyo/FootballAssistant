'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { validateReaderPayload, createWindowsReaderSetup, inspectGame, PRODUCER_ID, PROTOCOL, GAME_HASH } = require('../src/windows-reader-setup.cjs');
const { loadSettings } = require('../src/bootstrap.cjs');
async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-reader-')); t.after(() => fs.rm(root, { recursive:true, force:true }));
  const folder = path.join(root,'reader-windows-x64'); await fs.mkdir(folder);
  const files = {'OffseasonReaderCli.exe':'offline fixture, not executable','runtime.dll':'fixture runtime'};
  const manifest = {schema:1,target:'win32-x64',entrypoint:'OffseasonReaderCli.exe',producerId:PRODUCER_ID,protocol:PROTOCOL,gamePluginSha256:GAME_HASH,files:{}};
  for (const [name,data] of Object.entries(files)) { await fs.writeFile(path.join(folder,name),data); manifest.files[name]=crypto.createHash('sha256').update(data).digest('hex'); }
  const save = () => fs.writeFile(path.join(folder,'manifest.json'),JSON.stringify(manifest)); await save(); return {root,folder,manifest,save};
}
test('bundled producer inventory is exact and hashed; never calls executable', async t => {
  const f=await fixture(t); assert.equal((await validateReaderPayload(f.root)).executable,path.join(f.folder,'OffseasonReaderCli.exe'));
  await fs.writeFile(path.join(f.folder,'injected.dll'),'x'); await assert.rejects(validateReaderPayload(f.root),/未列出/);
  await fs.unlink(path.join(f.folder,'injected.dll')); await fs.writeFile(path.join(f.folder,'runtime.dll'),'changed'); await assert.rejects(validateReaderPayload(f.root),/校验失败/);
});
test('manifest refuses traversal, case collision, unsupported protocol and linked payload', async t => {
  const f=await fixture(t); const h=f.manifest.files['runtime.dll'];
  f.manifest.files['../escape']=h; await f.save(); await assert.rejects(validateReaderPayload(f.root)); delete f.manifest.files['../escape'];
  f.manifest.files['RUNTIME.DLL']=h; await f.save(); await assert.rejects(validateReaderPayload(f.root)); delete f.manifest.files['RUNTIME.DLL'];
  f.manifest.protocol='other'; await f.save(); await assert.rejects(validateReaderPayload(f.root)); f.manifest.protocol=PROTOCOL; await f.save();
  await fs.unlink(path.join(f.folder,'runtime.dll')); await fs.link(path.join(f.folder,'OffseasonReaderCli.exe'),path.join(f.folder,'runtime.dll')); await assert.rejects(validateReaderPayload(f.root),/普通文件/);
});
test('explicit consent configures only user settings, passive status never verifies, disable survives damaged payload', async t => {
  const f=await fixture(t); const userData=path.join(f.root,'user'); await fs.mkdir(userData);
  const calls=[], statuses=[]; let broken=false;
  const setup=createWindowsReaderSetup({userData,resourcesPath:f.root,packaged:true,platform:'win32',discover:async()=>['/fixture/fm.exe'],inspect:async gamePath=>({gamePath,externalLoaders:['winhttp.dll']}),validatePayload:async()=>{if(broken)throw Error('broken');return {executable:'/trusted/reader.exe'};},requestStatus:async verify=>{statuses.push(verify);return {state:'configured'};},onConfigured:async value=>{calls.push(value);return {restartRequired:true};}});
  assert.equal((await setup.inspect()).enabled,false); assert.deepEqual(statuses,[false]);
  await assert.rejects(setup.enable({enabled:true,readOnlyConsent:false})); assert.equal(calls.length,0);
  await assert.rejects(setup.enable({enabled:true,readOnlyConsent:true,path:'/untrusted'}));
  const enabled=await setup.enable({enabled:true,readOnlyConsent:true}); assert.equal(enabled.restartRequired,true); assert.equal(enabled.gameFilesChanged,false);
  assert.deepEqual(calls[0],{enabled:true,executable:'/trusted/reader.exe'}); assert.equal((await loadSettings(userData)).windowsReaderEnabled,true);
  await setup.status({verify:true}); assert.equal(statuses.at(-1),true);
  broken=true; await setup.enable({enabled:false,readOnlyConsent:false}); assert.equal((await loadSettings(userData)).windowsReaderEnabled,false); assert.equal(calls.at(-1).executable,'');
});
test('game inspector rejects wrong executable and unsupported binary without writing files', async t => {
  const f=await fixture(t); await fs.writeFile(path.join(f.root,'fm.exe'),'fixture'); await fs.writeFile(path.join(f.root,'game_plugin.dll'),'unknown');
  await assert.rejects(inspectGame(path.join(f.root,'OffseasonReaderCli.exe'))); await assert.rejects(inspectGame(path.join(f.root,'fm.exe')),/不在此读取器支持范围/);
  assert.equal(await fs.readFile(path.join(f.root,'game_plugin.dll'),'utf8'),'unknown');
});
test('only trusted settings frame can invoke onboarding IPC', () => {
  const {allowsWindowIpc}=require('../src/companion-security.cjs');
  const context={role:'settings',trustedMainFrame:true,currentUrl:'file:///settings.html',pageUrl:'file:///settings.html'};
  for(const method of ['reader-onboarding-inspect','reader-onboarding-select','reader-onboarding-enable','reader-onboarding-verify']) { assert.equal(allowsWindowIpc(context,method),true); assert.equal(allowsWindowIpc({...context,role:'pet'},method),false); assert.equal(allowsWindowIpc({...context,trustedMainFrame:false},method),false); }
});
