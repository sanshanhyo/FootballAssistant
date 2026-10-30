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
    application = await playwright._electron.launch({ executablePath, args: [launcher, '--disable-background-networking', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'], cwd: appRoot, env });
    const page = await application.firstWindow(); page.setDefaultTimeout(5_000);
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
    await page.waitForFunction(() => window.companion && document.querySelector('#compact-mode').textContent.includes('模拟'));
    await check('explicit mock startup and isolated renderer', async () => {
      assert.match(await page.title(), /FootballAssistant/u);
      assert.equal(await page.evaluate(() => typeof require), 'undefined');
      assert.equal(await page.locator('#panel').isVisible(), false);
      const state = await page.evaluate(async () => (await window.companion.getState()).value);
      assert.equal(state.mode, 'mock'); assert.equal(state.proactivity, 80); assert.equal(state.historyEnabled, false);
      assert.equal(state.pendingRequests.length, 0); assert.equal(state.messages.length, 0);
    });
    await page.screenshot({ path: path.join(output, 'compact.png') }); report.screenshots.push('compact.png');
    await check('single click, mock reply, tool result and unknown information card', async () => {
      await page.locator('#pet').click(); await page.locator('#message').fill('解释当前观测'); await page.locator('#send').click();
      await page.locator('.message.assistant .info-card').waitFor();
      assert.match(await page.locator('#messages').innerText(), /模拟回复/u);
      assert.match(await page.locator('.info-card').innerText(), /未知/u);
      assert.match(await page.locator('.task-state').innerText(), /完成/u);
      await page.locator('.message.assistant .observation').first().evaluate(element => { element.open = true; });
      const metadata = await page.locator('.message.assistant .observation').first().innerText();
      for (const label of ['会话', '采样', 'partial', 'synthetic']) assert.ok(metadata.includes(label));
    });
    await page.screenshot({ path: path.join(output, 'reply.png') }); report.screenshots.push('reply.png');
    await check('backend switch cancels old requests without real-mode fallback', async () => {
      await page.locator('#message').fill('切换前请求'); await page.locator('#send').click();
      await page.locator('#mode').selectOption('real'); await page.waitForTimeout(500);
      assert.equal(await page.locator('.message').count(), 0); assert.equal(await page.locator('#send').isDisabled(), true);
      const result = await page.evaluate(async () => await window.companion.sendMessage({ text: '禁止发送' }));
      assert.equal(result.ok, false); assert.match(result.error, /尚未接入/u);
      await page.locator('#mode').selectOption('mock');
    });
    await check('explicit memories survive chat clearing and can be deleted', async () => {
      await page.locator('#history-options').evaluate(element => { element.open = true; });
      await page.locator('#memory-text').fill('离线验收显式记忆'); await page.locator('#save-memory').click();
      await page.locator('#memory-list .saved-entry').waitFor(); await page.locator('#clear-history').click();
      assert.match(await page.locator('#memory-list').innerText(), /离线验收显式记忆/u);
      await page.locator('#memory-list button').click();
      await page.waitForFunction(() => document.querySelector('#memory-list').textContent.includes('尚未明确保存'));
    });
    await check('fake-media press creates editable mock draft without sending', async () => {
      await page.locator('#voice-options').evaluate(element => { element.open = true; });
      await page.locator('#stt-provider').selectOption('mock');
      const before = await page.evaluate(async () => (await window.companion.getHistory()).value.messages.length);
      const box = await page.locator('#record-button').boundingBox();
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
  } catch (error) { report.failure = error.stack; process.exitCode = 1; }
  finally {
    if (application) await application.close().catch(() => {});
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ...report, output }, null, 2));
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
