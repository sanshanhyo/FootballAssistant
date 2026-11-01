'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { signBuiltMac } = require('../packaging/sign-mac-adhoc.cjs');
test('mac build explicitly ad-hoc signs assembled bundle without publishing', () => {
  const pkg = require('../package.json');
  assert.match(pkg.scripts['pack:mac'], /--publish never && node packaging\/sign-mac-adhoc\.cjs$/);
  assert.equal(pkg.devDependencies['@electron/osx-sign'], '1.3.3');
  const source = fs.readFileSync(path.join(__dirname, '../packaging/sign-mac-adhoc.cjs'), 'utf8');
  assert.match(source, /identity: '-'/); assert.match(source, /strictVerify: true/);
  assert.doesNotMatch(source, /xattr|spctl|security add|CSC_LINK/);
});
test('ad-hoc signing refuses non-macOS before touching the artifact or invoking signer', async () => {
  let called = false;
  await assert.rejects(signBuiltMac({ platform: 'linux', sign: () => { called = true; } }), /macOS build runner/);
  assert.equal(called, false);
});
