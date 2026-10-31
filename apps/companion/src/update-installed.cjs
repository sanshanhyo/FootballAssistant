'use strict';
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { verifyManifest, REPOSITORY } = require('./update-security.cjs');

async function verifyInstaller(file, artifact) {
  const stat = await fsp.lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== artifact.size) throw new Error('Installer size/type mismatch');
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  if (hash.digest('hex') !== artifact.sha256) throw new Error('Installer differs from signed manifest');
}
async function verifyWindowsSignature(file, allowedThumbprints) {
  // Encode the path as data; never interpolate shell syntax or launch a downloaded helper.
  const encodedPath = Buffer.from(file, 'utf8').toString('base64');
  const script = `$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedPath}')); $s=Get-AuthenticodeSignature -LiteralPath $p; @{status=$s.Status.ToString();thumbprint=$s.SignerCertificate.Thumbprint}|ConvertTo-Json -Compress`;
  const powershell = require('node:path').join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const { stdout } = await promisify(execFile)(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], { timeout: 30000, windowsHide: true, maxBuffer: 16384 });
  const result = JSON.parse(stdout.replace(/^\uFEFF/, '').trim());
  if (result.status !== 'Valid' || typeof result.thumbprint !== 'string' || !allowedThumbprints.includes(result.thumbprint.toUpperCase())) throw new Error('Installer Authenticode signature is not trusted');
}

