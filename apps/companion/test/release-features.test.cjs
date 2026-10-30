'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { ALPHA_TTS_ENABLED, speakWhenEnabled } = require('../src/release-features.cjs');
test('Alpha 0.0.1 rejects speech before invoking the provider', () => {
  let called = false;
  assert.equal(ALPHA_TTS_ENABLED, false);
  assert.throws(() => speakWhenEnabled(() => { called = true; }), /TTS is disabled/);
  assert.equal(called, false);
});
