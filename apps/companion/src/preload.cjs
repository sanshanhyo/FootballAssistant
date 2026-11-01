'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const invoke = (name, ...args) => ipcRenderer.invoke(`companion:${name}`, ...args);
const isSettings = process.argv.includes('--companion-window=settings');
const common = {
  getState: () => invoke('get-state'),
  gameStatus: () => invoke('game-status'),
  refreshReaderPreviews: () => invoke('refresh-reader-previews'),
  setCaptureProfile: profile => invoke('set-capture-profile', profile),
  setMode: mode => invoke('set-mode', mode),
  cancelRequest: id => invoke('cancel-request', id),
  newConversation: () => invoke('new-conversation'),
  setProactivity: percent => invoke('set-proactivity', percent),
  setPreferences: patch => invoke('set-preferences', patch),
  simulateEvent: kind => invoke('simulate-event', kind),
  getHistory: () => invoke('get-history'),
  clearHistory: () => invoke('clear-history'),
  setHistoryEnabled: enabled => invoke('set-history-enabled', enabled),
  getMemories: () => invoke('get-memories'),
  saveMemory: memory => invoke('save-memory', memory),
  deleteMemory: id => invoke('delete-memory', id),
  openSettings: () => invoke('open-settings'),
  speechCapabilities: () => invoke('speech-capabilities'),
  stopSpeech: () => invoke('stop-speech'),
  quit: () => invoke('quit'),
  subscribe: callback => {
    if (typeof callback !== 'function') throw new Error('订阅回调无效。');
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('companion:event', listener);
    return () => ipcRenderer.removeListener('companion:event', listener);
  },
};
const pet = {
  sendMessage: input => invoke('send-message', input),
  showContextMenu: () => invoke('context-menu'),
  microphonePermission: () => invoke('microphone-permission'),
  transcribe: input => invoke('transcribe', input),
  cancelSpeechOperation: id => invoke('cancel-speech-operation', id),
  speak: input => invoke('speak', input),
  dragStart: () => invoke('drag-start'), dragMove: () => invoke('drag-move'), dragEnd: () => invoke('drag-end'),
  inputRects: rects => ipcRenderer.send('companion:input-rects', rects),
};
contextBridge.exposeInMainWorld('companion', isSettings ? { ...common, controlSettingsWindow: action => invoke('settings-window-control', action), windowsDiscoveryImport: input => invoke('windows-discovery-import', input), windowsDiscoveryGet: () => invoke('windows-discovery-get'), windowsDiscoveryClear: () => invoke('windows-discovery-clear'), bridgeInspect: () => invoke('bridge-inspect'), bridgePlan: () => invoke('bridge-plan'), bridgeDeploy: input => invoke('bridge-deploy', input), bridgeRollback: () => invoke('bridge-rollback'), personaStatus: () => invoke('persona-status'), getPersona: () => invoke('persona-get'), savePersona: input => invoke('persona-save', input), getCharacterIntroduction: () => invoke('character-introduction'), getAbout: () => invoke('about-get'), openRepository: () => invoke('repository-open'), openContributors: () => invoke('contributors-open'), openPersonaFile: () => invoke('persona-open-file'), openPersonaFolder: () => invoke('persona-open-folder'), openUpdateRelease: () => invoke('update-open-release'), bootstrapStatus: () => invoke('bootstrap-status'), updateStatus: () => invoke('update-status'), checkUpdate: () => invoke('update-check'), downloadUpdate: () => invoke('update-download'), getModelProviders: () => invoke('model-providers-get'), listModels: input => invoke('model-models-list', input), cancelModelList: () => invoke('model-models-cancel'), getModelConfig: () => invoke('model-config-get'), saveModelConfig: input => invoke('model-config-save', input) } : { ...common, ...pet });
