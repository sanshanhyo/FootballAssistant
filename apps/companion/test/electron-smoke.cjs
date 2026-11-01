'use strict';
// Manual offline smoke, excluded from *.test.cjs. No real microphone or service.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

async function main() {
  let playwright;
  try { playwright = require(process.env.FA_PLAYWRIGHT_MODULE_PATH || 'playwright'); }
  catch { throw new Error('Optional smoke requires an existing Playwright installation or FA_PLAYWRIGHT_MODULE_PATH.'); }
  const executablePath = process.env.FA_ELECTRON_EXECUTABLE || require('electron');
  const appRoot = path.resolve(__dirname, '..');
  const output = await fs.mkdtemp(path.join(os.tmpdir(), 'football-companion-smoke-'));
  const launcher = path.join(output, 'offline-launcher.cjs');
  await fs.writeFile(launcher, `
'use strict';
const { app, systemPreferences } = require('electron');
global.__offlineSmoke = { networkAttempts: 0, processAttempts: 0 };
systemPreferences.getMediaAccessStatus = () => 'granted';
systemPreferences.askForMediaAccess = async () => true;
globalThis.fetch = async () => { global.__offlineSmoke.networkAttempts++; throw new Error('Offline smoke blocks network.'); };
require('node:child_process').spawn = () => { global.__offlineSmoke.processAttempts++; throw new Error('Offline smoke blocks external speech processes.'); };
app.on('session-created', session => session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'ws://*/*', 'wss://*/*'] }, (_details, callback) => { global.__offlineSmoke.networkAttempts++; callback({ cancel: true }); }));
require(${JSON.stringify(path.join(appRoot, 'src', 'main.cjs'))});
`);
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (/^(FA_|FOOTBALL_ASSISTANT_)/u.test(key) || /(?:OPENAI|AZURE|ANTHROPIC|SPEECH|TTS).*(?:KEY|TOKEN)/u.test(key) || key === 'ELECTRON_RUN_AS_NODE') delete env[key];
  }
  env.FA_COMPANION_USER_DATA_DIR = path.join(output, 'user-data');
  const report = { platform: process.platform, arch: process.arch, fixture: 'Offline, Chromium fake media, simulated providers, isolated user data; no OS microphone or real speech service.', checks: [], errors: [], screenshots: [] };
  let application;
  const check = async (name, action) => { await action(); report.checks.push(name); };
  try {
    application = await playwright._electron.launch({ executablePath, args: [launcher, '--disable-background-networking', '--use-fake-device-for-media-stream'], cwd: appRoot, env });
    const page = await application.firstWindow(); page.setDefaultTimeout(5_000);
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
    await page.waitForFunction(() => window.companion && document.querySelector('#character-image')?.naturalWidth > 0);
    await check('normal app starts real before the offline fixture explicitly selects mock', async () => {
      const initial = await page.evaluate(async () => (await window.companion.getState()).value);
      assert.equal(initial.mode, 'real'); assert.equal(initial.synthetic, false);
    });
    await check('explicit mock fixture state, speech-only bubble and isolated renderer', async () => {
      const selected = await page.evaluate(async () => await window.companion.setMode('mock'));
      assert.equal(selected.ok, true);
      assert.match(await page.title(), /FootballAssistant/u);
      assert.equal(await page.evaluate(() => typeof require), 'undefined');
      assert.equal(await page.locator('#chat-form').isVisible(), false);
      assert.equal(await page.locator('#compact-bubble').isVisible(), false);
      assert.equal(await page.locator('#compact-bubble button, #compact-bubble details, #message-badges, #message-origin').count(), 0);
      assert.equal(await page.locator('#mode, #stt-provider, #expression, #memory-text').count(), 0);
      const state = await page.evaluate(async () => (await window.companion.getState()).value);
      assert.equal(state.mode, 'mock'); assert.equal(state.proactivity, 80); assert.equal(state.historyEnabled, false);
      assert.equal(state.pendingRequests.length, 0); assert.equal(state.messages.length, 0);
    });
    await page.screenshot({ path: path.join(output, 'compact.png') }); report.screenshots.push('compact.png');
    let settings;
    await check('single click shows speech; six-page settings retain history/source data without diagnostic panels', async () => {
      await page.locator('#pet').click(); await page.locator('#message').fill('解释当前观测'); await page.locator('#send').click();
      await page.waitForFunction(() => document.querySelector('#compact-text').textContent.includes('模拟回复'));
      assert.ok(await page.evaluate(() => Array.from(new Intl.Segmenter('zh', { granularity: 'grapheme' }).segment(document.querySelector('#compact-text').textContent)).length <= 40));
      assert.equal(await page.locator('#bubble-progress').isVisible(), true);
      const firstPart = await page.locator('#compact-text').innerText();
      await page.locator('#compact-text').click();
      assert.notEqual(await page.locator('#compact-text').innerText(), firstPart);
      const completeReply = await page.evaluate(async () => (await window.companion.getState()).value.messages.find(message => message.role === 'assistant').text);
      assert.ok(completeReply.length > firstPart.length);
      const settingsCreated = application.waitForEvent('window');
      await page.evaluate(() => window.companion.openSettings());
      settings = await settingsCreated; settings.setDefaultTimeout(5_000);
      settings.on('pageerror', error => report.errors.push(error.message));
      settings.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
      await settings.waitForFunction(() => window.companion && document.querySelector('#model-provider'));
      assert.deepEqual(await settings.locator('[data-page]').allTextContents(), ['连接', '输入', '人设', '历史与记忆', '外观', '关于']);
      assert.equal(await settings.locator('#mode, #tasks, #observations, #discovery-capture, #bridge-setup-card, .brand, .sidebar-footer, .eyebrow, .muted, small').count(), 0);
      assert.equal(await settings.locator('#model-name').evaluate(element => element.tagName), 'SELECT');
      assert.equal(await settings.locator('#custom-url-row').isVisible(), false);
      const runtime = await settings.evaluate(async () => (await window.companion.getState()).value);
      assert.ok(runtime.tools.some(item => item.tool.status === 'completed'));
      const assistant = runtime.messages.find(message => message.role === 'assistant');
      assert.ok(assistant.cards.length > 0);
      assert.equal(assistant.metadata.synthetic, true);
      assert.equal(typeof assistant.metadata.partial, 'boolean');
      assert.ok(assistant.metadata.sessionId);
      assert.ok(assistant.metadata.sampledAt);
      await settings.locator('[data-page="records"]').click();
      await settings.locator('#history-list .info-card').first().waitFor({ state: 'attached' });
      await settings.locator('#history-list details').evaluateAll(elements => elements.forEach(element => { element.open = true; }));
      assert.match(await settings.locator('#history-list .info-card').first().innerText(), /未知/u);
      await settings.locator('#history-list .metadata').first().evaluate(element => { element.open = true; });
      const metadata = await settings.locator('#history-list .metadata').first().innerText();
      for (const label of ['会话', '采样', '来源']) assert.ok(metadata.includes(label));
      assert.match(await settings.locator('#history-list').innerText(), /模拟/u);
    });
    await page.screenshot({ path: path.join(output, 'reply.png') }); report.screenshots.push('reply.png');
    await check('backend switch cancels old requests without real-mode fallback', async () => {
      await page.locator('#message').fill('切换前请求'); await page.locator('#send').click();
      const real = await settings.evaluate(async () => await window.companion.setMode('real'));
      assert.equal(real.ok, true);
      await page.waitForFunction(async () => (await window.companion.getState()).value.mode === 'real');
      assert.equal(await page.locator('#compact-bubble').isVisible(), false);
      await settings.locator('[data-page="connection"]').click();
      assert.match(await settings.locator('#connection-status').innerText(), /后台未连接/u);
      const disconnected = await settings.evaluate(async () => (await window.companion.getState()).value);
      assert.equal(disconnected.synthetic, false);
      assert.equal(disconnected.pendingRequests.length, 0);
      assert.equal(disconnected.mode, 'real');
      assert.equal(await page.locator('#send').isDisabled(), disconnected.canSend !== true);
      const result = await page.evaluate(async () => await window.companion.sendMessage({ text: '禁止发送' }));
      assert.equal(result.ok, false); assert.match(result.error, /连接|runtime|后端|服务/u);
      assert.equal((await settings.evaluate(async () => await window.companion.setMode('mock'))).ok, true);
    });
    await check('explicit memories survive chat clearing and can be deleted', async () => {
      await settings.locator('nav [data-page="records"]').click();
      await settings.locator('#memory-text').fill('离线验收显式记忆'); await settings.locator('#save-memory').click();
      await settings.locator('#memory-list .memory-entry').waitFor();
      settings.once('dialog', dialog => dialog.accept());
      await settings.locator('#clear-history').click();
      await settings.waitForFunction(() => document.querySelector('#history-count').textContent.includes('暂无'));
      assert.match(await settings.locator('#memory-list').innerText(), /离线验收显式记忆/u);
      await settings.locator('#memory-list button').click();
      await settings.waitForFunction(() => document.querySelector('#memory-list').textContent.includes('暂无记忆'));
    });
    await check('persona, appearance and about pages expose working controls without helper prose', async () => {
      await settings.locator('[data-page="companion"]').click();
      await settings.waitForFunction(() => document.querySelector('#character-image').naturalWidth > 0);
      assert.ok((await settings.locator('#character-introduction').innerText()).trim());
      assert.equal(await settings.locator('#persona-content').count(), 1);
      assert.equal(await settings.locator('#persona-save').count(), 1);
      assert.equal(await settings.locator('#persona-refresh').count(), 1);
      await settings.locator('#proactivity').focus();
      await settings.locator('#proactivity').press('End');
      await settings.waitForFunction(async () => (await window.companion.getState()).value.proactivity === 100);
      assert.equal(await settings.locator('#proactivity-value').innerText(), '100%');
      await settings.locator('[data-page="appearance"]').click();
      await settings.locator('#font-family').selectOption('serif');
      await settings.locator('#font-size').selectOption('16');
      await settings.locator('#dark-mode').uncheck();
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'light' && document.documentElement.style.getPropertyValue('--font-scale') === String(16/14));
      assert.match(await page.locator('#message').evaluate(el => getComputedStyle(el).fontFamily), /Songti|Noto Serif|Georgia/);
      await page.reload();
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'light' && document.documentElement.style.getPropertyValue('--font-scale') === String(16/14));
      assert.equal(await settings.locator('html').getAttribute('data-theme'), 'light');
      await settings.reload();
      await settings.waitForFunction(() => window.companion);
      await settings.locator('[data-page="appearance"]').click();
      assert.equal(await settings.locator('#font-family').inputValue(), 'serif');
      assert.equal(await settings.locator('#font-size').inputValue(), '16');
      assert.equal(await settings.locator('#dark-mode').isChecked(), false);
      await settings.locator('#font-family').selectOption('system');
      await settings.locator('#font-size').selectOption('14');
      await settings.locator('#dark-mode').check();
      await settings.locator('[data-page="about"]').click();
      await settings.waitForFunction(() => document.querySelector('.app-icon').naturalWidth > 0);
      assert.equal(await settings.locator('.about-content h2').innerText(), 'Football Assistant');
      assert.ok((await settings.locator('#app-version').innerText()).trim());
      assert.equal(await settings.locator('#update-check, #open-repository, #open-contributors').count(), 3);
      assert.equal(await settings.locator('.about-nav').getAttribute('data-page'), 'about');
      for (const name of ['connection', 'voice', 'companion', 'records', 'appearance', 'about']) {
        await settings.locator(`[data-page="${name}"]`).click();
        assert.equal(await settings.locator(`#page-${name}`).isVisible(), true);
        assert.equal(await settings.locator('.settings-page:visible').count(), 1);
        const screenshot = `settings-${name}.png`;
        await settings.screenshot({ path: path.join(output, screenshot), fullPage: true });
        report.screenshots.push(screenshot);
      }
    });
    await check('fake-media press creates editable mock draft without sending', async () => {
      await settings.locator('nav [data-page="voice"]').click();
      assert.equal(await settings.locator('#stt-provider option[value="mock"]').count(), 0);
      assert.equal(await settings.locator('#stt-provider option[value="local-whisper"]').count(), 1);
      // Fixture-only IPC retains mock speech coverage without exposing a user mock control.
      const mockSpeech = await settings.evaluate(async () => await window.companion.setPreferences({ sttProvider: 'mock' }));
      assert.equal(mockSpeech.ok, true);
      // Wait for the pet to apply the shared state, not just the main-process preference write.
      await page.waitForFunction(() => document.querySelector('#voice-status').textContent.includes('语音服务已切换'));
      await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(window => window.webContents.getURL().endsWith('/index.html')).focus());
      await page.waitForFunction(() => document.hasFocus());
      const before = await page.evaluate(async () => (await window.companion.getHistory()).value.messages.length);
      const box = await page.locator('#pet').boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
      await page.waitForFunction(() => document.querySelector('#voice-status').textContent.includes('正在录音'));
      await page.waitForTimeout(350); await page.mouse.up();
      await page.waitForFunction(() => document.querySelector('#draft-note').textContent.includes('模拟转写'));
      assert.match(await page.locator('#message').inputValue(), /模拟/u);
      assert.equal(await page.evaluate(async () => (await window.companion.getHistory()).value.messages.length), before);
    });
    await page.screenshot({ path: path.join(output, 'voice-draft.png') }); report.screenshots.push('voice-draft.png');
    await check('no network, external speech processes, or renderer errors', async () => {
      assert.deepEqual(await application.evaluate(() => global.__offlineSmoke), { networkAttempts: 0, processAttempts: 0 });
      assert.deepEqual(report.errors, []);
    });
  } catch (error) {
    report.failure = error.stack; process.exitCode = 1;
    if (application) {
      const pet = application.windows().find(window => window.url().endsWith('/index.html'));
      if (pet) report.failureState = await pet.evaluate(async () => ({ voice: document.querySelector('#voice-status')?.textContent, error: document.querySelector('#error')?.textContent, focused: document.hasFocus(), pet: document.querySelector('#pet')?.getBoundingClientRect().toJSON(), preferences: (await window.companion.getState()).value.preferences })).catch(() => null);
    }
  }
  finally {
    if (application) await application.close().catch(() => {});
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ...report, output }, null, 2));
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
