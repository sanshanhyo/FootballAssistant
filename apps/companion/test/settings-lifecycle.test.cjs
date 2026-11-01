'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/main.cjs'), 'utf8');
for (const event of ['second-instance', 'activate']) {
  test(`${event} reveals pet and opens settings, handling a rejected open`, async () => {
    const statement = source.split('\n').find(line => line.includes(`app.on('${event}',`));
    assert.ok(statement); let callback, shown = 0, opened = 0;
    vm.runInNewContext(statement, { app: { on(name, fn) { assert.equal(name,event); callback=fn; } }, showPet() { shown++; }, openSettings() { opened++; return Promise.reject(new Error('fixture')); } });
    callback(); await new Promise(resolve=>setImmediate(resolve));
    assert.equal(shown,1); assert.equal(opened,1);
  });
}
test('existing minimized settings restores before show/focus without constructing another window', async () => {
  const body = source.slice(source.indexOf('async function openSettings() {'), source.indexOf('  const area = screen.getPrimaryDisplay()', source.indexOf('async function openSettings() {')));
  for (const minimized of [true,false]) {
    const events=[]; const context={ settingsWindow: { isDestroyed:()=>false,isMinimized:()=>minimized,restore:()=>events.push('restore'),show:()=>events.push('show'),focus:()=>events.push('focus') } };
    vm.createContext(context); vm.runInContext(body+'\n}',context);
    const result=await vm.runInContext('openSettings()',context);
    assert.equal(result.opened,true); assert.deepEqual(events,minimized?['restore','show','focus']:['show','focus']);
  }
});
