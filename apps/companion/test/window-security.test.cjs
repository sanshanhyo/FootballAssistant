'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {sameLocalPage,allowsWindowIpc,allowsMicrophone}=require('../src/companion-security.cjs');
const {controlSettingsWindow}=require('../src/settings-window.cjs');
const expected='file:///C:/Users/ADMINI%7E1/AppData/Local/Temp/app.asar/src/settings.html';
const actual=expected.replace('%7E','~');
test('Windows portable tilde serialization is the same local page, without weakening role/frame restrictions',()=>{
 assert.equal(sameLocalPage(actual,expected),true);
 const context={role:'settings',trustedMainFrame:true,currentUrl:actual,pageUrl:expected};
 assert.equal(allowsWindowIpc(context,'get-state'),true);
 assert.equal(allowsWindowIpc(context,'settings-window-control'),true);
 assert.equal(allowsWindowIpc({...context,role:'pet'},'settings-window-control'),false);
 assert.equal(allowsWindowIpc({...context,trustedMainFrame:false},'get-state'),false);
 for(const url of [actual.replace('settings','index'),actual+'?q=1',actual+'#x','https://example.com/settings.html',actual.replace('/src/','%2Fsrc%2F'),actual.replace('/src/','%5Csrc%5C'),actual.replace('~','%GG'),'file://server/share/settings.html']) {
  assert.equal(sameLocalPage(url,expected),false,url);
 }
});
test('microphone checks use the same local URL normalization and still reject subframes/video',()=>{
 const context={trustedContents:true,currentUrl:actual,pageUrl:expected};
 assert.equal(allowsMicrophone(context,'media',{isMainFrame:true,requestingUrl:actual,mediaTypes:['audio']}),true);
 assert.equal(allowsMicrophone(context,'media',{isMainFrame:false,requestingUrl:actual,mediaTypes:['audio']}),false);
 assert.equal(allowsMicrophone(context,'media',{isMainFrame:true,requestingUrl:actual,mediaTypes:['video']}),false);
 assert.equal(allowsMicrophone({...context,trustedContents:false},'media',{isMainFrame:true,requestingUrl:actual,mediaTypes:['audio']}),false);
});
test('custom settings controls are bounded and deferred close retains beforeunload semantics',()=>{
 const calls=[];let maximized=false,destroyed=false,close;
 const window={isDestroyed:()=>destroyed,minimize:()=>calls.push('minimize'),isMaximized:()=>maximized,maximize:()=>{maximized=true;calls.push('maximize');},unmaximize:()=>{maximized=false;calls.push('restore');},close:()=>calls.push('close')};
 controlSettingsWindow(window,'minimize');controlSettingsWindow(window,'toggle-maximize');controlSettingsWindow(window,'toggle-maximize');
 controlSettingsWindow(window,'close',fn=>close=fn);assert.deepEqual(calls,['minimize','maximize','restore']);close();
 assert.deepEqual(calls,['minimize','maximize','restore','close']);
 assert.throws(()=>controlSettingsWindow(window,'destroy'));
 controlSettingsWindow(window,'close',fn=>close=fn);destroyed=true;close();assert.equal(calls.length,4);
 assert.throws(()=>controlSettingsWindow(window,'minimize'));
});
