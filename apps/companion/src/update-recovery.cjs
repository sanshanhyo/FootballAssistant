'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { compareVersions } = require('./update-security.cjs');
const { validateModelConfig } = require('./credentials.cjs');
const SNAPSHOTS = Object.freeze([
  { source: 'companion-ui.json', limit: 2_000_000, validate: bytes => { if (JSON.parse(bytes.toString('utf8')).version !== 1) throw Error('Unsupported conversation schema'); } },
  { source: 'model-config.json', limit: 16384, validate: bytes => validateModelConfig(JSON.parse(bytes.toString('utf8')), { persisted: true }) },
  // Opaque OS-encrypted bytes only: never decrypt or include key material in the journal.
  { source: 'credentials.enc.json', limit: 32768, validate: bytes => { const value = JSON.parse(bytes.toString('utf8')); if (value.schema_version !== 1 || typeof value.ciphertext !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.ciphertext) || Object.keys(value).some(key => !['schema_version', 'ciphertext'].includes(key))) throw Error('Unsupported encrypted credential schema'); } },
  { source: 'backend/persona.md', limit: 16384, validate: bytes => { const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); if (!text.trim() || text.includes('\0')) throw Error('Invalid persona'); } },
]);

// This journal never restores data or executes an old installer. Recovery is explicit:
// retain the original settings snapshot and stop further unattended upgrades.
function createUpdateRecovery({ userData, currentVersion }) {
  compareVersions(currentVersion, currentVersion);
  const directory = path.join(userData, 'updates', 'recovery');
  const journalPath = path.join(directory, 'journal.json');
  let journal = null, status = { state: 'idle', currentVersion }, loaded = false, invalid = false, launchObserved = false;
  let queue = Promise.resolve();
  const snapshot = () => structuredClone(status);
  function show(value) {
    status = { ...value, currentVersion, journalPath, ...(value.backup ? { backupPath: path.join(directory, value.backup) } : {}) };
    return snapshot();
  }
  function blocked(reason) { return show({ ...(journal || {}), state: 'recovery_required', reason }); }
  async function safeDirectory(dir) {
    await fs.mkdir(dir, { recursive: true, mode: 0o700 });
    const info = await fs.lstat(dir);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Recovery directory must not be a symlink');
  }
  async function ensureDirectory() {
    await safeDirectory(userData); await safeDirectory(path.join(userData, 'updates')); await safeDirectory(directory);
  }
  async function smallFile(file, limit) {
    const info = await fs.lstat(file);
    if (!info.isFile() || info.isSymbolicLink() || info.size > limit) throw new Error('Recovery input must be a bounded regular file');
    return fs.readFile(file);
  }
  function validJournal(value) {
    if (!value || value.schema !== 1 || !['prepared', 'awaiting_health', 'healthy', 'recovery_required'].includes(value.state) || !/^[a-f0-9-]{36}$/.test(value.transaction || '')) throw new Error('Invalid update recovery journal');
    if (compareVersions(value.targetVersion, value.previousVersion) <= 0 || !Number.isFinite(Date.parse(value.preparedAt))) throw new Error('Invalid update recovery version/time');
    if (value.backup !== null && (value.backup !== `settings-${value.transaction}.json` || !/^[a-f0-9]{64}$/.test(value.backupSha256 || ''))) throw new Error('Invalid settings backup metadata');
    if (value.snapshots !== undefined && (!Array.isArray(value.snapshots) || value.snapshots.length > SNAPSHOTS.length || value.snapshots.some((item, index) => !SNAPSHOTS.some(spec => spec.source === item.source) || item.backup !== `data-${value.transaction}-${index}.bak` || !/^[a-f0-9]{64}$/.test(item.sha256 || '')) || new Set(value.snapshots.map(item => item.source)).size !== value.snapshots.length)) throw Error('Invalid user-data snapshot metadata');
    return value;
  }
  async function load() {
    if (loaded) return;
    loaded = true;
    try {
      await ensureDirectory();
      journal = validJournal(JSON.parse((await smallFile(journalPath, 16384)).toString('utf8')));
      if (journal.backup) {
        const backup = await smallFile(path.join(directory, journal.backup), 16384);
        if (crypto.createHash('sha256').update(backup).digest('hex') !== journal.backupSha256) throw new Error('Settings recovery backup integrity check failed');
      }
      for (const item of journal.snapshots || []) {
        const spec = SNAPSHOTS.find(spec => spec.source === item.source);
        const bytes = await smallFile(path.join(directory, item.backup), spec.limit);
        if (crypto.createHash('sha256').update(bytes).digest('hex') !== item.sha256) throw Error('User-data backup integrity check failed');
      }
      show(journal);
    } catch (error) {
      // ENOENT is an empty state only if no journal was found. A missing referenced
      // backup is corruption and must not reset the recovery history.
      if (error.code === 'ENOENT' && journal === null) return;
      invalid = true; blocked('Recovery journal or retained backup is invalid; preserve files for manual recovery');
    }
  }
  async function atomicWrite(file, bytes) {
    const temporary = `${file}.${crypto.randomUUID()}.tmp`;
    let handle;
    try {
      handle = await fs.open(temporary, 'wx', 0o600); await handle.writeFile(bytes); await handle.sync(); await handle.close(); handle = null;
      await fs.rename(temporary, file);
      if (process.platform !== 'win32') { const dir = await fs.open(directory, 'r'); try { await dir.sync(); } finally { await dir.close(); } }
    } finally { await handle?.close(); await fs.rm(temporary, { force: true }); }
  }
  async function persist(value) {
    await atomicWrite(journalPath, JSON.stringify(value, null, 2) + '\n'); journal = value; return show(value);
  }
  function execute(task) {
    const next = queue.then(async () => {
      try { await load(); return await task(); }
      catch { invalid = true; return blocked('Recovery state could not be safely persisted; automatic upgrade is blocked'); }
    });
    queue = next.catch(() => {}); return next;
  }
  function prepare({ targetVersion }) { return execute(async () => {
    if (invalid || (journal && journal.state !== 'healthy')) return blocked('An unresolved update recovery record exists; automatic upgrade is blocked');
    if (compareVersions(targetVersion, currentVersion) <= 0) return blocked('Recovery preparation requires a newer target version');
    const transaction = crypto.randomUUID(); let backup = null, backupSha256 = null;
    try {
      const bytes = await smallFile(path.join(userData, 'settings.json'), 16384);
      const settings = JSON.parse(bytes.toString('utf8'));
      // This settings snapshot accepts only the non-secret bootstrap schema.
      // Account/UI/persona checkpoints use the separate fixed allowlist below;
      // backend environment files and the rest of the profile are never traversed.
      if (!settings || settings.version !== 1 || Object.keys(settings).some(key => !['version', 'backend', 'bridgePrivateRoot', 'backendEnvFile'].includes(key)) || !settings.backend || Object.keys(settings.backend).some(key => key !== 'port') || !Number.isInteger(settings.backend.port) || settings.backend.port < 1 || settings.backend.port > 65535 || typeof settings.bridgePrivateRoot !== 'string' || typeof settings.backendEnvFile !== 'string') throw new Error('Settings schema cannot be safely snapshotted');
      backup = `settings-${transaction}.json`; backupSha256 = crypto.createHash('sha256').update(bytes).digest('hex');
      // Immutable unique-name backup: never replace an earlier upgrade's snapshot.
      const handle = await fs.open(path.join(directory, backup), 'wx', 0o600);
      try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const snapshots = [];
    // Caller has quiesced IPC, flushed the UI write queue and stopped its owned backend.
    // Only fixed files are copied; never traverse the profile or copy active SQLite files.
    for (const spec of SNAPSHOTS) {
      try {
        const source = path.join(userData, spec.source);
        if (spec.source.includes('/')) {
          const parent = await fs.lstat(path.dirname(source));
          if (!parent.isDirectory() || parent.isSymbolicLink()) throw Error('Unsafe data snapshot parent');
        }
        const bytes = await smallFile(source, spec.limit); spec.validate(bytes);
        const name = `data-${transaction}-${snapshots.length}.bak`;
        const handle = await fs.open(path.join(directory, name), 'wx', 0o600);
        try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
        snapshots.push({ source: spec.source, backup: name, sha256: crypto.createHash('sha256').update(bytes).digest('hex') });
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    // Outside editors/services do not share the app write queue. Detect changes
    // during checkpoint creation rather than approving a mixed-version snapshot.
    if (backup && crypto.createHash('sha256').update(await smallFile(path.join(userData, 'settings.json'), 16384)).digest('hex') !== backupSha256) throw Error('Settings changed during checkpoint');
    for (const item of snapshots) {
      const spec = SNAPSHOTS.find(spec => spec.source === item.source);
      const bytes = await smallFile(path.join(userData, item.source), spec.limit);
      if (crypto.createHash('sha256').update(bytes).digest('hex') !== item.sha256) throw Error('User data changed during checkpoint');
    }
    return persist({ schema: 1, state: 'prepared', transaction, previousVersion: currentVersion, targetVersion, preparedAt: new Date().toISOString(), backup, backupSha256, snapshots });
  }); }
  function beginLaunch() { return execute(async () => {
    if (invalid || launchObserved || !journal) return snapshot();
    launchObserved = true;
    if (journal.state === 'recovery_required') return snapshot();
    if (journal.state === 'healthy') {
      if (currentVersion === journal.targetVersion) return snapshot();
      return persist({ ...journal, state: 'recovery_required', reason: 'Running version differs from the last healthy upgraded version; validate configuration compatibility before another update' });
    }
    if (journal.state === 'prepared' && currentVersion === journal.targetVersion) return persist({ ...journal, state: 'awaiting_health', launchedAt: new Date().toISOString() });
    return persist({ ...journal, state: 'recovery_required', reason: journal.state === 'awaiting_health' ? 'Previous upgraded launch did not acknowledge backend/UI health; retained settings are available for recovery' : 'Expected updated version did not start; retained settings are available for recovery' });
  }); }
  function acknowledgeHealthy() { return execute(async () => {
    if (invalid || !journal) return snapshot();
    if (!launchObserved || journal.state !== 'awaiting_health' || journal.targetVersion !== currentVersion) return snapshot();
    return persist({ ...journal, state: 'healthy', healthyAt: new Date().toISOString() });
  }); }
  function fail(reason = 'Updated application failed its startup health check') { return execute(async () => {
    if (invalid || !journal || journal.state === 'healthy') return snapshot();
    return persist({ ...journal, state: 'recovery_required', reason: String(reason).slice(0, 400) });
  }); }
  return { get status() { return snapshot(); }, prepare, beginLaunch, acknowledgeHealthy, fail };
}
module.exports = { createUpdateRecovery };
