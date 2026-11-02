(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CompanionMotion = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  // Whole-image gestures only; these do not animate the character's face.
  const poses = {
    thinking: ['none', 'rotate(-1.2deg) translateY(-1px)', 'none'],
    transcribing: ['none', 'rotate(-1deg)', 'none'],
    listening: ['none', 'rotate(1deg)', 'none'],
    speaking: ['none', 'translateY(-2px) scaleY(1.008)', 'none'],
    happy: ['none', 'translateY(-6px) rotate(-1deg)', 'translateY(-1px)', 'none'],
    sad: ['none', 'translateY(2px) rotate(-1.5deg)', 'none'],
    idle: ['none', 'translateY(-1px)', 'none'],
    puzzled: ['none', 'rotate(2deg)', 'rotate(-.6deg)', 'none'],
    notice: ['none', 'translateY(-3px)', 'none'],
  };
  function bind({ image, media, enabled = true, timers = { setTimeout, clearTimeout } }) {
    let current = null, idleTimer = null, animation = null, generation = 0, visible = true, disposed = false;
    const allowed = () => enabled && visible && !media?.matches && !disposed;
    function cancel() {
      generation++;
      timers.clearTimeout(idleTimer); idleTimer = null;
      const previous = animation; animation = null;
      previous?.cancel();
      image.dataset.motion = 'off';
    }
    function scheduleIdle() {
      timers.clearTimeout(idleTimer); idleTimer = null;
      if (current !== 'idle' || !allowed() || !image.animate) return;
      idleTimer = timers.setTimeout(() => { idleTimer = null; pulseIdle(); }, 45000);
      idleTimer?.unref?.();
    }
    function rest() { image.dataset.motion = allowed() ? 'idle' : 'off'; scheduleIdle(); }
    function pulseIdle() {
      if (disposed || current !== 'idle' || animation || !allowed() || !image.animate) return;
      timers.clearTimeout(idleTimer); idleTimer = null;
      const token = generation;
      animation = image.animate(poses.idle.map(transform => ({ transform })), { duration: 1800, easing: 'ease-in-out', iterations: 1 });
      animation.finished.then(() => { if (generation === token && !disposed) { animation = null; rest(); } }).catch(() => {});
    }
    function reconcile() { cancel(); rest(); }
    function setState(next) {
      if (disposed || next === current) return;
      current = next; cancel();
      if (!allowed() || next === 'idle' || !poses[next] || !image.animate) { rest(); return; }
      image.dataset.motion = 'reacting';
      const token = generation;
      animation = image.animate(poses[next].map(transform => ({ transform })), {
        duration: next === 'thinking' || next === 'puzzled' ? 1400 : next === 'happy' ? 720 : 950,
        easing: 'ease-in-out', iterations: 1,
      });
      // An older completion must never overwrite a newer state.
      animation.finished.then(() => {
        if (generation !== token || disposed) return;
        animation = null; rest();
      }).catch(() => {});
    }
    media?.addEventListener('change', reconcile);
    rest();
    return {
      setState,
      pulseIdle,
      setEnabled(value) { const next = value !== false; if (enabled !== next) { enabled = next; reconcile(); } },
      setVisible(value) { if (visible !== value) { visible = value; reconcile(); } },
      reset() { current = 'idle'; reconcile(); },
      dispose() { disposed = true; cancel(); media?.removeEventListener('change', reconcile); },
    };
  }
  return { bind };
});
