'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const invoke = (name, ...args) => ipcRenderer.invoke(`companion:${name}`, ...args);
contextBridge.exposeInMainWorld('companion', {
  getState: () => invoke('get-state'),
  setMode: mode => invoke('set-mode', mode),
  sendMessage: input => invoke('send-message', input),
  cancelRequest: id => invoke('cancel-request', id),
  newConversation: () => invoke('new-conversation'),
  setProactivity: percent => invoke('set-proactivity', percent),
  simulateEvent: kind => invoke('simulate-event', kind),
  getHistory: () => invoke('get-history'),
  clearHistory: () => invoke('clear-history'),
  setHistoryEnabled: enabled => invoke('set-history-enabled', enabled),
  getMemories: () => invoke('get-memories'),
  saveMemory: memory => invoke('save-memory', memory),
  deleteMemory: id => invoke('delete-memory', id),
  openSettings: () => invoke('open-settings'),
  showContextMenu: () => invoke('context-menu'),
  speechCapabilities: () => invoke('speech-capabilities'),
  microphonePermission: () => invoke('microphone-permission'),
  transcribe: input => invoke('transcribe', input),
  cancelSpeechOperation: id => invoke('cancel-speech-operation', id),
  speak: input => invoke('speak', input),
  stopSpeech: () => invoke('stop-speech'),
  quit: () => invoke('quit'),
  dragStart: () => invoke('drag-start'), dragMove: () => invoke('drag-move'), dragEnd: () => invoke('drag-end'),
  inputRects: rects => ipcRenderer.send('companion:input-rects', rects),
  subscribe: callback => {
    if (typeof callback !== 'function') throw new Error('订阅回调无效。');
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('companion:event', listener);
    return () => ipcRenderer.removeListener('companion:event', listener);
  },
});
