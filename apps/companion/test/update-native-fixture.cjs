'use strict';
// Real two-version NSIS upgrade, deliberately isolated from the production app.
// No production release, certificate, OS trust-store change, or native updater mock.
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');

function requireDisposableWindows() {
  if (process.platform !== 'win32' || process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_OS !== 'Windows' || !process.env.RUNNER_TEMP) throw new Error('Native updater fixture is restricted to disposable GitHub Actions Windows runners');
}
function command(executable, args, { cwd, timeout = 180000, env = process.env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd, env, stdio: 'inherit', windowsHide: true });
    const timer = setTimeout(() => { child.kill(); reject(new Error(`Fixture command timed out: ${path.basename(executable)}`)); }, timeout);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error(`Fixture command failed: ${path.basename(executable)} (${code})`)); });
  });
}
const appSource = String.raw`
'use strict';
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { NsisUpdater } = require('electron-updater');
const { createInstalledUpdater } = require('./update-installed.cjs');
const { createUpdateRecovery } = require('./update-recovery.cjs');
const config = require('./fixture-config.json');
app.setPath('userData', config.profile);
const evidence = event => fs.appendFileSync(path.join(config.profile, 'evidence.jsonl'), JSON.stringify({ ...event, appVersion: app.getVersion(), time: new Date().toISOString() }) + '\n');
app.whenReady().then(async () => {
  const version = app.getVersion();
  const recovery = createUpdateRecovery({ userData: config.profile, currentVersion: version });
  const launch = await recovery.beginLaunch();
  evidence({ step: 'launch', recovery: launch.state, argvUpdated: process.argv.includes('--updated') });
  const window = new BrowserWindow({ show: false, webPreferences: { sandbox: true, nodeIntegration: false, contextIsolation: true } });
  await window.loadURL('data:text/html,<html><body>Native update fixture</body></html>');
  assert.equal(await window.webContents.executeJavaScript('document.body.textContent'), 'Native update fixture');
  if (version === config.targetVersion) {
    assert.equal(launch.state, 'awaiting_health');
    assert.equal(fs.readFileSync(path.join(config.profile, 'settings.json'), 'utf8'), config.originalSettings);
    assert.equal((await recovery.acknowledgeHealthy()).state, 'healthy');
    evidence({ step: 'target_healthy', settingsPreserved: true, recovery: 'healthy' });
    fs.writeFileSync(path.join(config.profile, 'complete.json'), JSON.stringify({ version, healthy: true, settingsPreserved: true }));
    app.quit(); return;
  }
  assert.equal(version, config.initialVersion);
  const envelopeResponse = await fetch(config.serverUrl + '/manifest.json');
  assert.equal(envelopeResponse.status, 200);
  const envelope = await envelopeResponse.json();
  const updater = createInstalledUpdater({
    platform: 'win32', distribution: 'nsis', arch: process.arch, currentVersion: version,
    configSchema: 1, backendProtocol: 1, bridgeProtocol: 1,
    productionTrust: { publicKey: config.publicKey, trustPolicy: 'ed25519-pinned' },
    nativeFactory: () => {
      const native = new NsisUpdater({ provider: 'generic', url: config.serverUrl + '/' });
      native.disableDifferentialDownload = true;
      native.installDirectory = config.install;
      return native;
    },
    isSafeToInstall: () => true,
    beforeInstall: async ({ targetVersion }) => {
      const state = await recovery.prepare({ targetVersion });
      assert.equal(state.state, 'prepared');
      evidence({ step: 'prepared', targetVersion, backupRetained: Boolean(state.backupPath) });
    },
    onStatus: status => evidence({ step: 'update_status', state: status.state })
  });
  const staged = await updater.stage(envelope);
  assert.equal(staged.state, 'ready_for_safe_exit', staged.reason);
  evidence({ step: 'staged', targetVersion: config.targetVersion });
  const installed = await updater.applyOnSafeExit({ normalQuit: true, sessionEnding: false, restart: true });
  assert.equal(installed.state, 'installing', installed.reason);
}).catch(error => {
  try { evidence({ step: 'error', message: error.message }); } catch {}
  try { fs.writeFileSync(path.join(config.profile, 'failed.json'), JSON.stringify({ message: error.message, stack: error.stack })); } catch {}
  app.exit(1);
});
app.on('window-all-closed', () => {});
`;

