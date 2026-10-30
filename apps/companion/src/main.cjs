'use strict';
const { app, BrowserWindow, ipcMain, screen, dialog, Menu } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const backend = require('./backend.cjs');
const { createSpeech } = require('./tts.cjs');
const { resolveRect } = require('./vendor/displays.cjs');

let win;
let runtimeFile;
let inputRects = [];
let drag = null;
let ignoring = false;
let pointerTimer;
let lastDragAt = 0;
const page = path.join(__dirname, 'index.html');
const pageUrl = pathToFileURL(page).href;
const smokePath = process.env.FOOTBALL_ASSISTANT_SMOKE_REPORT;

function emit(channel, value) { if (win && !win.isDestroyed()) win.webContents.send(channel, value); }
const speech = createSpeech(state => emit('companion:tts-state', state));
function senderAllowed(event) { return win && event.sender === win.webContents && event.senderFrame?.url === pageUrl; }
function handle(name, action) {
  ipcMain.handle(name, async (event, ...args) => {
    if (!senderAllowed(event)) throw new Error('无效的窗口请求。');
    try { return { ok: true, value: await action(...args) }; }
    catch (error) { return { ok: false, error: error.message || '请求失败。' }; }
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
  win.setIgnoreMouseEvents(next, { forward: true });
  ignoring = next;
}
function pointerFallback() {
  if (!win || win.isDestroyed()) return;
  if (drag) {
    if (Date.now() - lastDragAt > 2_000) drag = null;
    else { setIgnoring(false); return; }
  }
  const point = screen.getCursorScreenPoint();
  const bounds = win.getBounds();
  const hit = inputRects.some(rect => point.x >= bounds.x + rect.x && point.x < bounds.x + rect.x + rect.width &&
    point.y >= bounds.y + rect.y && point.y < bounds.y + rect.y + rect.height);
  setIgnoring(!hit);
}
async function chooseRuntime() {
  const selected = await dialog.showOpenDialog(win, {
    title: '选择 FootballAssistant 服务的 runtime.json',
    defaultPath: runtimeFile,
    filters: [{ name: '连接文件', extensions: ['json'] }],
    properties: ['openFile'],
  });
  if (selected.canceled || !selected.filePaths[0]) return { selected: false };
  const candidate = selected.filePaths[0];
  await backend.readRuntime(candidate);
  runtimeFile = candidate;
  await fs.mkdir(app.getPath('userData'), { recursive: true });
  await fs.writeFile(path.join(app.getPath('userData'), 'connection.json'), JSON.stringify({ runtimeFile }), { mode: 0o600 });
  return { selected: true };
}
function registerIpc() {
  handle('companion:status', () => backend.request(runtimeFile, '/v1/status'));
  handle('companion:monitoring', () => backend.request(runtimeFile, '/v1/monitoring'));
  handle('companion:events', after => {
    if (!Number.isSafeInteger(after) || after < 0) throw new Error('监听游标无效。');
    return backend.request(runtimeFile, `/v1/events?after=${after}&limit=100`);
  });
  handle('companion:chat', input => {
    if (!input || typeof input.message !== 'string' || !input.message.trim() || input.message.length > 4_000) throw new Error('请输入 1–4000 字的消息。');
    const body = { message: input.message.trim() };
    if (input.conversation_id !== undefined) {
      if (typeof input.conversation_id !== 'string' || input.conversation_id.length > 128) throw new Error('会话标识无效。');
      body.conversation_id = input.conversation_id;
    }
    return backend.request(runtimeFile, '/v1/chat', body);
  });
  handle('companion:choose-runtime', chooseRuntime);
  handle('companion:speak', text => speech.speak(text));
  handle('companion:stop-speech', () => speech.stop());
  handle('companion:quit', () => app.quit());
  handle('companion:drag-start', () => {
    const point = screen.getCursorScreenPoint();
    const bounds = win.getBounds();
    drag = { x: point.x - bounds.x, y: point.y - bounds.y };
    lastDragAt = Date.now();
    setIgnoring(false);
  });
  handle('companion:drag-move', () => {
    if (!drag) return;
    const point = screen.getCursorScreenPoint();
    lastDragAt = Date.now();
    win.setBounds(visibleBounds({ ...win.getBounds(), x: point.x - drag.x, y: point.y - drag.y }));
  });
  handle('companion:drag-end', () => { drag = null; });
  ipcMain.on('companion:input-rects', (event, rects) => {
    if (!senderAllowed(event) || !Array.isArray(rects) || rects.length > 20) return;
    inputRects = rects.filter(rect => rect && ['x','y','width','height'].every(key => Number.isFinite(rect[key]) && Math.abs(rect[key]) <= 10_000) && rect.width > 0 && rect.height > 0);
    pointerFallback();
  });
}
async function buildWindow() {
  const primary = screen.getPrimaryDisplay().workArea;
  win = new BrowserWindow({
    width: 390, height: Math.min(620, primary.height),
    x: primary.x + primary.width - 414, y: primary.y + primary.height - Math.min(644, primary.height),
    frame: false, transparent: true, backgroundColor: '#00000000',
    resizable: false, maximizable: false, fullscreenable: false,
    alwaysOnTop: true, skipTaskbar: false, show: false, hasShadow: false,
    title: 'FootballAssistant',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setAlwaysOnTop(true, process.platform === 'darwin' ? 'floating' : 'normal');
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  win.once('ready-to-show', () => { win.show(); pointerFallback(); });
  await win.loadFile(page);
  pointerTimer = setInterval(pointerFallback, 60);
  screen.on('display-removed', () => { if (win && !win.isDestroyed()) win.setBounds(visibleBounds(win.getBounds())); });
  if (smokePath) {
    const report = {
      platform: process.platform, arch: process.arch, electron: process.versions.electron,
      window: { transparentConfigured: true, backgroundColor: win.getBackgroundColor(), alwaysOnTop: win.isAlwaysOnTop(), bounds: win.getBounds(), contextIsolation: win.webContents.getLastWebPreferences().contextIsolation, nodeIntegration: win.webContents.getLastWebPreferences().nodeIntegration, sandbox: win.webContents.getLastWebPreferences().sandbox },
      renderer: await win.webContents.executeJavaScript('({title: document.title, bridge: Boolean(window.companion), nodeExposed: typeof require !== "undefined", pet: Boolean(document.getElementById("pet"))})'),
    };
    await fs.mkdir(path.dirname(smokePath), { recursive: true });
    await fs.writeFile(smokePath, JSON.stringify(report, null, 2));
    await win.webContents.capturePage().then(image => fs.writeFile(smokePath.replace(/\.json$/, '.png'), image.toPNG()));
    if (process.env.FOOTBALL_ASSISTANT_SMOKE_EXIT === '1') setTimeout(() => app.quit(), 300);
  }
}
async function main() {
  runtimeFile = process.env.FOOTBALL_ASSISTANT_RUNTIME_FILE || path.resolve(__dirname, '../../../local-data/runtime.json');
  if (!process.env.FOOTBALL_ASSISTANT_RUNTIME_FILE) {
    try { runtimeFile = JSON.parse(await fs.readFile(path.join(app.getPath('userData'), 'connection.json'), 'utf8')).runtimeFile || runtimeFile; }
    catch { /* first launch */ }
  }
  registerIpc();
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: 'FootballAssistant', submenu: [
    { label: '显示伙伴', click: () => win?.show() },
    { label: '选择服务连接文件…', click: () => chooseRuntime().catch(error => dialog.showErrorBox('连接失败', error.message)) },
    { label: '停止朗读', click: () => speech.stop() }, { type: 'separator' }, { role: 'quit', label: '退出' },
  ]}]));
  await buildWindow();
  app.on('activate', () => win?.show());
}
app.whenReady().then(main).catch(error => { console.error(error.message); app.exit(1); });
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => { clearInterval(pointerTimer); speech.stop(); });
