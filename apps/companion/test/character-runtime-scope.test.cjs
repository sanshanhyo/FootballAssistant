'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { CompanionRuntime } = require('../src/companion-runtime.cjs');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const { scopeFor } = require('../src/character-library.cjs');
function library() {
  const writes = [], selections = [], scopes = new Map(), selected = new Map();
  const resolve = (id = 'official.eckera') => ({ characterId: id, requestedCharacterId: id, name: id === 'official.eckera' ? '埃克拉' : 'Test character', persona: `Persona ${id}`, voice: null, warnings: [], fallback: false,
    portraitPath: path.resolve(__dirname, id === 'official.eckera' ? '../src/assets/characters/official.eckera/default.png' : 'fixture-custom.png') });
  return { writes, selections, resolve, list: () => [resolve(), resolve('test.other')],
    selected: save => resolve(selected.get(save)), select(save, id) { selections.push([save,id]); selected.set(save,id); return resolve(id); },
    readScope(save,id) { return structuredClone(scopes.get(scopeFor(save,id).key) || { messages: [], memories: [] }); },
    writeScope(save,id,value) { writes.push([save,id]); scopes.set(scopeFor(save,id).key,structuredClone(value)); },
  };
}
async function fixture(t, options = {}) {
  const lib = library(); let cancelled = 0;
  const runtime = new CompanionRuntime({ characterLibrary: lib, cancelCharacterEffects: () => cancelled++, ...options });
  await runtime.init(); t.after(() => runtime.close());
  return { runtime, lib, cancelled: () => cancelled };
}
test('unknown save stays ephemeral; character scopes switch without message/memory mixing', async t => {
  const { runtime:r, lib, cancelled } = await fixture(t);
  r.setHistoryEnabled(true); const save = r.saveId;
  await r.saveMemory({ text: 'official-only' }); r.addMessage({ id:'one', text:'official history', sessionId:r.sessionId, epoch:r.epoch });
  r.selectCharacter('test.other'); assert.equal(r.messages.length,0); assert.equal(r.memories.length,0);
  assert.equal(r.state().character.useBuiltinScenes,false); assert.match(r.state().character.visual.source,/^file:/);
  await r.saveMemory({ text:'custom-only' }); r.selectCharacter('official.eckera');
  assert.deepEqual(r.memories.map(x=>x.text),['official-only']); assert.equal(r.state().messages[0].text,'official history');
  assert.equal(r.state().character.useBuiltinScenes,true); assert.equal(r.saveId,save); assert.ok(cancelled()>=3);
  assert.deepEqual(lib.writes,[]); assert.deepEqual(lib.selections,[]);
  r.setMode('mock'); assert.notEqual(r.saveId,save); assert.equal(r.memories.length,0);
});
test('verified save binding persists scoped data and never inherits unknown history', async t => {
  const { runtime:r, lib } = await fixture(t); r.setHistoryEnabled(true);
  await r.saveMemory({text:'unknown-only'}); r.bindSaveContext('verified-save'); assert.equal(r.memories.length,0);
  await r.saveMemory({text:'save-official'}); r.selectCharacter('test.other'); await r.saveMemory({text:'save-custom'});
  r.bindSaveContext('second-save'); assert.equal(r.memories.length,0);
  r.bindSaveContext('verified-save'); assert.equal(r.characterId,'test.other'); assert.equal(r.memories[0].text,'save-custom');
  assert.ok(lib.writes.every(([save])=>!save.startsWith('session:')));
  assert.throws(()=>r.bindSaveContext('session:unverified'));
});
test('switch aborts pending chat and rejects late output; real request captures current persona scope', async t => {
  let finish, request;
  const realClient = { capabilities:()=>[], status:async()=>({metadata:{limitations:[]}}), reply(value) { request=value; return new Promise(resolve=>finish=resolve); } };
  const {runtime:r}=await fixture(t,{realClient}); r.setMode('real');
  r.sendMessage({text:'hello'}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(request.characterContext.character_id,'official.eckera'); assert.match(request.characterContext.save_id,/^session:/);
  const { createCharacterController } = require('../src/character-controller.cjs');
  const controller = createCharacterController({ library: r.characterLibrary, runtime: r });
  await controller.select('test.other'); assert.equal(request.signal.aborted,true);
  finish({text:'old reply',metadata:{},cards:[]}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(r.messages.length,0); assert.equal(r.characterContext().persona,'Persona test.other');
});
test('real memories use scoped service and discard a response after switching character', async t => {
  let finish; const calls=[];
  const realClient={capabilities:()=>[], addMemory:async value=>{calls.push(value);return{id:'memory',content:value.content};}, memories:()=>new Promise(resolve=>finish=resolve)};
  const {runtime:r}=await fixture(t,{realClient}); r.setMode('real');
  const saved=await r.saveMemory({text:'server memory'}); assert.equal(saved.id,'memory'); assert.equal(calls[0].characterContext.character_id,'official.eckera');
  const pending=r.getMemories(); r.selectCharacter('test.other'); finish({memories:[{id:'old',content:'not current'}]});
  await assert.rejects(pending,/切换/); assert.equal(r.memories.length,0);
});
test('reader sends character_context on ordinary chat and scope queries on memory operations', async () => {
  const calls=[]; const context={save_id:'session:fixture',character_id:'test.other',persona:'Fixture persona'};
  const client=new RealReaderClient({request:async (url,body,options)=>{
    calls.push({url,body,options});
    if(url==='/v1/chat')return{reply:'fixture',conversation_id:'conversation',character_context:context};
    if(options?.method==='DELETE')return{deleted:true};
    return{memories:[],id:'id',content:'content',character_context:{save_id:context.save_id,character_id:context.character_id}};
  }});
  await client.reply({message:'hello',conversationId:'conversation',characterContext:context}); assert.deepEqual(calls[0].body.character_context,context);
  await client.memories({characterContext:context}); assert.match(calls[1].url,/save_id=session%3Afixture&character_id=test.other/);
  await client.addMemory({content:'content',characterContext:context}); assert.equal(calls[2].body.character_context.persona,undefined);
  await client.deleteMemory({id:'12345678-1234-1234-1234-123456789012',characterContext:context}); assert.equal(calls[3].options.method,'DELETE');
  assert.throws(()=>client.verifyMemoryScope({character_context:{save_id:'wrong',character_id:'test.other'}},context),/范围/);
});
test('controlled backend transport allows only scoped memory verbs and retains complete character chat context', async t => {
  const fs = require('node:fs/promises'), os = require('node:os');
  const { request } = require('../src/backend.cjs');
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'memory-route-')); t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const file=path.join(dir,'runtime.json'); await fs.writeFile(file,JSON.stringify({base_url:'http://127.0.0.1:12345',token:'fixture-token-long-enough'}));
  const calls=[], fetch=async(url,options)=>{calls.push({url,options});return{ok:true,status:200,text:async()=>JSON.stringify({deleted:true})};};
  const query='?save_id=session%3Atest&character_id=test.other', id='12345678-1234-1234-1234-123456789012';
  await request(file,'/v1/memories'+query,undefined,{fetch});
  await request(file,'/v1/memories',{content:'fixture',character_context:{save_id:'session:test',character_id:'test.other'}},{fetch});
  await request(file,`/v1/memories/${id}${query}`,undefined,{fetch,method:'DELETE'});
  const context={save_id:'session:test',character_id:'test.other',persona:'fixture persona'};
  await request(file,'/v1/chat',{message:'hello',character_context:context},{fetch});
  assert.deepEqual(calls.map(x=>x.options.method),['GET','POST','DELETE','POST']);
  assert.deepEqual(JSON.parse(calls[3].options.body).character_context,context);
  for(const endpoint of ['/v1/memories','/v1/memories?save_id=only','/v1/memories'+query+'&save_id=other','/v1/memories'+query+'&extra=1','/v1/memories'+query+'#fragment',`/v1/memories/${id}`]) await assert.rejects(request(file,endpoint,undefined,{fetch}),/请求方法/);
  await assert.rejects(request(file,'/v1/memories',{content:'unscoped'},{fetch}),/请求方法/);
  await assert.rejects(request(file,'/v1/memories'+query,undefined,{fetch,method:'DELETE'}),/请求方法/);
  assert.equal(calls.length,4);
});
test('scoped runtime never writes conversation or memory content to global UI file', async t => {
  const fs=require('node:fs/promises'),os=require('node:os');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'scope-ui-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const file=path.join(dir,'ui.json');const lib=library();const r=new CompanionRuntime({file,characterLibrary:lib});
  try { await r.init();r.setHistoryEnabled(true);await r.saveMemory({text:'private temporary'});r.addMessage({text:'private chat',sessionId:r.sessionId});await r.persist();
    const global=JSON.parse(await fs.readFile(file,'utf8'));assert.deepEqual(global.memories,[]);assert.deepEqual(global.messages,[]);assert.deepEqual(lib.writes,[]);
  } finally {await r.close();}
});

