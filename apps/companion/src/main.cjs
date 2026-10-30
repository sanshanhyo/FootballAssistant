'use strict';
const { app, BrowserWindow, ipcMain, screen, Menu, Tray, nativeImage, systemPreferences } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { CompanionRuntime } = require('./companion-runtime.cjs');
const { createSpeechService } = require('./speech-service.cjs');
const { allowsMicrophone, allowsWindowIpc, stopSpeechForRole } = require('./companion-security.cjs');
const { resolveRect } = require('./vendor/displays.cjs');

if (process.env.FA_COMPANION_USER_DATA_DIR) {
  const isolatedPath = process.env.FA_COMPANION_USER_DATA_DIR;
  if (!path.isAbsolute(isolatedPath)) throw new Error('测试用户目录必须使用绝对路径。');
  require('node:fs').mkdirSync(isolatedPath, { recursive: true });
  app.setPath('userData', isolatedPath);
}

let win;
let settingsWindow;
let tray;
let runtime;
let quitting = false;
let inputRects = [];
let drag = null;
let ignoring = false;
let pointerTimer;
let lastDragAt = 0;
const page = path.join(__dirname, 'index.html');
const pageUrl = pathToFileURL(page).href;
const settingsPage = path.join(__dirname, 'settings.html');
const settingsPageUrl = pathToFileURL(settingsPage).href;
const smokePath = process.env.FOOTBALL_ASSISTANT_SMOKE_REPORT;
function emit(value) {
  for (const window of [win, settingsWindow]) {
    if (window && !window.isDestroyed() && !window.webContents.isDestroyed()) window.webContents.send('companion:event', value);
  }
}
function emitPet(value) { if (win && !win.isDestroyed() && !win.webContents.isDestroyed()) win.webContents.send('companion:event', value); }
const speech = createSpeechService({ onState: state => emit({ type: 'speech', state }) });
function senderRole(event, method) {
  for (const [role, window, url] of [['pet', win, pageUrl], ['settings', settingsWindow, settingsPageUrl]]) {
    if (!window || window.isDestroyed() || event.sender !== window.webContents) continue;
    return allowsWindowIpc({ role, currentUrl: event.senderFrame?.url, pageUrl: url,
      trustedMainFrame: event.senderFrame === window.webContents.mainFrame }, method) ? role : null;
  }
  return null;
}
function senderAllowed(event, method) { return Boolean(senderRole(event, method)); }
function handle(name, action, { withSender = false } = {}) {
  ipcMain.handle(`companion:${name}`, async (event, ...args) => {
    const role = senderRole(event, name);
    if (!role) return { ok: false, error: '无效的窗口请求。' };
    try { return { ok: true, value: await (withSender ? action({ role }, ...args) : action(...args)) }; }
    catch (error) { return { ok: false, error: error.message || '请求失败。', ...(error.code ? { code: error.code } : {}) }; }
  });
}
function visibleBounds(bounds) {
  const areas = screen.getAllDisplays().map(display => display.workArea);
  const area = resolveRect(areas, bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  if (!area) return bounds;
  return { ...bounds,
    x: Math.round(Math.min(Math.max(bounds.x, area.x), Math.max(area.x, area.x + area.width - bounds.width))),
    y: Math.round(Math.min(Math.max(bounds.y, area.y), Math.max(area.y, area.y + area.height - bounds.height))),
  };
}
function setIgnoring(next) {
  if (!win || win.isDestroyed() || next === ignoring) return;
  win.setIgnoreMouseEvents(next, { forward: true }); ignoring = next;
}
function pointerFallback() {
  if (!win || win.isDestroyed() || !win.isVisible()) return;
  if (drag) {
    if (Date.now() - lastDragAt > 2_000) drag = null;
    else { setIgnoring(false); return; }
  }
  const point = screen.getCursorScreenPoint(); const bounds = win.getBounds();
  const hit = inputRects.some(rect => point.x >= bounds.x + rect.x && point.x < bounds.x + rect.x + rect.width && point.y >= bounds.y + rect.y && point.y < bounds.y + rect.y + rect.height);
  setIgnoring(!hit);
}
function showPet() { if (win && !win.isDestroyed()) { win.show(); win.focus(); pointerFallback(); emitPet({ type: 'visibility', visible: true }); } }
function hidePet() { if (win && !win.isDestroyed()) { speech.stop(); emitPet({ type: 'visibility', visible: false }); win.hide(); } }
async function openSettings() {
  if (settingsWindow && !settingsWindow.isDestroyed()) { settingsWindow.show(); settingsWindow.focus(); return { opened: true }; }
  const area = screen.getPrimaryDisplay().workArea;
  const window = new BrowserWindow({ width: Math.min(960, area.width), height: Math.min(740, area.height),
    minWidth: Math.min(580, area.width), minHeight: Math.min(420, area.height),
    title: 'FootballAssistant 设置', backgroundColor: '#111714', show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), additionalArguments: ['--companion-window=settings'], contextIsolation: true, nodeIntegration: false, sandbox: true, partition: 'companion-settings' } });
  settingsWindow = window;
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.webContents.session.setPermissionCheckHandler(() => false);
  window.on('closed', () => { if (settingsWindow === window) settingsWindow = null; });
  try {
    await window.loadFile(settingsPage);
    if (!window.isDestroyed()) window.show();
  } catch (error) {
    if (!window.isDestroyed()) window.destroy();
    throw error;
  }
  return { opened: true };
}
function contextMenu() {
  return Menu.buildFromTemplate([
    { label: win?.isVisible() ? '隐藏桌宠' : '显示桌宠', click: () => win?.isVisible() ? hidePet() : showPet() },
    { label: '设置…', click: () => openSettings().catch(() => {}) },
    { label: '朗读上一条回复', enabled: Boolean(runtime?.state().messages.some(message => message.role === 'assistant')), click: () => { showPet(); emitPet({ type: 'read-last-reply' }); } },
    { label: '停止语音', click: () => { speech.stop(); emit({ type: 'stop-speech' }); } },
    { type: 'separator' }, { label: '退出', click: () => app.quit() },
  ]);
}
function trayImage() {
  const size = 20; const data = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const radius = Math.hypot(x - 9.5, y - 9.5);
    if (radius > 8.5) continue;
    const index = (y * size + x) * 4;
    const hole = radius < 3 || (Math.abs(x - 9.5) < 1.1 && radius > 5.5) || (Math.abs(y - 9.5) < 1.1 && radius > 5.5);
    data[index] = process.platform === 'darwin' ? 0 : 30;
    data[index + 1] = process.platform === 'darwin' ? 0 : 105;
    data[index + 2] = process.platform === 'darwin' ? 0 : 72;
    data[index + 3] = hole ? 0 : 255;
  }
  const image = nativeImage.createFromBitmap(data, { width: size, height: size, scaleFactor: 1 });
  if (process.platform === 'darwin') image.setTemplateImage(true);
  return image;
}
function registerIpc() {
  handle('get-state', () => runtime.state());
  handle('set-mode', mode => { speech.stop(); return runtime.setMode(mode); });
  handle('send-message', input => runtime.sendMessage(input));
  handle('cancel-request', id => runtime.cancelRequest(id));
  handle('new-conversation', () => { speech.stop(); return runtime.switchSession(); });
  handle('set-proactivity', value => runtime.setProactivity(value));
  handle('set-preferences', patch => {
    const before = runtime.state().preferences;
    const next = runtime.setPreferences(patch);
    if (before.sttProvider !== next.preferences.sttProvider || before.ttsProvider !== next.preferences.ttsProvider) {
      speech.stop();
    }
    return next;
  });
  handle('simulate-event', kind => runtime.simulateEvent(kind));
  handle('get-history', () => runtime.getHistory());
  handle('clear-history', () => { speech.stop(); return runtime.clearHistory(); });
  handle('set-history-enabled', value => runtime.setHistoryEnabled(value));
  handle('get-memories', () => runtime.getMemories());
  handle('save-memory', value => runtime.saveMemory(value));
  handle('delete-memory', id => runtime.deleteMemory(id));
  handle('open-settings', openSettings);
  handle('context-menu', () => { contextMenu().popup({ window: win }); return {}; });
  handle('speech-capabilities', () => speech.capabilities());
  function speechInput(input) {
    if (!input || input.generation !== runtime.epoch || input.conversationId !== runtime.sessionId) throw new Error('语音所属会话已切换。');
    return input;
  }
  handle('transcribe', input => speech.transcribe(speechInput(input)));
  handle('speak', input => speech.speak(speechInput(input)));
  handle('cancel-speech-operation', id => speech.cancel(id));
  handle('stop-speech', ({ role }) => stopSpeechForRole(role, { stop: () => speech.stop(), notifyPet: emitPet }), { withSender: true });
  handle('microphone-permission', async () => {
    if (process.platform !== 'darwin') return { state: 'prompt' };
    const state = systemPreferences.getMediaAccessStatus('microphone');
    if (state === 'not-determined') return { state: await systemPreferences.askForMediaAccess('microphone') ? 'granted' : 'denied' };
    return { state };
  });
  handle('quit', () => app.quit());
  handle('drag-start', () => {
    const point = screen.getCursorScreenPoint(); const bounds = win.getBounds();
    drag = { x: point.x - bounds.x, y: point.y - bounds.y }; lastDragAt = Date.now(); setIgnoring(false);
  });
  handle('drag-move', () => {
    if (!drag) return;
    const point = screen.getCursorScreenPoint(); lastDragAt = Date.now();
    win.setBounds(visibleBounds({ ...win.getBounds(), x: point.x - drag.x, y: point.y - drag.y }));
  });
  handle('drag-end', () => { drag = null; });
  ipcMain.on('companion:input-rects', (event, rects) => {
    if (!senderAllowed(event, 'input-rects') || !Array.isArray(rects) || rects.length > 30) return;
    inputRects = rects.filter(rect => rect && ['x', 'y', 'width', 'height'].every(key => Number.isFinite(rect[key]) && Math.abs(rect[key]) <= 10_000) && rect.width > 0 && rect.height > 0);
    pointerFallback();
  });
}
function permitMicrophone(contents, permission, details, check = false) {
  return allowsMicrophone({ trustedContents: Boolean(win && !win.isDestroyed() && contents === win.webContents), currentUrl: contents?.getURL(), pageUrl }, permission, details, check);
}
async function buildWindow() {
  const primary = screen.getPrimaryDisplay().workArea;
  const width = Math.min(520, primary.width); const height = Math.min(620, primary.height);
  win = new BrowserWindow({
    width, height, x: Math.max(primary.x, primary.x + primary.width - width - 24), y: Math.max(primary.y, primary.y + primary.height - height - 24),
    frame: false, transparent: true, backgroundColor: '#00000000', resizable: false, maximizable: false, fullscreenable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false, hasShadow: false, title: 'FootballAssistant',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), additionalArguments: ['--companion-window=pet'], contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setAlwaysOnTop(true, process.platform === 'darwin' ? 'floating' : 'normal');
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  win.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => callback(permitMicrophone(contents, permission, details)));
  win.webContents.session.setPermissionCheckHandler((contents, permission, _origin, details) => permitMicrophone(contents, permission, details, true));
  win.on('close', event => { if (!quitting) { event.preventDefault(); hidePet(); } });
  win.once('ready-to-show', showPet);
  await win.loadFile(page);
  pointerTimer = setInterval(pointerFallback, 60);
  screen.on('display-removed', () => { if (win && !win.isDestroyed()) win.setBounds(visibleBounds(win.getBounds())); });
  if (smokePath) {
    const report = {
      platform: process.platform, arch: process.arch, electron: process.versions.electron,
      window: { transparentConfigured: true, backgroundColor: win.getBackgroundColor(), alwaysOnTop: win.isAlwaysOnTop(), bounds: win.getBounds(), contextIsolation: win.webContents.getLastWebPreferences().contextIsolation, nodeIntegration: win.webContents.getLastWebPreferences().nodeIntegration, sandbox: win.webContents.getLastWebPreferences().sandbox },
      runtime: runtime.state(),
      renderer: await win.webContents.executeJavaScript('({title: document.title, bridge: Boolean(window.companion), nodeExposed: typeof require !== "undefined", pet: Boolean(document.getElementById("pet"))})'),
    };
    await fs.mkdir(path.dirname(smokePath), { recursive: true });
    await fs.writeFile(smokePath, JSON.stringify(report, null, 2));
    await win.webContents.capturePage().then(image => fs.writeFile(smokePath.replace(/\.json$/, '.png'), image.toPNG()));
    if (process.env.FOOTBALL_ASSISTANT_SMOKE_EXIT === '1') setTimeout(() => app.quit(), 300);
  }
}
async function main() {
  runtime = new CompanionRuntime({ file: path.join(app.getPath('userData'), 'companion-ui.json') });
  await runtime.init(); runtime.on('event', emit);
  registerIpc();
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: 'FootballAssistant', submenu: [
    { label: '显示桌宠', click: showPet }, { label: '隐藏桌宠', click: hidePet },
    { label: '设置…', click: () => openSettings().catch(() => {}) },
    { type: 'separator' }, { role: 'quit', label: '退出' },
  ] }]));
  await buildWindow();
  tray = new Tray(trayImage()); tray.setToolTip('FootballAssistant · 桌宠');
  tray.on('click', () => contextMenu().popup()); tray.on('double-click', showPet);
  tray.on('right-click', () => contextMenu().popup());
  app.on('activate', showPet);
}
app.whenReady().then(main).catch(error => { console.error(error.message); app.exit(1); });
app.on('window-all-closed', () => { /* The tray owns application lifetime. */ });
app.on('before-quit', event => {
  if (quitting) return;
  event.preventDefault(); quitting = true;
  clearInterval(pointerTimer); speech.dispose(); tray?.destroy();
  Promise.resolve(runtime?.close()).finally(() => app.quit());
});
