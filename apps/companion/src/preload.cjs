'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const invoke = (name, ...args) => ipcRenderer.invoke(`companion:${name}`, ...args);
contextBridge.exposeInMainWorld('companion', {
  status: () => invoke('status'),
  monitoring: () => invoke('monitoring'),
  events: after => invoke('events', after),
  chat: input => invoke('chat', input),
  chooseRuntime: () => invoke('choose-runtime'),
  speak: text => invoke('speak', text),
  stopSpeech: () => invoke('stop-speech'),
  quit: () => invoke('quit'),
  dragStart: () => invoke('drag-start'),
  dragMove: () => invoke('drag-move'),
  dragEnd: () => invoke('drag-end'),
  inputRects: rects => ipcRenderer.send('companion:input-rects', rects),
  onSpeech: callback => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('companion:tts-state', listener);
    return () => ipcRenderer.removeListener('companion:tts-state', listener);
  },
});
