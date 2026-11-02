'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const Appearance=require('../src/appearance.js');
function fixture(value){const properties=new Map(),events=new Map();let stored=value;const document={documentElement:{style:{setProperty:(k,v)=>properties.set(k,v)},dataset:{}}};const window={addEventListener:(k,fn)=>events.set(k,fn),removeEventListener:(k)=>events.delete(k)};return {document,window,properties,events,storage:{getItem:()=>stored},set:value=>stored=value};}
test('pet applies saved family/size/theme on reload and receives bounded cross-window changes',()=>{const f=fixture(JSON.stringify({fontFamily:'serif',fontSize:18,darkMode:false}));let layouts=0;const stop=Appearance.bindPet({...f,onChange:()=>layouts++});assert.equal(f.properties.get('--bubble-font'),Appearance.FONTS.serif);assert.equal(f.properties.get('--font-scale'),String(18/14));assert.equal(f.document.documentElement.dataset.theme,'light');f.set(JSON.stringify({fontFamily:'mono',fontSize:13,darkMode:true}));f.events.get('storage')({key:'unrelated'});assert.equal(layouts,1);f.events.get('storage')({key:Appearance.KEY});assert.equal(f.properties.get('--font'),Appearance.FONTS.mono);assert.equal(f.document.documentElement.dataset.theme,'dark');assert.equal(layouts,2);stop();assert.equal(f.events.size,0);});
test('malformed, missing and untrusted appearance values cannot inject CSS or oversized sizes',()=>{for(const value of ['bad json','null',JSON.stringify({fontFamily:'url(https://invalid)',fontSize:999,darkMode:'false'})]){const f=fixture(value);Appearance.bindPet(f);assert.equal(f.properties.get('--font'),Appearance.FONTS.system);assert.equal(f.properties.get('--font-scale'),'1');assert.equal(f.document.documentElement.dataset.theme,'dark');}const f=fixture(null);Appearance.bindPet(f);assert.match(f.properties.get('--bubble-font'),/851 GBai Marker/);f.set('{}');f.events.get('storage')({key:null});assert.equal(f.properties.get('--font-scale'),'1');});
test('both windows load shared appearance script and pet CSS uses the selected pixel size inside the responsive bubble',()=>{const src=name=>fs.readFileSync(path.join(__dirname,'../src',name),'utf8');for(const name of ['index.html','settings.html'])assert.match(src(name),/src="appearance.js"/);assert.match(src('renderer.js'),/CompanionAppearance\?\.bindPet/);assert.match(src('settings.js'),/Appearance\.apply/);assert.match(src('style.css'),/font-size:var\(--bubble-font-size,14px\)/);assert.match(src('style.css'),/data-theme="light"\] #chat-form/);});
test('Whisper license is exact hash protected from Windows newline conversion',()=>{const crypto=require('node:crypto');const root=path.join(__dirname,'..','..','..');const p=path.join(__dirname,'../packaging/WHISPER-MODEL-LICENSE.txt');assert.equal(crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'),'b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d');assert.match(fs.readFileSync(path.join(root,'.gitattributes'),'utf8'),/\/apps\/companion\/packaging\/WHISPER-MODEL-LICENSE\.txt -text/);});

test('light motion defaults on and cross-window changes propagate the stored boolean',()=>{
  const f=fixture('{}'); const values=[];
  const stop=Appearance.bindPet({...f,onChange:prefs=>values.push(prefs.lightMotion)});
  f.set(JSON.stringify({lightMotion:false}));f.events.get('storage')({key:Appearance.KEY});
  f.set(JSON.stringify({lightMotion:true}));f.events.get('storage')({key:Appearance.KEY});
  assert.deepEqual(values,[true,false,true]);stop();
});
test('bubble font uses the exact selected pixel size',()=>{
  for (const size of [13,14,16,18]) { const f=fixture(JSON.stringify({fontSize:size}));Appearance.bindPet(f);assert.equal(f.properties.get('--bubble-font-size'),`${size}px`); }
});
test('bubble duration defaults and malformed values are bounded',()=>{
  assert.equal(Appearance.normalize({}).bubbleDurationMode,'auto');
  for (const value of [undefined,null,'bad',0,-1,1,61,Infinity,2.5]) assert.equal(Appearance.normalize({bubbleDurationMode:'bad',bubbleDurationSeconds:value}).bubbleDurationSeconds,8);
  for (const value of [2,8,60]) assert.equal(Appearance.normalize({bubbleDurationMode:'fixed',bubbleDurationSeconds:value}).bubbleDurationSeconds,value);
  const f=fixture(JSON.stringify({bubbleDurationMode:'fixed',bubbleDurationSeconds:60}));let prefs;
  Appearance.bindPet({...f,onChange:value=>prefs=value});assert.equal(prefs.bubbleDurationSeconds,60);
  f.set(JSON.stringify({bubbleDurationMode:'auto'}));f.events.get('storage')({key:Appearance.KEY});assert.equal(prefs.bubbleDurationMode,'auto');
});
