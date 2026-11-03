(function (root, factory) { if (typeof module === 'object' && module.exports) module.exports = factory(); else root.FootballTtsPlayback = factory(); })(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  function createPlayback({ makeAudio = url => new Audio(url), createUrl = blob => URL.createObjectURL(blob), revokeUrl = url => URL.revokeObjectURL(url), makeBlob = (bytes, type) => new Blob([bytes], { type }) } = {}) {
    let active = null;
    function stop() { active?.finish(Error('cancelled')); }
    function play(result, signal) {
      if (result.playback !== 'renderer') return Promise.resolve();
      stop();
      return new Promise((resolve, reject) => {
        if (signal.aborted) { reject(Error('cancelled')); return; }
        const bytes = result.audio instanceof ArrayBuffer ? result.audio : ArrayBuffer.isView(result.audio) ? result.audio.buffer.slice(result.audio.byteOffset, result.audio.byteOffset + result.audio.byteLength) : null;
        if (!bytes?.byteLength) { reject(Error('Missing audio')); return; }
        const url = createUrl(makeBlob(bytes, result.mimeType || 'audio/mpeg')); const audio = makeAudio(url); let settled = false;
        const finish = error => {
          if (settled) return; settled = true;
          signal.removeEventListener('abort', abort); audio.removeEventListener('ended', ended); audio.removeEventListener('error', failed);
          audio.pause(); audio.removeAttribute('src'); audio.load(); revokeUrl(url); if (active?.finish === finish) active = null;
          if (error) reject(error); else resolve();
        };
        const abort = () => finish(Error('cancelled')), ended = () => finish(), failed = () => finish(Error('Playback failed'));
        active = { finish }; audio.volume = Math.max(0, Math.min(1, result.volume ?? 1));
        signal.addEventListener('abort', abort, { once: true }); audio.addEventListener('ended', ended, { once: true }); audio.addEventListener('error', failed, { once: true });
        Promise.resolve().then(() => settled ? undefined : audio.play()).catch(failed);
      });
    }
    return { play, stop };
  }
  return { createPlayback };
});