function verifyFixtureEvidenceEncoding() {
  const vm = require('node:vm');
  const writes = [];
  const evidenceDeclaration = appSource.split('\n').find(line => line.startsWith('const evidence ='));
  assert.ok(evidenceDeclaration, 'Missing embedded evidence writer');
  // Exercise the actual embedded declaration, including a message containing a
  // newline: JSON escaping must not be confused with the record delimiter.
  vm.runInNewContext(evidenceDeclaration + "\nevidence({ message: 'first\\nsecond' }); evidence({ message: 'next' });", {
    fs: { appendFileSync: (_file, value) => writes.push(value) }, path,
    config: { profile: 'fixture-profile' }, app: { getVersion: () => '0.0.1-alpha.1' }
  });
  const output = writes.join('');
  assert.equal(output.split('\n').length, 3, 'Expected two actual newline-terminated JSON records');
  const records = output.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(records[0].message, 'first\nsecond');
  assert.equal(records[1].message, 'next');
  return true;
}

async function main() {
  requireDisposableWindows();
  verifyFixtureEvidenceEncoding();
  const companion = path.resolve(__dirname, '..');
  const root = await fs.mkdtemp(path.join(process.env.RUNNER_TEMP, 'fa-native-update-'));
  const project = path.join(root, 'fixture-app');
  const install = path.join(root, 'installed');
  const profile = path.join(root, 'profile');
  const initialVersion = '0.0.1-alpha.1', targetVersion = '0.0.2-alpha.1';
  const originalSettings = JSON.stringify({ version: 1, backend: { port: 17827 }, bridgePrivateRoot: '', backendEnvFile: '' }, null, 2);
  const reportPath = path.join(process.env.RUNNER_TEMP, 'companion-smoke-update-fixture.json');
  await fs.rm(reportPath, { force: true });
  await fs.mkdir(project); await fs.mkdir(profile);
  await fs.writeFile(path.join(profile, 'settings.json'), originalSettings);
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519'); // ephemeral fixture only; never persisted
  const requests = [];
  let manifest = null, targetDirectory = null;
  const server = http.createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
      requests.push({ path: pathname, method: request.method });
      if (pathname === '/manifest.json' && manifest) {
        response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(manifest)); return;
      }
      // A bounded local fixture server, not a configurable production feed.
      const name = decodeURIComponent(pathname.slice(1));
      if (!targetDirectory || path.basename(name) !== name || !/\.(?:yml|exe|blockmap)$/.test(name)) { response.writeHead(404); response.end(); return; }
      const file = path.join(targetDirectory, name);
      const info = await fs.stat(file);
      response.writeHead(200, { 'Content-Length': info.size, 'Content-Type': name.endsWith('.yml') ? 'text/yaml' : 'application/octet-stream' });
      if (request.method === 'HEAD') response.end(); else fsSync.createReadStream(file).pipe(response);
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const serverUrl = `http://127.0.0.1:${server.address().port}`;
  const config = { initialVersion, targetVersion, install, profile, originalSettings, serverUrl, publicKey: publicKey.export({ type: 'spki', format: 'pem' }) };
  let initialChild = null;
  try {
    for (const name of ['update-installed.cjs', 'update-security.cjs', 'update-recovery.cjs']) await fs.copyFile(path.join(companion, 'src', name), path.join(project, name));
    await fs.writeFile(path.join(project, 'main.cjs'), appSource);
    await fs.writeFile(path.join(project, 'fixture-config.json'), JSON.stringify(config));
    const packageFile = path.join(project, 'package.json');
    const packageJson = { name: 'football-assistant-native-update-fixture', version: initialVersion, private: true, description: 'Disposable CI-only update fixture', author: 'FootballAssistant CI', main: 'main.cjs', dependencies: { 'electron-updater': '6.6.2' } };
    await fs.writeFile(packageFile, JSON.stringify(packageJson));
    // Use the normal public registry dependency installer; no app/private credentials.
    const npmCli = path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js');
    await fs.access(npmCli).catch(() => { throw new Error('setup-node Windows npm-cli.js not found beside node.exe; fixture install was not attempted'); });
    await command(process.execPath, [npmCli, 'install', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org'], { cwd: project, timeout: 180000 });
    const { build, Platform, Arch } = require('electron-builder');
    const electronVersion = require(path.join(companion, 'node_modules', 'electron', 'package.json')).version;
    const common = {
      appId: 'local.footballassistant.ci-native-update', productName: 'FA Native Update Fixture',
      // The npm Electron package need not have an extracted dist directory.
      // Let builder reuse its normal verified Electron download/cache (as the real app does).
      electronVersion,
      asar: true, npmRebuild: false,
      files: ['*.cjs', 'fixture-config.json', 'package.json', 'node_modules/**/*'],
      win: { target: ['nsis'], signExecutable: false },
      nsis: { oneClick: false, perMachine: false, allowElevation: false, allowToChangeInstallationDirectory: true, runAfterFinish: false, deleteAppDataOnUninstall: false, artifactName: 'Fixture-${version}-Setup.exe' },
      publish: { provider: 'generic', url: serverUrl + '/', channel: 'alpha' }
    };
    const outputs = {};
    for (const version of [initialVersion, targetVersion]) {
      await fs.writeFile(packageFile, JSON.stringify({ ...packageJson, version }));
      const output = path.join(root, `build-${version}`);
      await build({ projectDir: project, targets: Platform.WINDOWS.createTarget(['nsis'], Arch.x64), publish: 'never', config: { ...structuredClone(common), directories: { output } } });
      outputs[version] = output;
    }
    targetDirectory = outputs[targetVersion];
    await fs.access(path.join(targetDirectory, 'alpha.yml')).catch(() => { throw new Error('Builder did not generate the required generic Alpha update metadata'); });
    const targetName = `Fixture-${targetVersion}-Setup.exe`;
    const targetBytes = await fs.readFile(path.join(targetDirectory, targetName));
    const payload = JSON.stringify({ schema: 1, channel: 'alpha', version: targetVersion, expiresAt: new Date(Date.now() + 3600000).toISOString(), configSchemas: [1], backendProtocol: 1, bridgeProtocol: 1, artifacts: [{ platform: 'win32', arch: 'x64', format: 'exe', installerType: 'nsis', size: targetBytes.length, sha256: crypto.createHash('sha256').update(targetBytes).digest('hex'), url: `https://github.com/sanshanhyo/FootballAssistant/releases/download/${targetVersion}/${targetName}` }] });
    manifest = { payload, signature: crypto.sign(null, Buffer.from(payload), privateKey).toString('base64') };
    await command(path.join(outputs[initialVersion], `Fixture-${initialVersion}-Setup.exe`), ['/S', `/D=${install}`]);
    const executable = path.join(install, 'FA Native Update Fixture.exe');
    await fs.access(executable);
    initialChild = spawn(executable, [], { stdio: 'inherit', windowsHide: true });
    initialChild.once('error', error => fs.writeFile(path.join(profile, 'failed.json'), JSON.stringify({ message: error.message })).catch(() => {}));
    const deadline = Date.now() + 240000;
    let complete = null;
    while (Date.now() < deadline) {
      try { const failure = JSON.parse(await fs.readFile(path.join(profile, 'failed.json'), 'utf8')); throw new Error(`Fixture app failed: ${failure.message}`); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      try { complete = JSON.parse(await fs.readFile(path.join(profile, 'complete.json'), 'utf8')); break; } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    assert.ok(complete, 'Native upgrade/relaunch did not complete before deadline');
    assert.equal(complete.version, targetVersion); assert.equal(complete.healthy, true); assert.equal(complete.settingsPreserved, true);
    const events = (await fs.readFile(path.join(profile, 'evidence.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    assert.ok(events.some(event => event.step === 'launch' && event.appVersion === initialVersion));
    assert.ok(events.some(event => event.step === 'launch' && event.appVersion === targetVersion && event.argvUpdated));
    assert.ok(requests.some(request => request.path.endsWith('.exe') && request.method === 'GET'), 'No actual updater installer download observed');
    const result = { passed: true, initialVersion, targetVersion, actualNativeInstaller: true, actualDownload: true, actualRelaunch: true, settingsPreserved: true, healthAcknowledged: true, trustPolicy: 'ephemeral-ed25519-fixture-only', publicKeyFingerprint: crypto.createHash('sha256').update(config.publicKey).digest('hex'), authenticodeValidated: false, productionReadiness: false, events, requests };
    await fs.writeFile(reportPath, JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ passed: true, reportPath, initialVersion, targetVersion }));
    // Give the healthy target its own normal quit window before uninstall cleanup.
    await new Promise(resolve => setTimeout(resolve, 1500));
  } catch (error) {
    let events = ''; try { events = await fs.readFile(path.join(profile, 'evidence.jsonl'), 'utf8'); } catch {}
    await fs.writeFile(reportPath, JSON.stringify({ passed: false, error: error.message, events, requests, root }, null, 2));
    throw error;
  } finally {
    initialChild?.kill();
    const uninstaller = path.join(install, 'Uninstall FA Native Update Fixture.exe');
    try { await fs.access(uninstaller); await command(uninstaller, ['/S', `_?=${install}`]); } catch (error) { if (error.code !== 'ENOENT') console.error(`Fixture cleanup: ${error.message}`); }
    await new Promise(resolve => server.close(resolve));
  }
}
if (require.main === module) main().catch(error => { console.error(error.stack); process.exit(1); });
module.exports = { requireDisposableWindows, fixtureAppSource: appSource, verifyFixtureEvidenceEncoding };
