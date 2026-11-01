'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { distribution } = require('../src/distribution.cjs');
test('NSIS marker is channel metadata only; unknown and portable fail closed', t => {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'fa-distribution-'));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const options={platform:'win32',packaged:true,executable:path.join(directory,'FootballAssistant.exe'),env:{}};
  assert.equal(distribution(options),'unknown');
  fs.writeFileSync(path.join(directory,'installation.json'),JSON.stringify({schema:1,distribution:'nsis'}));
  assert.equal(distribution(options),'nsis');
  assert.equal(distribution({...options,env:{PORTABLE_EXECUTABLE_FILE:'portable.exe'}}),'portable');
  assert.equal(distribution({...options,packaged:false}),'unknown');
  assert.equal(distribution({...options,platform:'darwin'}),'unknown');
  fs.writeFileSync(path.join(directory,'installation.json'),'{');assert.equal(distribution(options),'unknown');
});
