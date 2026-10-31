'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const { build } = require('../package.json');

test('both desktop builders use the approved unmodified V2 PNG rather than Electron defaults', () => {
  const source = 'packaging/assets/icon.png';
  assert.equal(build.icon, source);
  assert.equal(build.mac.icon, source);
  assert.equal(build.win.icon, source);
  const bytes = fs.readFileSync(path.join(root, source));
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(bytes.readUInt32BE(16), 1254);
  assert.equal(bytes.readUInt32BE(20), 1254);
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), '2be6a8f930b4303d6b5774b2f1ea4f64640e064d282be6d2c2836ab90e5194af');
});

test('unsigned Windows builds still apply executable icon and version resources', () => {
  assert.notEqual(build.win.signAndEditExecutable, false);
  assert.equal(build.win.signExecutable, false);
  assert.equal(build.mac.identity, null);
  assert.ok(build.win.target.some(item => item.target === 'nsis'));
  assert.ok(build.win.target.some(item => item.target === 'portable'));
});