// This gate is dormant in production until release trust is explicitly configured.
// All options are trusted main-process/build-time values, never renderer IPC input.
function createInstalledUpdater(options) {
  const { productionTrust, nativeFactory = () => {
    const { NsisUpdater } = require('electron-updater');
    const [owner, repo] = REPOSITORY.split('/');
    return new NsisUpdater({ provider: 'github', owner, repo });
  }, verifySignature = verifyWindowsSignature, isSafeToInstall = () => false, beforeInstall = async () => {}, onInstallFailure = async () => {}, onStatus = () => {} } = options;
  const thumbprints = productionTrust?.certificateThumbprints;
  const trustPolicy = productionTrust?.trustPolicy || 'authenticode-and-ed25519';
  const publisherTrust = trustPolicy === 'ed25519-pinned' || (trustPolicy === 'authenticode-and-ed25519' && Array.isArray(thumbprints) && thumbprints.length > 0 && thumbprints.every(x => typeof x === 'string' && /^[A-Fa-f0-9]{40}$/.test(x)));
  const enabled = options.platform === 'win32' && options.distribution === 'nsis' && typeof productionTrust?.publicKey === 'string' && publisherTrust;
  let native = null, ready = null, operation = null, disposed = false, preparationStarted = false;
  let status = { state: 'manual_required', automaticInstallEnabled: Boolean(enabled), distribution: options.distribution || 'unknown', trustPolicy, publisherVerificationRequired: trustPolicy === 'authenticode-and-ed25519', reason: enabled ? 'Trusted NSIS path configured; waiting for a signed compatible release' : 'Automatic installation requires an installed NSIS build, pinned release key and trusted Windows signing certificate; current updates remain manual' };
  function publish(patch) { status = { ...status, ...patch }; try { onStatus(structuredClone(status)); } catch {} return structuredClone(status); }
  async function failed(error) {
    ready = null; publish({ state: 'blocked', reason: error.message });
    if (preparationStarted) {
      preparationStarted = false;
      try { await onInstallFailure(error); } catch { publish({ state: 'blocked', reason: `${error.message}; application recovery requires attention` }); }
    }
    return structuredClone(status);
  }
  function run(task) {
    if (operation) return operation;
    operation = Promise.resolve().then(task).catch(failed).finally(() => { operation = null; });
    return operation;
  }
  function getNative() {
    if (!native) {
      native = nativeFactory();
      // Do not let any native default quit hook bypass our safety/verification gate.
      native.autoDownload = false;
      native.disableWebInstaller = true;
      native.autoInstallOnAppQuit = false;
      native.allowDowngrade = false;
      native.allowPrerelease = true;
      native.channel = 'alpha';
      // Setting channel may change downgrade defaults; reassert after it.
      native.allowDowngrade = false;
      native.on('error', error => { void failed(error); });
    }
    return native;
  }
  function stage(envelope) { return run(async () => {
    ready = null;
    if (!enabled || disposed) return publish({ state: 'manual_required' });
    const candidate = verifyManifest(envelope, productionTrust.publicKey, options);
    if (candidate.isCurrent) return publish({ state: 'up_to_date' });
    if (candidate.artifact.format !== 'exe' || candidate.artifact.installerType !== 'nsis') throw new Error('Signed artifact is not an NSIS installer');
    publish({ state: 'checking' });
    const updater = getNative();
    const result = await updater.checkForUpdates();
    if (!result || result.updateInfo?.version !== candidate.version) throw new Error('Native update metadata does not match signed release');
    publish({ state: 'downloading' });
    const files = await updater.downloadUpdate();
    // No nsis-web/package payloads: the approved installer must be one whole EXE.
    if (!Array.isArray(files) || files.length !== 1 || typeof files[0] !== 'string') throw new Error('Expected exactly one full NSIS installer');
    await verifyInstaller(files[0], candidate.artifact);
    if (trustPolicy === 'authenticode-and-ed25519') await verifySignature(files[0], thumbprints.map(x => x.toUpperCase()));
    if (disposed) throw new Error('Updater stopped');
    ready = { candidate, file: files[0] };
    if (updater.installerPath !== files[0]) throw new Error('Native installer path does not match verified file');
    return publish({ state: 'ready_for_safe_exit', availableVersion: candidate.version, reason: 'Verified installer staged; waiting for normal idle exit, never a forced restart' });
  }); }
  function applyOnSafeExit({ normalQuit = false, sessionEnding = true } = {}) { return run(async () => {
    if (!enabled || disposed || !ready) return publish({ state: 'manual_required' });
    if (!normalQuit || sessionEnding || isSafeToInstall() !== true) return publish({ state: 'deferred', reason: 'Waiting for normal exit with no game, chat, recording or backend work' });
    const staged = ready;
    if (Date.parse(staged.candidate.expiresAt) <= Date.now()) throw new Error('Signed release expired; recheck before installation');
    // Recheck cached bytes/signature immediately before native installer dispatch.
    await verifyInstaller(staged.file, staged.candidate.artifact);
    if (trustPolicy === 'authenticode-and-ed25519') await verifySignature(staged.file, thumbprints.map(x => x.toUpperCase()));
    if (disposed || ready !== staged || isSafeToInstall() !== true) return publish({ state: 'deferred' });
    preparationStarted = true;
    await beforeInstall({ targetVersion: staged.candidate.version });
    // Preparation can await backups and process shutdown. Revalidate AFTER it;
    // never dispatch bytes/path that changed while the application was quiescing.
    if (native.installerPath !== staged.file) throw new Error('Native installer path changed before dispatch');
    await verifyInstaller(staged.file, staged.candidate.artifact);
    if (trustPolicy === 'authenticode-and-ed25519') await verifySignature(staged.file, thumbprints.map(x => x.toUpperCase()));
    if (native.installerPath !== staged.file) throw new Error('Native installer path changed during final verification');
    if (Date.parse(staged.candidate.expiresAt) <= Date.now()) throw new Error('Signed release expired before dispatch');
    if (disposed || ready !== staged || isSafeToInstall() !== true) throw new Error('Safe installation window closed after preparation');
    ready = null;
    publish({ state: 'installing', reason: 'Applying verified update on safe normal exit' });
    native.quitAndInstall(true, true);
    return structuredClone(status);
  }); }
  function stop() { disposed = true; ready = null; if (native) { native.autoInstallOnAppQuit = false; } }
  return { get status() { return structuredClone(status); }, stage, applyOnSafeExit, stop };
}
module.exports = { createInstalledUpdater, verifyInstaller, verifyWindowsSignature };
