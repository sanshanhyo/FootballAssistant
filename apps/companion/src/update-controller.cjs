'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { checkPublicAlphaReleases } = require('./update-releases.cjs');
const { trustedReleaseUrl, verifyManifest } = require('./update-security.cjs');

// No application replacement or process exit is performed by this Alpha controller.
// The unsigned macOS / portable Windows channel is intentionally manual-install-only.
function createUpdateController(options) {
  const { feedUrl, publicKey, cacheDir, onStatus = () => {}, fetchImpl = globalThis.fetch } = options;
  const signedMode = Boolean(feedUrl && publicKey);
  const automaticInstallEnabled = Boolean(signedMode && options.installedUpdater?.status.automaticInstallEnabled);
  let status = { state: 'idle', currentVersion: options.currentVersion, automaticInstallEnabled, installMode: automaticInstallEnabled ? 'idle-restart' : 'manual', source: signedMode ? 'signed-manifest' : 'github-releases', signedDownloadAvailable: signedMode, reason: signedMode ? null : 'Public Alpha release checks enabled; signed automatic downloads are not configured' };
  let candidate = null, signedEnvelope = null, operation = null, timer = null, aborter = null, stopped = false;
  const snapshot = () => structuredClone(status);
  function publish(patch) { status = { ...status, ...patch }; try { onStatus(snapshot()); } catch {} return snapshot(); }
  function run(task) {
    if (operation) return operation;
    if (stopped) return Promise.resolve(snapshot());
    operation = task().catch(error => publish({ state: signedMode ? 'error' : 'network_error', reason: error.message })).finally(() => { operation = null; aborter = null; });
    return operation;
  }
  async function request(url, maxBytes, consume) {
    trustedReleaseUrl(url);
    aborter = new AbortController();
    const timeout = setTimeout(() => aborter?.abort(), 10 * 60 * 1000);
    try {
      // GitHub release downloads redirect to release-assets.githubusercontent.com.
      // Follow only this exact HTTPS host, never arbitrary manifest-controlled redirects.
      let current = url, response;
      for (let redirects = 0; redirects <= 3; redirects++) {
        response = await fetchImpl(current, { redirect: 'manual', signal: aborter.signal });
        if (![301, 302, 303, 307, 308].includes(response.status)) break;
        const next = new URL(response.headers.get('location'), current);
        if (next.protocol !== 'https:' || next.username || next.password || next.port || !['github.com', 'release-assets.githubusercontent.com'].includes(next.hostname)) throw new Error('Untrusted download redirect');
        if (next.hostname === 'github.com') trustedReleaseUrl(next.href);
        current = next.href;
        await response.body?.cancel();
      }
      if (!response.ok || !response.body) { const error = new Error(`Update download failed (${response.status})`); error.httpStatus = response.status; throw error; }
      let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > maxBytes) throw new Error('Update exceeds declared size');
        await consume(chunk);
      }
      return size;
    } finally { clearTimeout(timeout); }
  }
  function check() { return run(async () => {
    // Keep an already verified download ready until the user installs it.
    if (status.state === 'downloaded') return snapshot();
    candidate = null; signedEnvelope = null;
    publish({ state: 'checking', reason: null, availableVersion: null, downloadedPath: null, releaseUrl: null });
    if (!signedMode) {
      aborter = new AbortController();
      const timeout = setTimeout(() => aborter?.abort(), 30000);
      try { return publish(await checkPublicAlphaReleases({ fetchImpl, signal: aborter.signal, currentVersion: options.currentVersion })); }
      finally { clearTimeout(timeout); }
    }
    const chunks = [];
    try { await request(feedUrl, 256 * 1024, chunk => chunks.push(Buffer.from(chunk))); }
    catch (error) { if (error.httpStatus === 404) return publish({ state: 'no_release', reason: 'No signed Alpha update channel has been published yet; no package was downloaded or installed' }); throw error; }
    const envelope = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    // Equal/older feeds are not executable update candidates; never download them.
    candidate = verifyManifest(envelope, publicKey, options);
    signedEnvelope = envelope;
    if (candidate.isCurrent) { candidate = null; return publish({ state: 'up_to_date', reason: null }); }
    return publish({ state: 'update_available', availableVersion: candidate.version, releaseUrl: candidate.releaseUrl, reason: automaticInstallEnabled ? 'Verified update available; background download and idle restart enabled' : 'Verified update available; manual installation required' });
  }); }
  function download() { return run(async () => {
    if (!signedMode) return publish({ state: 'manual_required', reason: 'No signed download feed configured. Review the official release page and install manually; the app will not download or execute this package.' });
    if (!candidate) throw new Error('Check for a compatible update first');
    if (options.installedUpdater?.status.automaticInstallEnabled) {
      const installed = await options.installedUpdater.stage(signedEnvelope);
      return publish({ state: installed.state, reason: installed.reason, installation: installed });
    }
    if (Date.parse(candidate.expiresAt) <= Date.now()) throw new Error('Update manifest expired; check again');
    if (!cacheDir) throw new Error('Update cache directory is not configured');
    const { artifact } = candidate;
    await fs.mkdir(cacheDir, { recursive: true, mode: 0o700 });
    const destination = path.join(cacheDir, `FootballAssistant-${candidate.version}-${options.platform}-${options.arch}.${artifact.format}`);
    const temporary = `${destination}.${crypto.randomUUID()}.part`;
    let file;
    try {
      file = await fs.open(temporary, 'wx', 0o600);
      const digest = crypto.createHash('sha256');
      publish({ state: 'downloading', reason: null });
      const bytes = await request(artifact.url, artifact.size, async chunk => { digest.update(chunk); await file.writeFile(chunk); });
      if (bytes !== artifact.size || digest.digest('hex') !== artifact.sha256) throw new Error('Update integrity verification failed');
      await file.sync(); await file.close(); file = null;
      await fs.rename(temporary, destination);
      return publish({ state: 'downloaded', downloadedPath: destination, reason: 'Verified package ready. Finish your game/conversation, quit, then install manually. Existing app/config are unchanged.' });
    } finally { await file?.close(); await fs.rm(temporary, { force: true }); }
  }); }
  function start({ intervalMs = 30 * 60 * 1000, autoDownload = true } = {}) {
    if (timer) return;
    if (!Number.isFinite(intervalMs) || intervalMs < 60000) throw new Error('Update interval must be at least one minute');
    stopped = false;
    const tick = async () => { await check(); if (!stopped && autoDownload && signedMode && status.state === 'update_available') await download(); };
    void tick(); timer = setInterval(tick, intervalMs); timer.unref?.();
  }
  function stop() { stopped = true; clearInterval(timer); timer = null; aborter?.abort(); }
  return { get status() { return snapshot(); }, check, download, start, stop };
}
module.exports = { createUpdateController };
