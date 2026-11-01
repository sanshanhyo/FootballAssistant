'use strict';
function controlSettingsWindow(window, action, defer = setImmediate) {
  if (!window || window.isDestroyed()) throw new Error('设置窗口已关闭。');
  if (action === 'minimize') window.minimize();
  else if (action === 'toggle-maximize') window.isMaximized() ? window.unmaximize() : window.maximize();
  // Let the IPC reply finish before destroying its sender. close() still runs
  // beforeunload, including the renderer's unsaved-persona confirmation.
  else if (action === 'close') defer(() => { if (!window.isDestroyed()) window.close(); });
  else throw new Error('不支持的窗口操作。');
  return { requested: true };
}
module.exports = { controlSettingsWindow };
