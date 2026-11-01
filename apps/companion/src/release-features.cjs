'use strict';
// Alpha 0.0.1 ships without TTS; preserve the implementation for a later release.
const ALPHA_TTS_ENABLED = false;
function speakWhenEnabled(speak) {
  if (!ALPHA_TTS_ENABLED) throw new Error('TTS is disabled in Alpha 0.0.1');
  return speak();
}
module.exports = { ALPHA_TTS_ENABLED, speakWhenEnabled };
