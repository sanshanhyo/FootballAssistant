'use strict';
// Alpha 0.0.2 capability; explicit user opt-in is additionally enforced by speech-config.
const ALPHA_TTS_ENABLED = true;
function speakWhenEnabled(speak) {
  if (!ALPHA_TTS_ENABLED) throw new Error('TTS is unavailable');
  return speak();
}
module.exports = { ALPHA_TTS_ENABLED, speakWhenEnabled };
