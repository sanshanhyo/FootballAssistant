'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {readStateFile,writeStateFile}=require('../src/state-file.cjs');
const {CompanionRuntime}=require('../src/companion-runtime.cjs');
async function fixture(t){const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fa-state-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));return {dir,file:path.join(dir,'companion-ui.json')};}
test('atomic writes clean temporary files and reject a stale writer without losing newer bytes',async t=>{
 const {dir,file}=await fixture(t);const initial=await writeStateFile(file,'{"version":1}',null);
 const results=await Promise.allSettled([writeStateFile(file,'{"version":1,"owner":"first"}',initial),writeStateFile(file,'{"version":1,"owner":"stale"}',initial)]);
 assert.equal(results[0].status,'fulfilled');assert.equal(results[1].status,'rejected');
 assert.equal(JSON.parse((await readStateFile(file)).bytes).owner,'first');assert.deepEqual(await fs.readdir(dir),['companion-ui.json']);
});
test('runtime reload preserves history and memories and detects edits outside its write queue',async t=>{
 const {file}=await fixture(t);const runtime=new CompanionRuntime({file});await runtime.init();runtime.setHistoryEnabled(true);
 runtime.addMessage({id:'history',role:'assistant',text:'synthetic history',sessionId:runtime.sessionId,epoch:runtime.epoch});
 await runtime.saveMemory({text:'synthetic memory'});await runtime.close();
 const next=new CompanionRuntime({file});await next.init();assert.equal(next.getHistory().messages[0].text,'synthetic history');assert.equal(next.getMemories().entries[0].text,'synthetic memory');
 const external=JSON.stringify({version:1,memories:[{id:'outside',text:'external change'}]});await fs.writeFile(file,external);
 await next.saveMemory({text:'local stale change'});assert.ok(next.storageWarning);assert.equal(await fs.readFile(file,'utf8'),external);await next.close();
});
test('unsupported schema is preserved across attempts to persist and close',async t=>{
 const {file}=await fixture(t);const original='{"version":99,"future":"keep"}';await fs.writeFile(file,original);
 const runtime=new CompanionRuntime({file});await runtime.init();await runtime.saveMemory({text:'temporary'});await runtime.close();assert.equal(await fs.readFile(file,'utf8'),original);
});
test('oversized serialized state is rejected before replacement and the last readable data survives',async t=>{
 const {dir,file}=await fixture(t);const initial=await writeStateFile(file,'{"version":1}',null);
 await assert.rejects(writeStateFile(file,'x'.repeat(2_000_001),initial),/exceeds limit/);
 assert.equal((await readStateFile(file)).bytes.toString(),'{"version":1}');assert.deepEqual(await fs.readdir(dir),['companion-ui.json']);
});
