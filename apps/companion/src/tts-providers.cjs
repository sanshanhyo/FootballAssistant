'use strict';
// Trusted main-process adapters only. Never accept executable code/configuration from IPC.
function speechSettings(payload, fail) {
  const speed = payload.speed ?? 1;
  const volume = payload.volume ?? 1;
  if (typeof speed !== 'number' || !Number.isFinite(speed) || speed < 0.5 || speed > 2
      || typeof volume !== 'number' || !Number.isFinite(volume) || volume < 0 || volume > 1) {
    fail('invalid-settings', '语速应为 0.5–2，音量应为 0–1。');
  }
  return { speed, volume };
}
function createTtsProviders({ config, request, edgeAudio, requireVoice, escapeXml, fail, maxAudioBytes }) {
  const MAX_AUDIO_BYTES = maxAudioBytes;
  return new Map(['openai', 'azure', 'edge'].map(id => [id, {
    async synthesize(payload, signal) {
      const settings = speechSettings(payload, fail);
      let bytes;
      if (id === 'openai') {
        if (payload.text.length > 4096) fail('invalid-text', '此语音服务单次最多支持 4096 个字符。');
        bytes = await request(`${config.baseUrl}/audio/speech`, {
          method: 'POST', headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: config.ttsModel, input: payload.text, voice: requireVoice(payload.voice || config.ttsVoice), response_format: 'mp3', speed: settings.speed }),
        }, MAX_AUDIO_BYTES, signal, true);
      } else if (id === 'azure') {
        const voice = requireVoice(payload.voice || config.azureVoice);
        const language = voice.match(/^[A-Za-z]{2,3}-[A-Za-z]{2,4}/u)?.[0];
        if (!language) fail('invalid-voice', 'Azure 音色需要包含语言和区域。');
        const ssml = `<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="${language}"><voice name="${voice}"><prosody rate="${Math.round((settings.speed - 1) * 100)}%">${escapeXml(payload.text)}</prosody></voice></speak>`;
        bytes = await request(`https://${config.azureRegion}.tts.speech.microsoft.com/cognitiveservices/v1`, {
          method: 'POST', headers: {
            'Ocp-Apim-Subscription-Key': config.azureKey, 'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3', 'User-Agent': 'FootballAssistant-Companion',
          }, body: ssml,
        }, MAX_AUDIO_BYTES, signal, true);
      } else {
        bytes = await edgeAudio(payload.text, requireVoice(payload.voice || config.edgeVoice), signal, settings);
      }
      return { bytes, mimeType: 'audio/mpeg', volume: settings.volume };
    },
  }]));
}
module.exports = { createTtsProviders, speechSettings };
