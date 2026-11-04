'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { bind } = require('../src/pet-motion.js');
function fixture(options = {}) {
  const animations = [], listeners = new Map();
  const image = { dataset: {}, animate(frames, timing) {
    let finish;
    const animation = { frames, timing, cancelled: false, finished: new Promise(resolve => { finish = resolve; }),
      finish: () => finish(), cancel() { this.cancelled = true; } };
    animations.push(animation); return animation;
  } };
  const media = { matches: false, addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key) };
  const motion = bind({ image, media, ...options });
  return { image, media, motion, animations, listeners,
    reduce(value) { media.matches = value; listeners.get('change')(); } };
}
test('state reactions run once, then return to idle without changing interaction state', async () => {
  for (const state of ['listening','transcribing','thinking','speaking','happy','puzzled','notice']) {
    const f = fixture(); assert.equal(f.image.dataset.motion, 'idle');
    f.motion.setState(state); f.motion.setState(state);
    assert.equal(f.animations.length, 1); assert.equal(f.animations[0].timing.iterations, 1);
    assert.equal(f.image.dataset.motion, 'reacting');
    f.animations[0].finish(); await Promise.resolve();
    assert.equal(f.image.dataset.motion, 'idle');
    f.motion.setState(state); assert.equal(f.animations.length, 1);
    f.motion.dispose();
  }
});
test('new states cancel previous reactions and stale completions cannot reset the new one', async () => {
  const f = fixture(); f.motion.setState('thinking'); f.motion.setState('speaking');
  assert.equal(f.animations[0].cancelled, true);
  f.animations[0].finish(); await Promise.resolve(); assert.equal(f.image.dataset.motion, 'reacting');
  f.motion.setState('idle'); assert.equal(f.animations[1].cancelled, true);
  f.animations[1].finish(); await Promise.resolve(); assert.equal(f.image.dataset.motion, 'idle');
  f.motion.dispose();
});
test('reduced motion cancels active animation immediately and does not replay it when restored', async () => {
  const f = fixture(); f.motion.setState('happy'); f.reduce(true);
  assert.equal(f.animations[0].cancelled, true); assert.equal(f.image.dataset.motion, 'off');
  f.animations[0].finish(); await Promise.resolve(); assert.equal(f.image.dataset.motion, 'off');
  f.motion.setState('puzzled'); assert.equal(f.animations.length, 1);
  f.reduce(false); assert.equal(f.image.dataset.motion, 'idle'); assert.equal(f.animations.length, 1);
  f.motion.dispose(); assert.equal(f.listeners.size, 0);
});
test('setting and hidden window suppress all motion; restored windows do not replay old events', () => {
  const f = fixture({ enabled: false }); assert.equal(f.image.dataset.motion, 'off');
  f.motion.setState('notice'); assert.equal(f.animations.length, 0);
  f.motion.setEnabled(true); assert.equal(f.image.dataset.motion, 'idle');
  f.motion.setState('speaking'); f.motion.setVisible(false);
  assert.equal(f.animations[0].cancelled, true); assert.equal(f.image.dataset.motion, 'off');
  f.motion.setState('happy'); f.motion.setVisible(true); assert.equal(f.animations.length, 1);
  f.motion.setEnabled(false); assert.equal(f.image.dataset.motion, 'off');
  f.motion.dispose(); f.motion.setEnabled(true); f.motion.setState('thinking');
  assert.equal(f.image.dataset.motion, 'off'); assert.equal(f.animations.length, 1);
});
test('initial system reduction and missing Web Animations API are safe', () => {
  const f = fixture({ media: { matches: true, addEventListener() {}, removeEventListener() {} } });
  f.motion.setState('speaking'); assert.equal(f.animations.length, 0); assert.equal(f.image.dataset.motion, 'off');
  f.motion.dispose();
  const image = { dataset: {} }; const motion = bind({ image }); motion.setState('happy');
  assert.equal(image.dataset.motion, 'idle'); motion.dispose();
});
test('sad reaction and bounded idle pulse obey cancellation, reduced motion and disable', async () => {
  const f = fixture(); f.motion.setState('idle'); f.motion.pulseIdle(); f.motion.pulseIdle();
  assert.equal(f.animations.length, 1); assert.equal(f.animations[0].timing.iterations, 1);
  f.motion.setState('sad'); assert.equal(f.animations[0].cancelled, true);
  f.motion.pulseIdle(); assert.equal(f.animations.length, 2);
  f.motion.reset(); f.motion.pulseIdle(); assert.equal(f.animations.length, 3);
  f.reduce(true); assert.equal(f.animations[2].cancelled, true);
  f.motion.pulseIdle(); assert.equal(f.animations.length, 3);
  f.reduce(false); f.motion.setEnabled(false); f.motion.pulseIdle(); assert.equal(f.animations.length, 3);
  f.motion.dispose();
});

test('companionship schedules only confirmed idle, stays bounded and clears timers on interruption', async () => {
  let next = 0; const pending = new Map();
  const timers = { setTimeout(fn, delay) { assert.equal(delay, 45000); pending.set(++next, fn); return next; }, clearTimeout(id) { pending.delete(id); } };
  const f = fixture({ timers }); assert.equal(pending.size, 0);
  f.motion.setState('idle'); assert.equal(pending.size, 1);
  const fire = () => { const [id, fn] = [...pending][0]; pending.delete(id); fn(); };
  fire(); assert.equal(f.animations.length, 1); assert.equal(pending.size, 0);
  f.animations[0].finish(); await Promise.resolve(); assert.equal(pending.size, 1);
  f.motion.setState('thinking'); assert.equal(pending.size, 0);
  f.motion.reset(); assert.equal(pending.size, 1);
  f.motion.setVisible(false); assert.equal(pending.size, 0);
  f.motion.setVisible(true); assert.equal(pending.size, 1);
  f.reduce(true); assert.equal(pending.size, 0);
  f.reduce(false); assert.equal(pending.size, 1);
  f.motion.setEnabled(false); assert.equal(pending.size, 0);
  f.motion.setEnabled(true); assert.equal(pending.size, 1);
  f.motion.dispose(); assert.equal(pending.size, 0);
});
