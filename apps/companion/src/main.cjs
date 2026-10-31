'use strict';
const { app, BrowserWindow, ipcMain, screen, Menu, Tray, nativeImage, systemPreferences, dialog, safeStorage, shell, powerMonitor } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createPersonaAccess } = require('./persona-access.cjs');
const { createCredentialConfig } = require('./credentials.cjs');
const { createBridgeSetup } = require('./bridge-setup.cjs');
const { createBridgeDeployment } = require('./bridge-ipc.cjs');
const { createUpdateRecovery } = require('./update-recovery.cjs');
const { createUpdateLifecycle } = require('./update-lifecycle.cjs');
const updateTrust = require('./update-trust.cjs');
const { createInstalledUpdater } = require('./update-installed.cjs');
const { distribution } = require('./distribution.cjs');
const { createUpdateController } = require('./update-controller.cjs');
const { loadSettings, detectGame, BackendSupervisor } = require('./bootstrap.cjs');
const { RealReaderClient } = require('./reader-clients.cjs');
const { request, defaultRuntimeFile } = require('./backend.cjs');
const { CompanionRuntime } = require('./companion-runtime.cjs');
const { createSpeechService } = require('./speech-service.cjs');
const { ALPHA_TTS_ENABLED, speakWhenEnabled } = require('./release-features.cjs');
const { allowsMicrophone, allowsWindowIpc, stopSpeechForRole } = require('./companion-security.cjs');
const { resolveRect } = require('./vendor/displays.cjs');

if (process.env.FA_COMPANION_USER_DATA_DIR) {
  const isolatedPath = process.env.FA_COMPANION_USER_DATA_DIR;
  if (!path.isAbsolute(isolatedPath)) throw new Error('测试用户目录必须使用绝对路径。');
  require('node:fs').mkdirSync(isolatedPath, { recursive: true });
  app.setPath('userData', isolatedPath);
}

