'use strict';

const SHARED_IPC = [
  'get-state', 'game-status', 'refresh-reader-previews', 'set-capture-profile', 'set-mode', 'cancel-request', 'new-conversation', 'set-proactivity', 'set-preferences',
  'simulate-event', 'get-history', 'clear-history', 'set-history-enabled', 'get-memories',
  'save-memory', 'delete-memory', 'open-settings', 'speech-capabilities', 'stop-speech', 'quit',
];
const WINDOW_IPC = Object.freeze({
  pet: new Set([...SHARED_IPC, 'send-message', 'context-menu', 'transcribe', 'speak',
    'cancel-speech-operation', 'microphone-permission', 'drag-start', 'drag-move', 'drag-end', 'input-rects']),
  settings: new Set([...SHARED_IPC, 'persona-status', 'persona-open-file', 'persona-open-folder', 'update-open-release', 'model-config-get', 'model-config-save', 'bootstrap-status', 'update-status', 'update-check', 'update-download']),
});

function allowsWindowIpc({ role, trustedMainFrame, currentUrl, pageUrl }, method) {
  return Boolean(trustedMainFrame && currentUrl === pageUrl && Object.hasOwn(WINDOW_IPC, role) && WINDOW_IPC[role].has(method));
}

function stopSpeechForRole(role, { stop, notifyPet }) {
  if (role !== 'pet' && role !== 'settings') throw new Error('无效的窗口角色。');
  const result = stop();
  // The pet already cleans up before requesting a stop. Echoing it can cancel its next operation.
  if (role === 'settings') notifyPet({ type: 'stop-speech', reason: '设置中停止语音' });
  return result;
}

function allowsMicrophone({ trustedContents, currentUrl, pageUrl }, permission, details, check = false) {
  if (!trustedContents || currentUrl !== pageUrl || permission !== 'media' || details?.isMainFrame !== true || details?.requestingUrl !== pageUrl) return false;
  // Electron permission checks use mediaType; requests use mediaTypes.
  if (check) return details.mediaType === 'audio';
  return Array.isArray(details.mediaTypes) && details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio';
}

module.exports = { allowsMicrophone, allowsWindowIpc, stopSpeechForRole };
