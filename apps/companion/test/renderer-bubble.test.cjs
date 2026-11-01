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
  emit('pointerdown');emit('click');assert.equal(queue.state().index,1);
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