const primaryInstance = app.requestSingleInstanceLock();
if (!primaryInstance) app.quit();
app.on('second-instance', () => showPet());
let backendSupervisor;
let backendOptions;
let credentials;
let personaAccess;
let bridgeDeployment;
let savingModel = false;
let updateController;
let installedUpdates;
let updateRecovery;
let updateLifecycle;
let updateQuiescing = false;
let updateBackendStopped = false;
let updateSessionEnding = false;
let lastGameClearAt = 0;
let activeIpc = 0;
let speechPlaying = false;
let bootstrapStatus;
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
const speech = createSpeechService({ onState: state => { speechPlaying = !['finished', 'error', 'stopped'].includes(state.state); emit({ type: 'speech', state }); } });
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
    if (updateQuiescing) return { ok: false, error: '已验证更新正在安全重启，请稍候。' };
    activeIpc++;
    try { return { ok: true, value: await (withSender ? action({ role }, ...args) : action(...args)) }; }
    catch (error) { return { ok: false, error: error.message || '请求失败。', ...(error.code ? { code: error.code } : {}) }; }
    finally { activeIpc--; }
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
    { label: '朗读上一条回复', enabled: ALPHA_TTS_ENABLED && Boolean(runtime?.state().messages.some(message => message.role === 'assistant')), click: () => { showPet(); emitPet({ type: 'read-last-reply' }); } },
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
  bridgeDeployment.register(handle);
  handle('persona-status', () => personaAccess.status());
  handle('persona-open-file', () => personaAccess.open('file'));
  handle('persona-open-folder', () => personaAccess.open('folder'));
  handle('game-status', () => detectGame());
  handle('bootstrap-status', async () => {
    const backend = { ...backendSupervisor.status };
    if (backend.state === 'ready' && !(await backendSupervisor.healthy())) { backend.state = 'unavailable'; backend.message = '本机后端当前不可连接。'; }
    return { ...bootstrapStatus, backend, game: await detectGame() };
  });
  handle('model-config-get', () => credentials.getPublicConfig());
  handle('model-config-save', async input => {
    if (savingModel || quitting || bridgeDeployment?.busy) throw new Error('配置正在应用，请稍后再试。');
    savingModel = true;
    try {
      let saved;
      try { saved = await credentials.save(input); } catch { throw new Error('模型配置保存失败；请检查地址、模型名与本机安全存储。'); }
      if (backendSupervisor?.external || !app.isPackaged || (backendSupervisor?.status.state === 'ready' && !backendSupervisor.status.owned)) return { ...saved, restartRequired: true };
      await backendSupervisor?.stop();
      if (quitting) return { ...saved, restartRequired: true };
      backendSupervisor = new BackendSupervisor({ ...backendOptions, backendEnv: await credentials.backendEnv() });
      bootstrapStatus.backend = await backendSupervisor.start();
      return { ...saved, restartRequired: false, backendState: bootstrapStatus.backend.state };
    } finally { savingModel = false; }
  });
  handle('update-open-release', async () => { await shell.openExternal('https://github.com/sanshanhyo/FootballAssistant/releases'); return { opened: true }; });
  handle('update-status', () => ({ ...updateController.status, installation: installedUpdates.status, recovery: updateRecovery.status }));
  handle('update-check', () => updateController.check());
  handle('update-download', () => updateController.download());
  handle('get-state', () => runtime.state());
  handle('refresh-reader-previews', () => runtime.refreshReaderPreviews());
  handle('set-capture-profile', profile => runtime.setCaptureProfile(profile));
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
  handle('speak', input => speakWhenEnabled(() => speech.speak(speechInput(input))));
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
  win.on('query-session-end', () => { updateSessionEnding = true; updateLifecycle?.stop(); });
  win.on('session-end', () => { updateSessionEnding = true; updateLifecycle?.stop(); });
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
      runtime: runtime.state(), bootstrap: bootstrapStatus, updates: { ...updateController.status, installation: installedUpdates.status, recovery: updateRecovery.status },
      renderer: await win.webContents.executeJavaScript('({title: document.title, bridge: Boolean(window.companion), nodeExposed: typeof require !== "undefined", pet: Boolean(document.getElementById("pet"))})'),
    };
    await fs.mkdir(path.dirname(smokePath), { recursive: true });
    await fs.writeFile(smokePath, JSON.stringify(report, null, 2));
    await win.webContents.capturePage().then(image => fs.writeFile(smokePath.replace(/\.json$/, '.png'), image.toPNG()));
    if (process.env.FOOTBALL_ASSISTANT_SMOKE_EXIT === '1') setTimeout(() => app.quit(), 300);
  }
}
function updateSafeNow() {
  return !updateSessionEnding && (!quitting || updateQuiescing) && Boolean(runtime) && activeIpc === 0 && !savingModel && !bridgeDeployment?.busy && !speechPlaying && !win?.webContents.isCurrentlyAudible() && !drag
    && (updateQuiescing || (!win?.isFocused() && !settingsWindow?.isVisible())) && runtime.pending.size === 0 && !runtime.captureController
    && Date.now() - lastGameClearAt < 60000 && updateRecovery?.status.state !== 'recovery_required'
    && (updateQuiescing || powerMonitor.getSystemIdleTime() >= 60);
}
async function inspectUpdateActivity() {
  if (!runtime || quitting || updateSessionEnding || !updateSafeNowExceptGame()) return 'busy';
  const game = await detectGame();
  if (game.state !== 'not_detected') { lastGameClearAt = 0; return 'busy'; }
  // Unsaved draft/active microphone makes restarting unsafe even in background.
  const uiIdle = await win.webContents.executeJavaScript(`Boolean(document.getElementById('message')) && !document.getElementById('message').value && !document.hasFocus() && !['listening','transcribing','speaking','thinking'].includes(document.getElementById('pet')?.dataset.expression)`).catch(() => false);
  if (!uiIdle) return 'busy';
  lastGameClearAt = Date.now();
  return updateSafeNow() ? 'idle' : 'busy';
}
function updateSafeNowExceptGame() {
  return activeIpc === 0 && !savingModel && !bridgeDeployment?.busy && !speechPlaying && !win?.webContents.isCurrentlyAudible() && !drag && !win?.isFocused() && !settingsWindow?.isVisible()
    && runtime.pending.size === 0 && !runtime.captureController && powerMonitor.getSystemIdleTime() >= 60
    && updateRecovery?.status.state !== 'recovery_required';
}
async function prepareUpdateRestart({ targetVersion }) {
  // Re-check the actual process list; never stop Football Manager for an update.
  const game = await detectGame();
  if (game.state !== 'not_detected' || !updateSafeNow()) throw new Error('Update postponed: application/game became active');
  lastGameClearAt = Date.now();
  updateQuiescing = true; updateBackendStopped = false;
  const recovery = await updateRecovery.prepare({ targetVersion });
  if (recovery.state !== 'prepared') { updateQuiescing = false; throw new Error('Update recovery checkpoint could not be saved'); }
  await runtime.persist();
  if (runtime.storageWarning) { updateQuiescing = false; throw new Error('Conversation state could not be saved before update'); }
  updateBackendStopped = backendSupervisor.status.owned === true;
  await backendSupervisor.stop(); // Only the helper this app owns, never FM/external services.
  if ((await detectGame()).state !== 'not_detected' || updateSessionEnding) throw new Error('Update postponed: game started or Windows session is ending');
  lastGameClearAt = Date.now();
}
async function recoverFailedUpdate(error) {
  updateLifecycle?.stop(); updateController?.stop();
  try {
    await updateRecovery.fail(`Update installation blocked: ${error.message}`);
    // A final verification failure must not leave the chat backend silently stopped.
    // Recreate only our own supervisor; external services are never killed/replaced.
    if (updateBackendStopped && !quitting && !updateSessionEnding) {
      backendSupervisor = new BackendSupervisor({ ...backendOptions, backendEnv: credentials.getPublicConfig().configured ? await credentials.backendEnv() : {} });
      bootstrapStatus.backend = await backendSupervisor.start();
    }
  } catch {
    bootstrapStatus.backend = { state: 'failed', owned: false, message: '更新已中止；本机后端恢复失败，请重启应用。配置备份已保留。' };
  } finally {
    updateQuiescing = false; updateBackendStopped = false;
    emit({ type: 'update-status', state: { ...updateController.status, state: 'recovery_required', installation: installedUpdates.status, recovery: updateRecovery.status } });
  }
}
async function main() {
  updateRecovery = createUpdateRecovery({ userData: app.getPath('userData'), currentVersion: app.getVersion() });
  await updateRecovery.beginLaunch(); // Before configuration migration or app startup writes.
  const settings = await loadSettings(app.getPath('userData'));
  const external = Boolean(process.env.FOOTBALL_ASSISTANT_RUNTIME_FILE || process.argv.includes('--runtime-file'));
  const runtimeFile = external || !app.isPackaged ? defaultRuntimeFile(process.env, process.argv) : path.join(app.getPath('userData'), 'backend', 'runtime.json');
  credentials = createCredentialConfig({ userData: app.getPath('userData'), safeStorage });
  backendOptions = { userData: app.getPath('userData'), resourcesPath: process.resourcesPath, packaged: app.isPackaged, runtimeFile, external, settings };
  backendSupervisor = new BackendSupervisor({ ...backendOptions, backendEnv: credentials.getPublicConfig().configured ? await credentials.backendEnv() : {} });
  installedUpdates = createInstalledUpdater({ platform: process.platform,
    distribution: distribution({ packaged: app.isPackaged, executable: app.getPath('exe') }),
    currentVersion: app.getVersion(), arch: process.arch, configSchema: 1, backendProtocol: 1, bridgeProtocol: 1,
    productionTrust: updateTrust.productionTrust,
    isSafeToInstall: updateSafeNow, beforeInstall: prepareUpdateRestart, onInstallFailure: recoverFailedUpdate,
    onStatus: state => { emit({ type: 'update-status', state: { ...updateController?.status, installation: state, recovery: updateRecovery.status } });
    } });
  updateController = createUpdateController({ currentVersion: app.getVersion(), platform: process.platform, arch: process.arch,
    configSchema: 1, backendProtocol: 1, bridgeProtocol: 1, cacheDir: path.join(app.getPath('userData'), 'updates'),
    feedUrl: process.platform === 'win32' ? updateTrust.feedUrl : undefined, publicKey: process.platform === 'win32' ? updateTrust.productionTrust?.publicKey : undefined, installedUpdater: installedUpdates, onStatus: state => emit({ type: 'update-status', state: { ...state, installation: installedUpdates.status, recovery: updateRecovery.status } }) }); // Signed downloads need a reviewed feed/key; public GitHub checks remain read-only.
  // Start updates only after initial backend and renderer health is established.
  bootstrapStatus = { backend: await backendSupervisor.start(), game: await detectGame(), readerPlatformSupported: process.platform === 'darwin', bridgeConfigured: external || settings.backendEnvFile || !backendSupervisor.status.owned ? null : Boolean(settings.bridgePrivateRoot) };
  if (app.isPackaged && bootstrapStatus.backend.state !== 'ready') dialog.showErrorBox('FootballAssistant 后端未连接', bootstrapStatus.backend.message);

  bridgeDeployment = createBridgeDeployment({
    setup: createBridgeSetup({ userData: app.getPath('userData'), resourcesPath: process.resourcesPath, isPackaged: app.isPackaged,
      requestHealth: () => request(runtimeFile, '/v1/status'),
      onConfigured: async privateRoot => {
        backendOptions.settings = await loadSettings(app.getPath('userData'));
        bootstrapStatus.bridgeConfigured = Boolean(privateRoot);
        bootstrapStatus.bridgeRestartRequired = true;
        if (backendSupervisor.status.owned) {
          try {
            await backendSupervisor.stop();
            backendSupervisor = new BackendSupervisor({ ...backendOptions, backendEnv: credentials.getPublicConfig().configured ? await credentials.backendEnv() : {} });
            bootstrapStatus.backend = await backendSupervisor.start();
            bootstrapStatus.bridgeRestartRequired = bootstrapStatus.backend.state !== 'ready';
          } catch { bootstrapStatus.bridgeRestartRequired = true; }
        }
        return { restartRequired: bootstrapStatus.bridgeRestartRequired };
      } }),
    chooseGame: async () => {
      const result = await dialog.showOpenDialog(settingsWindow || win, { properties: ['openFile'], filters: [{ name: 'Game App', extensions: ['app'] }] });
      return result.canceled ? null : result.filePaths[0];
    }, canMutate: () => !quitting && !updateQuiescing && !savingModel
  });

  personaAccess = createPersonaAccess({ userData: app.getPath('userData'),
    isManaged: () => app.isPackaged && !backendSupervisor.external && backendSupervisor.status.owned === true && backendSupervisor.status.state === 'ready',
    getMetadata: () => request(runtimeFile, '/v1/agent/persona'), openPath: target => shell.openPath(target) });
  runtime = new CompanionRuntime({ realClient: new RealReaderClient({ request: (endpoint, body, options) => request(runtimeFile, endpoint, body, options) }), file: path.join(app.getPath('userData'), 'companion-ui.json') });
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
  const rendererHealthy = await win.webContents.executeJavaScript("document.readyState === 'complete' && Boolean(window.companion) && Boolean(document.getElementById('pet'))").catch(() => false);
  if (bootstrapStatus.backend.state === 'ready' && rendererHealthy && !runtime.storageWarning) await updateRecovery.acknowledgeHealthy();
  else if (updateRecovery.status.state === 'awaiting_health') await updateRecovery.fail('Updated app backend or local state failed initial health check');
  updateLifecycle = createUpdateLifecycle({ installedUpdater: installedUpdates, inspectActivity: inspectUpdateActivity });
  if (app.isPackaged && updateRecovery.status.state !== 'recovery_required') { updateController.start(); updateLifecycle.start(); }
}
if (primaryInstance) app.whenReady().then(main).catch(async () => { await updateRecovery?.fail('Application failed to start after update'); dialog.showErrorBox('FootballAssistant 无法启动', '本机配置或启动失败；请检查用户数据目录中的 settings.json。不会覆盖现有配置。'); await backendSupervisor?.stop(); app.exit(1); });
app.on('before-quit-for-update', () => { /* Native updater still uses our before-quit cleanup. */ });
app.on('window-all-closed', () => { /* The tray owns application lifetime. */ });
app.on('before-quit', event => {
  if (quitting) return;
  event.preventDefault(); quitting = true;
  clearInterval(pointerTimer); updateController?.stop(); updateLifecycle?.stop(); installedUpdates?.stop(); speech.dispose(); tray?.destroy();
  Promise.resolve(runtime?.close()).finally(async () => { await backendSupervisor?.stop(); app.quit(); });
});