test('a backend reply for another character cannot be displayed as the current character', async () => {
  const client=new RealReaderClient({request:async()=>({reply:'wrong persona',character_context:{save_id:'save',character_id:'test.other'}})});
  await assert.rejects(client.reply({message:'hello',characterContext:{save_id:'save',character_id:'official.eckera',persona:'fixture'}}),/范围/);
});
test('history disabled preserves A → B → A during this run but never writes messages to disk', async t => {
  const {runtime:r,lib}=await fixture(t); assert.equal(r.historyEnabled,false);
  r.addMessage({id:'temporary',text:'A while history disabled',sessionId:r.sessionId});
  r.selectCharacter('test.other'); r.selectCharacter('official.eckera');
  assert.equal(r.state().messages[0].text,'A while history disabled');
  r.bindSaveContext('known-save'); r.addMessage({id:'known',text:'Known A temporary chat',sessionId:r.sessionId});
  r.selectCharacter('test.other'); r.selectCharacter('official.eckera');
  assert.equal(r.state().messages[0].text,'Known A temporary chat');
  assert.deepEqual(lib.readScope('known-save','official.eckera').messages,[]);
});
test('A → B → A keeps backend conversation while UI epoch changes; new conversation resets only backend continuity', async t => {
  const calls=[];
  const realClient={capabilities:()=>[],status:async()=>({metadata:{limitations:[]}}),reply:async request=>{calls.push(request);return{text:'fixture reply',metadata:{},cards:[]};}};
  const {runtime:r}=await fixture(t,{realClient}); r.setMode('real');
  const send=async text=>{r.sendMessage({text});await new Promise(resolve=>setImmediate(resolve));};
  await send('A first'); const a=calls[0].conversationId, uiSession=r.sessionId;
  r.selectCharacter('test.other'); await send('B first'); const b=calls[1].conversationId;
  r.selectCharacter('official.eckera'); assert.notEqual(r.sessionId,uiSession); await send('A second');
  assert.equal(calls[2].conversationId,a); assert.notEqual(b,a);
  assert.equal(calls[2].characterContext.character_id,'official.eckera');
  assert.ok(r.messages.every(message=>message.conversationId===a));
  r.switchSession(); await send('A new conversation'); const fresh=calls[3].conversationId; assert.notEqual(fresh,a);
  r.selectCharacter('test.other'); r.selectCharacter('official.eckera'); await send('A new continued'); assert.equal(calls[4].conversationId,fresh);
  assert.ok(r.state().messages.every(message=>message.conversationId===fresh));
});
test('persisted scope restores backend conversation ID from message metadata', async t => {
  const lib=library();
  lib.writeScope('known-save','official.eckera',{messages:[{id:'old',text:'old retained',conversationId:'retained-conversation'}],memories:[]});
  const r=new CompanionRuntime({characterLibrary:lib});await r.init();t.after(()=>r.close());r.setHistoryEnabled(true);r.bindSaveContext('known-save');
  assert.equal(r.backendConversationId,'retained-conversation');
  await r.clearHistory(); assert.notEqual(r.backendConversationId,'retained-conversation');
});
