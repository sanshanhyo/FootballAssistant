'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const { build } = require('../package.json');

test('both desktop builders use the approved unmodified rounded PNG rather than Electron defaults', () => {
  const source = 'packaging/assets/icon.png';
  assert.equal(build.icon, source);
  assert.equal(build.mac.icon, source);
  assert.equal(build.win.icon, source);
  const bytes = fs.readFileSync(path.join(root, source));
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(bytes.readUInt32BE(16), 1254);
  assert.equal(bytes.readUInt32BE(20), 1254);
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), 'cf35e79933dd2417c89a5c1fc3318ca8e830a874847435627a866a41738b48ec');
});

test('unsigned Windows builds still apply executable icon and version resources', () => {
  assert.notEqual(build.win.signAndEditExecutable, false);
  assert.equal(build.win.signExecutable, false);
  assert.equal(build.mac.identity, null);
  assert.ok(build.win.target.some(item => item.target === 'nsis'));
  assert.ok(build.win.target.some(item => item.target === 'portable'));
});
