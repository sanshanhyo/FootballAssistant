'use strict';
// Main-process only. Never execute a loader, start a game, or follow a config target.
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID, randomBytes } = require('node:crypto');
const GAME_HASH = 'bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f';
const LOADER_HASH = '2a7cbf74d26abe4765c3e662db1721b923bac39849ebfef2ca5dc7de7e2d9b7f';
const PLUGIN = 'BepInEx/plugins/FootballAssistant/FootballAssistant.MatchReader.dll';
const CONFIG = 'BepInEx/config/io.footballassistant.matchreader.cfg';
const SHARED_CONFIG = 'BepInEx/config/BepInEx.cfg';
const UNITY_HASH = 'c927f41849e3347cfc430a90b05f072df07ac45b0b2a3b39e9412c776f7c0d57';
const MAX_FILE = 256 * 1024 * 1024;
const digest = value => createHash('sha256').update(value).digest('hex');
const fail = (code, message = code) => { throw Object.assign(Error(message), { code }); };
const canonical = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value);
function relativeName(value) {
  if (typeof value !== 'string' || !value || value.length > 1024 || !/^[\x20-\x7e]+$/.test(value) || /[\\<>:"|?*]/.test(value) || value.startsWith('/') || value.split('/').some(p => !p || p === '.' || p === '..' || /[. ]$/.test(p) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p))) fail('unsafe_path');
  return value;
}
function child(root, name) { relativeName(name); return path.join(root, ...name.split('/')); }
function parents(directory) {
  let current = path.resolve(directory);
  for (;;) {
    try {
      const info = fs.lstatSync(current);
      if (!info.isDirectory() || info.isSymbolicLink() || (process.platform !== 'win32' && canonical(fs.realpathSync(current)) !== canonical(current))) fail('unsafe_directory');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const next = path.dirname(current); if (next === current) break; current = next;
  }
}
function read(file, maximum = MAX_FILE) {
  parents(path.dirname(file));
  const before = fs.lstatSync(file);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || !Number.isSafeInteger(before.size) || before.size > maximum) fail('unsafe_file');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const opened = fs.fstatSync(fd);
    if (opened.dev !== before.dev || opened.ino !== before.ino || opened.nlink !== 1 || opened.size !== before.size) fail('file_changed');
    const bytes = Buffer.alloc(before.size + 1); let count = 0;
    while (count < bytes.length) { const n = fs.readSync(fd, bytes, count, bytes.length - count, count); if (!n) break; count += n; }
    const after = fs.lstatSync(file); parents(path.dirname(file));
    if (after.isSymbolicLink() || after.nlink !== 1 || after.dev !== before.dev || after.ino !== before.ino || after.mtimeMs !== before.mtimeMs || count !== before.size || after.size !== count) fail('file_changed');
    return bytes.subarray(0, count);
  } finally { fs.closeSync(fd); }
}
function fingerprint(file, maximum = MAX_FILE) {
  let fd;
  try {
    parents(path.dirname(file)); const before = fs.lstatSync(file);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || !Number.isSafeInteger(before.size) || before.size > maximum) fail('unsafe_file');
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    const opened = fs.fstatSync(fd);
    if (opened.dev !== before.dev || opened.ino !== before.ino || opened.nlink !== 1 || opened.size !== before.size) fail('file_changed');
    const hash = createHash('sha256'), buffer = Buffer.alloc(1024 * 1024); let total = 0;
    for (;;) { const count = fs.readSync(fd, buffer, 0, buffer.length, total); if (!count) break; total += count; if (total > maximum) fail('file_size_limit'); hash.update(buffer.subarray(0, count)); }
    const after = fs.lstatSync(file); parents(path.dirname(file));
    if (after.isSymbolicLink() || after.nlink !== 1 || after.dev !== before.dev || after.ino !== before.ino || after.mtimeMs !== before.mtimeMs || total !== before.size || after.size !== total) fail('file_changed');
    return { sha256: hash.digest('hex'), size: total, dev: before.dev, ino: before.ino, mtimeMs: before.mtimeMs };
  } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  finally { if (fd !== undefined) fs.closeSync(fd); }
}
function sameContent(actual, expected) { return actual === null ? expected === null : Boolean(expected && actual.sha256 === expected.sha256 && actual.size === expected.size); }
function sameFingerprint(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function mkdir(directory, created) {
  parents(directory);
  const missing = []; let cursor = path.resolve(directory);
  while (!fs.existsSync(cursor)) { missing.push(cursor); cursor = path.dirname(cursor); }
  for (const dir of missing.reverse()) { parents(path.dirname(dir)); fs.mkdirSync(dir, { mode: 0o700 }); parents(dir); if (created) created.push(dir); }
  parents(directory);
}
function atomic(file, bytes, expected) {
  parents(path.dirname(file));
  if (!sameFingerprint(fingerprint(file), expected)) fail('target_changed');
  const temporary = path.join(path.dirname(file), `.fa-match-${randomUUID()}.tmp`);
  try {
    const fd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW || 0), 0o600);
    try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    parents(path.dirname(file));
    if (!sameFingerprint(fingerprint(file), expected)) fail('target_changed');
    fs.renameSync(temporary, file);
  } finally { try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
}
function writeJson(file, value) { mkdir(path.dirname(file)); atomic(file, Buffer.from(JSON.stringify(value, null, 2)), fingerprint(file)); }
function readJson(file) { return JSON.parse(read(file, 2 * 1024 * 1024).toString('utf8')); }
function walk(root, prefix = '', result = []) {
  parents(root);
  if (!fs.existsSync(root)) return result;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name; relativeName(relative);
    const file = path.join(root, entry.name); const info = fs.lstatSync(file);
    if (info.isSymbolicLink()) fail('unsafe_file');
    if (info.isDirectory()) walk(file, relative, result);
    else if (info.isFile() && info.nlink === 1) { result.push(relative); if (result.length > 4096) fail('file_count_limit'); }
    else fail('unsafe_file');
  }
  return result;
}
// Parse conservatively and preserve all unrelated configuration lines verbatim.
function sharedConfiguration(bytes) {
  const text = bytes ? new TextDecoder('utf-8', { fatal: true }).decode(bytes) : '';
  if (text.includes('\0')) fail('shared_config_invalid');
  const newline = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.split(/\r?\n/), sections = new Set(), keys = new Set();
  const wanted = new Map([['IL2CPP/UnityBaseLibrariesSource', ''], ['IL2CPP/UpdateInteropAssemblies', 'true'], ['Logging/UnityLogListening', 'false']]);
  let section = '', changed = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim(); if (!line || line.startsWith('#') || line.startsWith(';')) continue;
    const heading = /^\[([^\[\]]+)\]$/.exec(line);
    if (heading) { section = heading[1]; if (sections.has(section.toLowerCase())) fail('shared_config_invalid'); sections.add(section.toLowerCase()); continue; }
    const key = /^([^=]+?)\s*=\s*(.*)$/.exec(line);
    if (!section || !key) fail('shared_config_invalid');
    const id = section + '/' + key[1].trim();
    if (keys.has(id.toLowerCase())) fail('shared_config_invalid'); keys.add(id.toLowerCase());
    // Case aliases are ambiguous across config implementations: refuse them.
    if ([...wanted.keys()].some(k => k.toLowerCase() === id.toLowerCase() && k !== id)) fail('shared_config_invalid');
    if (wanted.has(id)) { const value = wanted.get(id); if (key[2].trim() !== value) { lines[i] = key[1].trim() + ' = ' + value; changed = true; } wanted.delete(id); }
  }
  for (const name of ['IL2CPP', 'Logging']) {
    const missing = [...wanted].filter(([key]) => key.startsWith(name + '/'));
    if (!missing.length) continue;
    let index = lines.findIndex(line => line.trim() === '[' + name + ']');
    if (index < 0) { if (sections.has(name.toLowerCase())) fail('shared_config_invalid'); lines.push('', '[' + name + ']'); index = lines.length - 1; }
    lines.splice(index + 1, 0, ...missing.map(([key, value]) => key.split('/')[1] + ' = ' + value)); changed = true;
  }
  return { bytes: changed ? Buffer.from(lines.join(newline) + (lines.at(-1) ? newline : ''), 'utf8') : (bytes || Buffer.alloc(0)), changed };
}
function runtimeGamePolicy(gameRoot) {
  const libs = child(gameRoot, 'BepInEx/unity-libs'); parents(libs);
  if (fs.existsSync(libs) && fs.readdirSync(libs).length) fail('existing_unity_libraries', 'Existing Unity libraries require manual review; they were not deleted.');
  const unity = fingerprint(child(gameRoot, 'UnityPlayer.dll'), 2 * 1024 * 1024 * 1024);
  if (!unity || unity.sha256 !== UNITY_HASH) fail('unsupported_unity_binary');
}
function allowedDeployment(name) {
  relativeName(name);
  return ['winhttp.dll', '.doorstop_version', 'doorstop_config.ini', PLUGIN].includes(name) || name.startsWith('dotnet/') || name.startsWith('BepInEx/core/');
}
function validateWindowsMatchPayload(payloadRoot) {
  if (typeof payloadRoot !== 'string' || !path.isAbsolute(payloadRoot)) fail('payload_missing');
  parents(payloadRoot);
  const raw = read(path.join(payloadRoot, 'manifest.json'), 2 * 1024 * 1024);
  const manifest = JSON.parse(raw.toString('utf8'));
  if (manifest.schema !== 1 || manifest.target !== 'win32-x64' || manifest.producerId !== 'io.footballassistant.matchreader' || manifest.protocol !== 'fa-match-snapshot/0.1' || manifest.gamePluginSha256 !== GAME_HASH || manifest.loader?.id !== 'bepinex' || manifest.loader?.version !== '6.0.0-be.785+6abdba4' || manifest.loader?.sourceSha256 !== LOADER_HASH) fail('payload_identity_invalid');
  const policy = manifest.runtimePolicy;
  if (!policy || policy.interopMode !== 'local-metadata-no-unstrip' || policy.unityBaseLibrariesSource !== '' || policy.unityLogListening !== false || policy.updateInteropAssemblies !== true || policy.runtimeDependencyDownloads !== false || policy.unityPlayerSha256 !== UNITY_HASH) fail('runtime_policy_invalid');
  const files = manifest.files, sizes = manifest.fileSizes;
  if (!files || Array.isArray(files) || typeof files !== 'object' || !sizes || typeof sizes !== 'object' || Array.isArray(sizes) || !Array.isArray(manifest.deploymentPaths) || !manifest.deploymentPaths.length) fail('payload_manifest_invalid');
  const names = Object.keys(files).sort(), folded = new Set(); let total = 0;
  if (names.length > 4096 || JSON.stringify(names) !== JSON.stringify(Object.keys(sizes).sort()) || !names.some(name => name.startsWith('licenses/'))) fail('payload_manifest_invalid');
  for (const name of names) {
    relativeName(name);
    if ((name !== 'source-provenance.json' && !/^(payload|licenses|sources)\//.test(name)) || folded.has(name.toLowerCase()) || !/^[a-f0-9]{64}$/.test(files[name]) || !Number.isSafeInteger(sizes[name]) || sizes[name] < 0 || sizes[name] > MAX_FILE) fail('payload_manifest_invalid');
    folded.add(name.toLowerCase()); total += sizes[name]; if (total > 1024 * 1024 * 1024) fail('payload_size_limit');
    const bytes = read(child(payloadRoot, name));
    if (bytes.length !== sizes[name] || digest(bytes) !== files[name]) fail('payload_integrity_failed');
  }
  const deployment = manifest.deploymentPaths;
  const required = ['winhttp.dll', '.doorstop_version', 'doorstop_config.ini', 'dotnet/coreclr.dll', 'dotnet/System.Private.CoreLib.dll',
    'BepInEx/core/BepInEx.Core.dll', 'BepInEx/core/BepInEx.Unity.Common.dll', 'BepInEx/core/BepInEx.Unity.IL2CPP.dll',
    'BepInEx/core/BepInEx.Preloader.Core.dll', 'BepInEx/core/MonoMod.RuntimeDetour.dll', 'BepInEx/core/MonoMod.Utils.dll',
    'BepInEx/core/Il2CppInterop.Runtime.dll', 'BepInEx/core/Il2CppInterop.Generator.dll', 'BepInEx/core/Cpp2IL.Core.dll', 'BepInEx/core/dobby.dll', PLUGIN];
  if (required.some(name => !deployment.includes(name)) || !Object.hasOwn(files, 'source-provenance.json')) fail('payload_incomplete');
  if (new Set(deployment.map(name => String(name).toLowerCase())).size !== deployment.length || !deployment.includes(PLUGIN) || !deployment.includes('winhttp.dll') || !deployment.includes('doorstop_config.ini') || !deployment.some(n => n.startsWith('dotnet/')) || !deployment.includes('BepInEx/core/BepInEx.Unity.IL2CPP.dll')) fail('payload_incomplete');
  for (const name of deployment) if (!allowedDeployment(name) || !Object.hasOwn(files, `payload/${name}`)) fail('payload_path_invalid');
  if (names.some(name => name.startsWith('payload/') && !deployment.includes(name.slice(8)))) fail('payload_unlisted_file');
  const actual = walk(payloadRoot).sort();
  if (JSON.stringify(actual) !== JSON.stringify(['manifest.json', ...names].sort())) fail('payload_unlisted_file');
  return { root: payloadRoot, manifest, manifestHash: digest(raw), deploymentPaths: [...deployment].sort(), producerId: manifest.producerId, protocol: manifest.protocol };
}
function gameIdentity(gamePath) {
  if (typeof gamePath !== 'string' || !path.isAbsolute(gamePath) || /[\0\r\n]/.test(gamePath) || gamePath.startsWith('\\\\') || path.basename(gamePath).toLowerCase() !== 'fm.exe') fail('invalid_game_path');
  parents(path.dirname(gamePath)); const exe = fingerprint(gamePath, 2 * 1024 * 1024 * 1024); if (!exe) fail('game_missing');
  gamePath = fs.realpathSync(gamePath);
  const gameRoot = path.dirname(gamePath); let pluginPath, plugin;
  for (const name of ['fm_Data/Plugins/x86_64/game_plugin.dll', 'fm_Data/Plugins/game_plugin.dll', 'game_plugin.dll']) {
    const file = child(gameRoot, name), value = fingerprint(file, 2 * 1024 * 1024 * 1024);
    if (value) { if (plugin) fail('ambiguous_game_binary'); pluginPath = file; plugin = value; }
  }
  if (!plugin || plugin.sha256 !== GAME_HASH) fail('unsupported_game_binary');
  return { gamePath: path.resolve(gamePath), gameRoot, pluginPath, exe, plugin };
}
function createWindowsMatchInstaller({ userData, resourcesPath, platform = process.platform, probeGame }) {
  // Construction is inert even on unsupported platforms.
  let busy = false; const plans = new Map();
  let root = path.join(userData, 'match-reader');
  let index = path.join(root, 'deployment.json');
  const payloadRoot = path.join(resourcesPath, 'match-windows-x64');
  let snapshotPath = path.join(root, 'active', 'match.json');
  const checkPlatform = () => { if (platform !== 'win32') fail('unsupported_platform'); if (!path.isAbsolute(userData) || /[\0\r\n]/.test(userData)) fail('invalid_user_data'); parents(userData);
    let existing = path.resolve(userData); const missing = [];
    while (!fs.existsSync(existing)) { missing.unshift(path.basename(existing)); existing = path.dirname(existing); }
    const realUserData = path.join(fs.realpathSync(existing), ...missing);
    root = path.join(realUserData, 'match-reader'); index = path.join(root, 'deployment.json'); snapshotPath = path.join(root, 'active', 'match.json');
  };
  const closed = async gameRoot => { if (typeof probeGame !== 'function') fail('game_state_unknown'); const value = await probeGame(gameRoot); const running = typeof value === 'boolean' ? value : value?.running; if (running !== false) fail(running === true ? 'game_running' : 'game_state_unknown'); };
  const exclusive = async fn => { if (busy) fail('operation_busy'); busy = true; try { return await fn(); } finally { busy = false; } };
  const journalPath = id => path.join(root, 'backups', id, 'journal.json');
  function receipt() {
    let pointer; try { pointer = readJson(index); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
    if (pointer.schema !== 1 || !/^[a-f0-9-]{36}$/.test(pointer.id)) fail('journal_invalid');
    return loadJournal(pointer.id);
  }
  function loadJournal(id, seen = new Set()) {
    if (!/^[a-f0-9-]{36}$/.test(id) || seen.has(id) || seen.size >= 32) fail('journal_invalid');
    seen.add(id);
    const journal = readJson(journalPath(id));
    if (journal.previousDeploymentId !== undefined && journal.previousDeploymentId !== null && (!/^[a-f0-9-]{36}$/.test(journal.previousDeploymentId) || journal.previousDeploymentId === journal.id)) fail('journal_invalid');
    if (journal.schema !== 1 || journal.id !== id || !Array.isArray(journal.files) || journal.files.length > 4096 || journal.snapshotPath !== snapshotPath || !Array.isArray(journal.createdDirectories)) fail('journal_invalid');
    if (typeof journal.gamePath !== 'string' || !path.isAbsolute(journal.gamePath) || path.basename(journal.gamePath).toLowerCase() !== 'fm.exe' || journal.gameRoot !== path.dirname(journal.gamePath)) fail('journal_invalid');
    const names = new Set();
    for (const entry of journal.files) {
      if ((!allowedDeployment(entry.path) && entry.path !== CONFIG && entry.path !== SHARED_CONFIG) || names.has(entry.path.toLowerCase()) || !['created', 'replaced', 'reused'].includes(entry.action) || !/^[a-f0-9]{64}$/.test(entry.after?.sha256) || !Number.isSafeInteger(entry.after?.size) || entry.after.size > MAX_FILE || entry.after.size < 0 || (entry.before && (!/^[a-f0-9]{64}$/.test(entry.before.sha256) || !Number.isSafeInteger(entry.before.size) || entry.before.size < 0 || entry.before.size > MAX_FILE))) fail('journal_invalid');
      if ((entry.action === 'created') !== (entry.before === null)) fail('journal_invalid');
      names.add(entry.path.toLowerCase());
    }
    for (const dir of journal.createdDirectories) { const relative = path.relative(journal.gameRoot, dir).split(path.sep).join('/'); relativeName(relative); if (!['BepInEx', 'dotnet'].some(prefix => relative === prefix || relative.startsWith(prefix + '/'))) fail('journal_invalid'); }
    // Recover a crash after restoring the old version but before publishing its index.
    if (journal.state === 'rolled_back' && journal.previousDeploymentId) return loadJournal(journal.previousDeploymentId, seen);
    return journal;
  }
  const save = journal => writeJson(journalPath(journal.id), journal);
  function computePlan(gamePath, payload, previous = null) {
    const game = gameIdentity(gamePath), files = [], conflicts = [];
    runtimeGamePolicy(game.gameRoot);
    const sharedPath = child(game.gameRoot, SHARED_CONFIG);
    const sharedBefore = fingerprint(sharedPath);
    const shared = sharedConfiguration(sharedBefore ? read(sharedPath, 1024 * 1024) : null);
    const configuration = Buffer.from(`[Output]\nSnapshotPath = ${snapshotPath.split(path.sep).join('/')}\n`, 'utf8');
    const expected = new Map(payload.deploymentPaths.map(name => [name, { sha256: payload.manifest.files[`payload/${name}`], size: payload.manifest.fileSizes[`payload/${name}`] }]));
    expected.set(SHARED_CONFIG, { sha256: digest(shared.bytes), size: shared.bytes.length });
    expected.set(CONFIG, { sha256: digest(configuration), size: configuration.length });
    for (const [name, after] of expected) {
      const before = fingerprint(child(game.gameRoot, name));
      const action = sameContent(before, after) ? 'reused' : before ? 'replaced' : 'created';
      const loader = name !== PLUGIN && name !== CONFIG;
      const prior = previous?.files.find(entry => entry.path === name);
      const owned = Boolean(prior && (prior.owned === true || (prior.owned === undefined && prior.action !== 'reused')) && sameContent(before, prior.after));
      if (action === 'replaced' && !owned && name !== SHARED_CONFIG) {
        const migratable = ['winhttp.dll', 'doorstop_config.ini', '.doorstop_version'].includes(name);
        conflicts.push({ path: name, reason: migratable ? 'loader_differs' : loader ? 'incompatible_existing_loader' : name === CONFIG ? 'reader_config_unowned' : 'reader_plugin_differs', migratable });
      }
      files.push({ path: name, action, before, after, loader, owned: action !== 'reused' || owned });
    }
    for (const prefix of ['BepInEx/core', 'dotnet']) {
      for (const relative of walk(child(game.gameRoot, prefix))) { const name = `${prefix}/${relative}`; if (!expected.has(name)) conflicts.push({ path: name, reason: 'unlisted_loader_file', migratable: false }); }
    }
    for (const name of ['version.dll', 'dinput8.dll', 'dxgi.dll', 'winmm.dll', 'doorstop.dll']) {
      if (fingerprint(child(game.gameRoot, name))) conflicts.push({ path: name, reason: 'other_loader_requires_manual_review', migratable: false });
    }
    return { game, files, conflicts, needsSharedConfigConsent: Boolean(sharedBefore && shared.changed), sharedConfiguration: shared.bytes.toString('utf8'), configuration: configuration.toString('utf8'), manifestHash: payload.manifestHash, previousReceipt: previous ? { id: previous.id, file: fingerprint(journalPath(previous.id)), index: fingerprint(index) } : null };
  }
  function planFingerprint(plan) { return digest(JSON.stringify({ game: plan.game, files: plan.files, conflicts: plan.conflicts, configuration: plan.configuration, sharedConfiguration: plan.sharedConfiguration, needsSharedConfigConsent: plan.needsSharedConfigConsent, manifestHash: plan.manifestHash, previousReceipt: plan.previousReceipt })); }
  async function inspect(gamePath, forUpgrade = false) {
    if (platform !== 'win32') return { state: 'unsupported_platform', canRollback: false };
    checkPlatform(); const journal = receipt();
    if (!journal || journal.state === 'rolled_back') {
      let payload; try { payload = validateWindowsMatchPayload(payloadRoot); } catch (error) { return { state: 'payload_unavailable', code: error.code || 'payload_invalid', canRollback: false, gamePath: gamePath || null }; }
      return { state: 'not_deployed', canRollback: false, payloadReady: true, gamePath: gamePath || null, producerId: payload.producerId };
    }
    const result = { deploymentId: journal.id, gamePath: journal.gamePath, gameRoot: journal.gameRoot, snapshotPath, canRollback: true };
    if (gamePath && canonical(gamePath) !== canonical(journal.gamePath)) return { ...result, state: 'different_game_deployment' };
    if (journal.state !== 'deployed') return { ...result, state: 'recovery_required' };
    try {
      const game = gameIdentity(journal.gamePath);
      runtimeGamePolicy(game.gameRoot);
      if (!forUpgrade && !journal.files.some(entry => entry.path === SHARED_CONFIG)) return { ...result, state: 'modified', reason: 'runtime_policy_missing' };
      if (!sameContent(game.exe, journal.game.exe) || !sameContent(game.plugin, journal.game.plugin)) return { ...result, state: 'modified', reason: 'game_changed' };
      for (const entry of journal.files) {
        if (entry.path === SHARED_CONFIG && !sharedConfiguration(read(child(journal.gameRoot, entry.path), 1024 * 1024)).changed) continue;
        if (!sameContent(fingerprint(child(journal.gameRoot, entry.path)), entry.after)) return { ...result, state: 'modified', reason: 'installed_file_changed', modifiedPath: entry.path };
      }
    } catch (error) { return { ...result, state: 'modified', reason: error.code || 'installed_file_unavailable' }; }
    return { ...result, state: 'deployed' };
  }
  async function restore(journal) {
    await closed(journal.gameRoot); parents(journal.gameRoot);
    if (journal.previousDeploymentId && loadJournal(journal.previousDeploymentId).state !== 'deployed') fail('previous_deployment_invalid');
    const restores = [];
    for (const entry of journal.files) {
      if (entry.action === 'reused') continue;
      const file = child(journal.gameRoot, entry.path), current = fingerprint(file);
      if (sameContent(current, entry.before)) continue;
      if (!sameContent(current, entry.after)) fail('rollback_file_modified', `Rollback preserved modified file: ${entry.path}`);
      let bytes = null;
      if (entry.before) { bytes = read(child(path.join(root, 'backups', journal.id, 'original'), entry.path)); if (digest(bytes) !== entry.before.sha256 || bytes.length !== entry.before.size) fail('backup_integrity_failed'); }
      restores.push({ entry, file, current, bytes });
    }
    journal.state = 'rolling_back'; save(journal);
    for (const { entry, file, current, bytes } of restores.reverse()) {
      await closed(journal.gameRoot);
      if (!sameFingerprint(fingerprint(file), current)) fail('rollback_file_modified');
      if (bytes) atomic(file, bytes, current); else { parents(path.dirname(file)); fs.unlinkSync(file); }
      entry.phase = 'restored'; save(journal);
    }
    for (const dir of [...new Set(journal.createdDirectories)].sort((a, b) => b.length - a.length)) {
      try { parents(dir); fs.rmdirSync(dir); } catch (error) { if (!['ENOENT', 'ENOTEMPTY', 'EEXIST'].includes(error.code)) throw error; }
    }
    journal.state = 'rolled_back'; save(journal);
    if (journal.previousDeploymentId) writeJson(index, { schema: 1, id: journal.previousDeploymentId });
    return { state: 'rolled_back', deploymentId: journal.id, gamePath: journal.gamePath, snapshotPath, canRollback: false };
  }
  return {
    inspect: gamePath => inspect(gamePath),
    plan: gamePath => exclusive(async () => {
      checkPlatform(); let previous = receipt();
      if (previous?.state === 'rolled_back') previous = null;
      if (previous && (previous.state !== 'deployed' || (await inspect(gamePath, true)).state !== 'deployed')) fail('existing_deployment', 'Recover or review the modified deployment first.');
      const payload = validateWindowsMatchPayload(payloadRoot); const value = computePlan(gamePath, payload, previous); await closed(value.game.gameRoot);
      const planId = randomUUID(), confirmationToken = randomBytes(32).toString('hex');
      plans.clear(); plans.set(planId, { ...value, confirmationToken, expires: Date.now() + 5 * 60 * 1000, fingerprint: planFingerprint(value) });
      const migrationFiles = value.conflicts.filter(c => c.migratable).map(c => c.path);
      return { state: 'planned', planId, confirmationToken, gamePath: value.game.gamePath, gameRoot: value.game.gameRoot, snapshotPath,
        needsSharedConfigConsent: value.needsSharedConfigConsent, sharedConfigChanges: value.needsSharedConfigConsent ? ['IL2CPP.UnityBaseLibrariesSource', 'IL2CPP.UpdateInteropAssemblies', 'Logging.UnityLogListening'] : [],
        canDeploy: value.conflicts.every(c => c.migratable), needsMigrationConsent: migrationFiles.length > 0, migrationFiles, conflicts: value.conflicts,
        operations: value.files.map(entry => ({ path: entry.path, action: entry.action, size: entry.after.size })) };
    }),
    deploy: input => exclusive(async () => {
      checkPlatform(); const plan = plans.get(input?.planId);
      if (!plan || input.confirm !== true || input.confirmationToken !== plan.confirmationToken || plan.expires < Date.now()) fail('confirmation_required');
      plans.clear();
      if (plan.needsSharedConfigConsent && input.confirmSharedConfig !== true) fail('shared_config_consent_required');
      if (plan.conflicts.some(c => !c.migratable)) fail('loader_conflict');
      if (plan.conflicts.length && input.migrateLoader !== true) fail('migration_consent_required');
      const payload = validateWindowsMatchPayload(payloadRoot); let previous = receipt(); if (previous?.state === 'rolled_back') previous = null;
      const current = computePlan(plan.game.gamePath, payload, previous);
      if (planFingerprint(current) !== plan.fingerprint) fail('plan_changed');
      await closed(plan.game.gameRoot);
      const id = randomUUID(); const backupRoot = path.join(root, 'backups', id); mkdir(backupRoot); mkdir(path.dirname(snapshotPath));
      const journal = { schema: 1, id, state: 'preparing', gamePath: plan.game.gamePath, gameRoot: plan.game.gameRoot, game: plan.game, snapshotPath,
        manifestHash: payload.manifestHash, previousDeploymentId: plan.previousReceipt?.id || null, createdDirectories: [], files: plan.files.map(entry => ({ ...entry, phase: 'pending' })) };
      for (const entry of journal.files) {
        if (entry.action !== 'replaced') continue;
        const bytes = read(child(journal.gameRoot, entry.path));
        if (digest(bytes) !== entry.before.sha256 || bytes.length !== entry.before.size) fail('plan_changed');
        const backup = child(path.join(backupRoot, 'original'), entry.path); mkdir(path.dirname(backup)); atomic(backup, bytes, null);
      }
      save(journal); writeJson(index, { schema: 1, id });
      try {
        journal.state = 'deploying'; save(journal);
        for (const entry of journal.files) {
          if (entry.action === 'reused') continue;
          await closed(journal.gameRoot);
          const bytes = entry.path === CONFIG ? Buffer.from(plan.configuration) : entry.path === SHARED_CONFIG ? Buffer.from(plan.sharedConfiguration) : read(child(payloadRoot, `payload/${entry.path}`));
          if (bytes.length !== entry.after.size || digest(bytes) !== entry.after.sha256) fail('payload_integrity_failed');
          const file = child(journal.gameRoot, entry.path);
          mkdir(path.dirname(file), journal.createdDirectories); save(journal);
          atomic(file, bytes, entry.before); entry.phase = 'written'; save(journal);
        }
        journal.state = 'deployed'; save(journal);
        return { state: 'deployed', deploymentId: id, gamePath: journal.gamePath, gameRoot: journal.gameRoot, snapshotPath, canRollback: true };
      } catch (error) {
        try { await restore(journal); } catch (rollbackError) { journal.state = 'recovery_required'; journal.recoveryCode = rollbackError.code || 'rollback_failed'; save(journal); }
        throw Object.assign(Error('Match deployment did not complete; inspect its recovery status.'), { code: error.code || 'deployment_failed', deploymentId: id, recoveryState: journal.state });
      }
    }),
    rollback: input => exclusive(async () => {
      checkPlatform(); if (input?.confirm !== true) fail('confirmation_required'); plans.clear();
      const journal = receipt(); if (!journal || journal.state === 'rolled_back') return { state: 'rolled_back', canRollback: false };
      try { return await restore(journal); }
      catch (error) { journal.state = 'recovery_required'; journal.recoveryCode = error.code || 'rollback_failed'; save(journal); throw error; }
    }),
  };
}
module.exports = { createWindowsMatchInstaller, validateWindowsMatchPayload };
