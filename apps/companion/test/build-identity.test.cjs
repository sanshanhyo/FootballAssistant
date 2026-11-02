'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { identity } = require('../packaging/write-build-identity.cjs');
test('test build identity binds exact version and commit without claiming release/game validation', () => {
  const result = identity({ version: '0.0.1-alpha.2', commit: 'a'.repeat(40), runId: '123' });
  assert.equal(result.version, '0.0.1-alpha.2'); assert.equal(result.runId, '123');
  assert.equal(result.releasePublished, false); assert.equal(result.realGameAcceptance, 'pending');
});
test('ambiguous SHA or non-alpha identity rejected', () => {
  assert.throws(() => identity({ version: '0.0.1-alpha.2', commit: 'abc' }));
  assert.throws(() => identity({ version: '0.0.1-onboarding.1', commit: 'a'.repeat(40) }));
});
