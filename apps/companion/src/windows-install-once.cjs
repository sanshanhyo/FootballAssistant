'use strict';
// Installer-only orchestration. No network, game launch, backend, discovery, or user-data override.
const fs = require('node:fs/promises');
const path = require('node:path');
const { DEFAULT_SETTINGS, validateSettings, detectGame } = require('./bootstrap.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const { inspectGame, validateReaderPayload } = require('./windows-reader-setup.cjs');
const { createWindowsMatchInstaller, validateWindowsMatchPayload } = require('./windows-match-installer.cjs');
const fail = (code, message) => { throw Object.assign(Error(message), { installCode: code }); };
async function defaultProbe() {
  const game = await detectGame('win32');
  return game.state === 'not_detected' ? false : game.state === 'running' ? true : null;
}
async function installWindowsReaders({ userData, resourcesPath, gamePath = '', silent = false,
  confirmException = async () => false, probeGame = defaultProbe, platform = process.platform,
  finalize = async () => {} }) {
  let deployed = null, savedRevision, before, settingsFile, installer;
  let phase = 'validation';
  const result = (code, message) => ({ code, message, gamePath, userData });
  try {
    if (platform !== 'win32') fail(4, 'Windows reader installation requires Windows.');
    if (!path.isAbsolute(userData) || !path.isAbsolute(resourcesPath)) fail(4, 'Invalid application paths.');
    await fs.mkdir(userData, { recursive: true, mode: 0o700 });
    userData = await fs.realpath(userData);
    settingsFile = path.join(userData, 'settings.json');
    before = await readStateFile(settingsFile, 16384);
    if (before.bytes && (await fs.lstat(settingsFile)).nlink !== 1) fail(4, 'Linked settings are not supported.');
    const settings = before.bytes ? validateSettings(JSON.parse(before.bytes.toString('utf8'))) : { ...DEFAULT_SETTINGS };
    gamePath = gamePath || settings.windowsMatchGamePath || settings.windowsReaderGamePath || '';
    if (!gamePath) fail(3, 'Select the FM installation directory in the installer.');
    if (!path.isAbsolute(gamePath) || /[\0\r\n]/.test(gamePath)) fail(4, 'FM path must be absolute.');
    if ((await fs.lstat(gamePath)).isDirectory()) gamePath = path.join(gamePath, 'fm.exe');
    gamePath = (await inspectGame(gamePath)).gamePath;
    await validateReaderPayload(resourcesPath); // Hash all bundled producer files; never run the producer here.
    const payload = validateWindowsMatchPayload(path.join(resourcesPath, 'match-windows-x64'));
    const policy = payload.manifest.runtimePolicy;
    if (!policy || policy.interopMode !== 'local-metadata-no-unstrip' || policy.unityBaseLibrariesSource !== '' ||
        policy.unityLogListening !== false || policy.updateInteropAssemblies !== true || policy.runtimeDependencyDownloads !== false)
      fail(4, 'This bundle does not provide the required no-download runtime policy.');
    installer = createWindowsMatchInstaller({ userData, resourcesPath, platform, probeGame });
    // Exceptions require explicit native confirmation, never implicit migration or process termination.
    for (;;) {
      const value = await probeGame(path.dirname(gamePath));
      const running = typeof value === 'boolean' ? value : value?.running;
      if (running === false) break;
      if (running !== true) fail(5, 'Cannot verify that FM is closed. No game files were changed.');
      if (silent) fail(3, 'Close FM before silent installation.');
      if (!await confirmException({ type: 'game_running', gamePath })) fail(2, 'Installation cancelled; FM must be closed.');
    }
    phase = 'deployment';
    const plan = await installer.plan(gamePath);
    if (!plan.canDeploy) fail(5, 'Incompatible loader or modified files require manual review; no files were replaced.');
    let migrateLoader = false;
    if (plan.needsMigrationConsent) {
      if (silent) fail(3, 'Existing loader migration requires interactive confirmation.');
      migrateLoader = await confirmException({ type: 'loader_migration', gamePath, files: plan.migrationFiles });
      if (!migrateLoader) fail(2, 'Loader migration cancelled.');
    }
    let confirmSharedConfig = false;
    if (plan.needsSharedConfigConsent) {
      if (silent) fail(3, 'Existing BepInEx configuration changes require interactive confirmation.');
      confirmSharedConfig = await confirmException({ type: 'shared_config', gamePath, fields: plan.sharedConfigChanges });
      if (!confirmSharedConfig) fail(2, 'Shared loader configuration change cancelled.');
    }
    deployed = await installer.deploy({ planId: plan.planId, confirmationToken: plan.confirmationToken, confirm: true, migrateLoader, confirmSharedConfig });
    phase = 'settings';
    const next = validateSettings({ ...settings, windowsReaderEnabled: true, windowsReaderGamePath: gamePath,
      windowsMatchEnabled: true, windowsMatchGamePath: gamePath });
    savedRevision = await writeStateFile(settingsFile, JSON.stringify(next, null, 2) + '\n', before.revision);
    const success = result(0, 'Readers installed and configured. Start FM normally; first-run local interop generation may take time.');
    await finalize(success);
    return success;
  } catch (error) {
    let recovery = error.recoveryState === 'recovery_required';
    // Only undo the deployment created by this invocation; prior receipt is restored by installer rollback.
    if (deployed) {
      try {
        const current = await installer.inspect(gamePath);
        if (current.deploymentId !== deployed.deploymentId) throw Error('Deployment changed outside this invocation.');
        await installer.rollback({ confirm: true });
      } catch { recovery = true; }
    }
    if (savedRevision !== undefined) {
      try {
        if (before.bytes) await writeStateFile(settingsFile, before.bytes, savedRevision);
        else {
          if ((await readStateFile(settingsFile)).revision !== savedRevision) throw Error('Settings changed.');
          await fs.unlink(settingsFile);
        }
      } catch { recovery = true; }
    }
    return result(recovery ? 6 : error.installCode || (phase === 'validation' ? 4 : phase === 'settings' ? 7 : 5),
      recovery ? 'Installation incomplete; recovery is required. No running game was terminated. ' + error.message : error.message);
  }
}
module.exports = { installWindowsReaders };
