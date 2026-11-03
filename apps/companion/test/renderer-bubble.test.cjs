'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const Bubbles = require('../src/bubble-segments.js');
test('renderer bubble ignores drags and cancelled pointers, supports click/keyboard, clears hit region on timed hide', async () => {
  const elements = new Map(); let timerId = 0; const timers = new Map(); let queue; let rects = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      id, hidden:['error','chat-form','interaction-feedback','draft-note'].includes(id), value:'', textContent:'', style:{}, dataset:{}, scrollHeight:30,
      events:new Map(), attrs:{}, classList:{remove(){},toggle(){}},
      addEventListener(type, fn) { this.events.set(type, fn); },
      setAttribute(key,value) { this.attrs[key]=value; }, focus(){},
      getClientRects() { return this.hidden ? [] : [{}]; },
      getBoundingClientRect() { return {x:id==='compact-bubble'?50:0,y:0,width:100,height:100}; },
    });
    return elements.get(id);
  };
  const state={epoch:1,sessionId:'qa',canSend:true,messages:[{id:'reply',role:'assistant',epoch:1,sessionId:'qa',text:'第一段。第二段。第三段。'}]};
  const api={inputRects:r=>rects=r,subscribe:()=>()=>{},getState:async()=>({ok:true,value:state}),speechCapabilities:async()=>({ok:true,value:{}}),stopSpeech:async()=>{}};
  const window={companion:api,CompanionUI:require('../src/ui-state.js'),CompanionScenes:require('../src/character-scene.js'),
    CompanionBubbles:{...Bubbles,createQueue:options=>(queue=Bubbles.createQueue({...options,setTimer:(fn)=>{timers.set(++timerId,fn);return timerId;},clearTimer:id=>timers.delete(id)}))},
    getSelection:()=>({toString:()=>''}),addEventListener(){}};
  const context={window,document:{getElementById:get,addEventListener(){}},setTimeout,clearTimeout,performance,URL,navigator:{},ResizeObserver:class {observe(){}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/renderer.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  const bubble=get('compact-bubble');
  const emit=(type,event={})=>bubble.events.get(type)({button:0,pointerId:1,clientX:20,clientY:20,detail:1,preventDefault(){},...event});
  emit('pointerdown');emit('pointermove',{clientX:40});emit('click');
  assert.equal(queue.state().index,0);
  emit('pointerdown');emit('pointercancel');emit('click');assert.equal(queue.state().index,0);
  emit('pointerenter');assert.equal(timers.size,0);
  emit('pointerdown');emit('click');assert.equal(queue.state().index,1);assert.equal(timers.size,0);
  emit('focus');emit('pointerleave');assert.equal(timers.size,0);
  emit('blur');assert.equal(timers.size,1);
  emit('keydown',{key:'Enter',repeat:true});assert.equal(queue.state().index,1);
  emit('keydown',{key:' ',repeat:false});assert.equal(queue.state().index,2);
  assert.equal(get('bubble-progress').textContent,'3 / 3');
  assert(rects.some(rect=>rect.x===50));
  [...timers.values()][0]();
  assert.equal(bubble.hidden,true);assert(!rects.some(rect=>rect.x===50));
  get('pet').events.get('keydown')({key:'Enter',repeat:false,preventDefault(){}});
  assert.equal(bubble.hidden,false);assert.equal(queue.state().index,2);
  queue.dispose();
});

test('automatic and manual speech use the full reply independently of bubble pagination', async () => {
  const elements = new Map(), enqueued = [];
  let queue, onRuntimeEvent;
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      id, hidden:['error','chat-form','interaction-feedback','draft-note'].includes(id), value:'', textContent:'', style:{}, dataset:{}, scrollHeight:30,
      events:new Map(), classList:{remove(){},toggle(){}},
      addEventListener(type, fn) { this.events.set(type, fn); },
      setAttribute(){}, focus(){},
      getClientRects() { return this.hidden ? [] : [{}]; },
      getBoundingClientRect() { return {x:0,y:0,width:100,height:100}; },
    });
    return elements.get(id);
  };
  const state = {epoch:1,sessionId:'tts-full-reply',canSend:true,messages:[]};
  const api = {
    inputRects(){}, subscribe:fn => { onRuntimeEvent = fn; return () => {}; },
    getState:async () => ({ok:true,value:state}),
    getSpeechConfig:async () => ({ok:true,value:{enabled:true}}),
    speechCapabilities:async () => ({ok:true,value:{}}), stopSpeech:async () => {},
  };
  const window = {
    companion:api, CompanionUI:require('../src/ui-state.js'), CompanionScenes:require('../src/character-scene.js'),
    CompanionBubbles:{...Bubbles,createQueue:options => (queue = Bubbles.createQueue({...options,setTimer:() => 1,clearTimer(){}}))},
    FootballTtsQueue:{createTtsQueue:() => ({
      enqueue(payload, options) { enqueued.push({payload,options}); return Promise.resolve(); },
      switchContext(){}, dispose(){},
    })},
    getSelection:() => ({toString:() => ''}), addEventListener(){},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/renderer.js'),'utf8'), {
    window, document:{getElementById:get,addEventListener(){}}, setTimeout,clearTimeout,performance,URL,navigator:{},ResizeObserver:class {observe(){}},
  });
  await new Promise(resolve => setImmediate(resolve));
  const text = '第一段保留完整内容。\n第二段包含标点、空格和 emoji ⚽。\n最后一段也必须完整朗读。';
  const message = {id:'full-reply',role:'assistant',epoch:state.epoch,sessionId:state.sessionId,text,metadata:{synthetic:false}};
  onRuntimeEvent({type:'message',message});
  assert.ok(queue.state().count >= 3);
  assert.notEqual(get('compact-text').textContent, text);
  assert.equal(enqueued.length, 1);
  assert.equal(enqueued[0].payload.text, text);
  assert.equal(enqueued[0].payload.generation, state.epoch);
  assert.equal(enqueued[0].payload.conversationId, state.sessionId);
  const nextPage = () => get('compact-bubble').events.get('keydown')({key:'Enter',repeat:false,preventDefault(){}});
  nextPage();
  assert.equal(queue.state().index, 1);
  assert.equal(enqueued.length, 1, 'turning a bubble page must not enqueue speech');
  onRuntimeEvent({type:'read-last-reply'});
  assert.equal(enqueued.length, 2);
  assert.equal(enqueued[1].payload.text, text, 'manual speech on page two must use the original reply');
  assert.equal(enqueued[1].options.interrupt, true);
  while (queue.state().hasNext) nextPage();
  assert.equal(queue.state().index, queue.state().count - 1);
  assert.equal(enqueued.length, 2, 'remaining page turns must not enqueue speech');
  onRuntimeEvent({type:'read-last-reply'});
  assert.equal(enqueued.length, 3);
  assert.equal(enqueued[2].payload.text, text, 'manual speech on the last page must still use the original reply');
  assert.equal(message.text, text);
  queue.dispose();
});
