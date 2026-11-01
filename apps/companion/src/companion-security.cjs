'use strict';
const { fileURLToPath } = require('node:url');

function sameLocalPage(currentUrl, pageUrl) {
  if (typeof currentUrl !== 'string' || typeof pageUrl !== 'string' || !pageUrl) return false;
  if (currentUrl === pageUrl) return true;
  try {
    const current = new URL(currentUrl), expected = new URL(pageUrl);
    if (current.protocol !== 'file:' || expected.protocol !== 'file:' || current.host || expected.host ||
        current.search || expected.search || current.hash || expected.hash) return false;
    // Node escapes ADMINI~1 as ADMINI%7E1; Chromium leaves the tilde intact.
    // Decoding only local paths preserves the page boundary. Encoded separators
    // and malformed escapes are rejected by fileURLToPath.
    return fileURLToPath(current) === fileURLToPath(expected);
  } catch { return false; }
}

const SHARED_IPC = [
  'get-state', 'game-status', 'refresh-reader-previews', 'set-capture-profile', 'set-mode', 'cancel-request', 'new-conversation', 'set-proactivity', 'set-preferences',
  'simulate-event', 'get-history', 'clear-history', 'set-history-enabled', 'get-memories',
  'save-memory', 'delete-memory', 'open-settings', 'speech-capabilities', 'stop-speech', 'quit',
];
const WINDOW_IPC = Object.freeze({
  pet: new Set([...SHARED_IPC, 'send-message', 'context-menu', 'transcribe', 'speak',
    'cancel-speech-operation', 'microphone-permission', 'drag-start', 'drag-move', 'drag-end', 'input-rects']),
  settings: new Set([...SHARED_IPC, 'settings-window-control', 'windows-discovery-import', 'windows-discovery-get', 'windows-discovery-clear', 'bridge-inspect', 'bridge-plan', 'bridge-deploy', 'bridge-rollback', 'persona-get', 'persona-save', 'character-introduction', 'about-get', 'repository-open', 'contributors-open', 'persona-status', 'persona-open-file', 'persona-open-folder', 'update-open-release', 'model-providers-get', 'model-models-list', 'model-models-cancel', 'model-config-get', 'model-config-save', 'bootstrap-status', 'update-status', 'update-check', 'update-download']),
});

function allowsWindowIpc({ role, trustedMainFrame, currentUrl, pageUrl }, method) {
  return Boolean(trustedMainFrame && sameLocalPage(currentUrl, pageUrl) && Object.hasOwn(WINDOW_IPC, role) && WINDOW_IPC[role].has(method));
}

function stopSpeechForRole(role, { stop, notifyPet }) {
  if (role !== 'pet' && role !== 'settings') throw new Error('无效的窗口角色。');
  const result = stop();
  // The pet already cleans up before requesting a stop. Echoing it can cancel its next operation.
  if (role === 'settings') notifyPet({ type: 'stop-speech', reason: '设置中停止语音' });
  return result;
}

function allowsMicrophone({ trustedContents, currentUrl, pageUrl }, permission, details, check = false) {
  if (!trustedContents || !sameLocalPage(currentUrl, pageUrl) || permission !== 'media' || details?.isMainFrame !== true || !sameLocalPage(details?.requestingUrl, pageUrl)) return false;
  // Electron permission checks use mediaType; requests use mediaTypes.
  if (check) return details.mediaType === 'audio';
  return Array.isArray(details.mediaTypes) && details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio';
}

module.exports = { sameLocalPage, allowsMicrophone, allowsWindowIpc, stopSpeechForRole };
