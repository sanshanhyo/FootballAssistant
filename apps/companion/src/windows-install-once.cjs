'use strict';
// Installer-only orchestration. No network, game launch, backend, discovery, or user-data override.
const fs = require('node:fs/promises');
const path = require('node:path');
const { DEFAULT_SETTINGS, validateSettings, detectGame } = require('./bootstrap.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
const { inspectGame, validateReaderPayload } = require('./windows-reader-setup.cjs');
const { createWindowsMatchInstaller, validateWindowsMatchPayload } = require('./windows-match-installer.cjs');
const fail = (code, message) => { throw Object.assign(Error(message), { installCode: code }); };
function installErrorMessage(error) {
  const messages = {
    EACCES: '没有文件读写权限。请检查游戏目录和应用数据目录权限后重试；不会绕过权限。',
    EPERM: '文件不可写或正被占用。请退出 FM 和桌宠，检查目录权限后重试。',
    EBUSY: '文件正被占用，请退出 FM 和桌宠后重试。',
    ENOENT: '所选游戏路径或安装资源不存在，请检查 FM 路径，并使用完整安装包重新安装。',
    game_running: 'FM 正在运行，已停止写入。请先保存游戏并退出 FM。',
    game_state_unknown: '无法确认 FM 已退出，已停止写入；请退出游戏后重试。',
    unsupported_game_binary: '当前 FM 版本不受支持，未继续部署。',
    unsupported_unity_binary: '当前 UnityPlayer.dll 与支持的游戏版本不匹配，未继续部署。',
    existing_unity_libraries: '检测到已有的 Unity 基库，需要人工检查；不会使用或删除这些文件。',
    runtime_policy_invalid: '安装包的离线运行配置不完整或不匹配；不会联网下载依赖。',
    payload_identity_invalid: '内置组件版本或身份不匹配，请使用完整安装包重新安装。',
    payload_integrity_failed: '内置组件校验失败，请使用完整安装包重新安装。',
    payload_manifest_invalid: '内置组件清单无效，未继续部署。',
    shared_config_invalid: '无法安全解析已有 BepInEx 配置，已保留原文件；请人工检查后重试。',
    existing_deployment: '已有部署被修改或尚未完成恢复，请先检查原部署，避免覆盖其它修改。',
    loader_conflict: '发现不兼容加载器，不能覆盖其它 Mod 的组件。',
    confirmation_required: '部署确认已过期，请重新运行安装程序。',
    plan_changed: '文件在确认后发生变化，已停止部署，请重新运行安装程序。',
    recovery_required: '上次部署尚未恢复完成，请保留备份并先恢复。',
    rollback_file_modified: '部署后的文件已被修改，恢复已停止，不会覆盖这些修改。',
    backup_integrity_failed: '备份校验失败，恢复已停止，不会用损坏备份覆盖文件。',
    unsafe_file: '检测到链接或不安全文件，为保护原文件已停止操作。',
    unsafe_directory: '检测到链接或不安全目录，为保护原文件已停止操作。',
  };
  if (messages[error.code]) return messages[error.code];
  if (/State changed/.test(error.message || '')) return '设置已被其它操作修改；本次不会覆盖新设置，请关闭其它实例后重试。';
  return /[\u3400-\u9fff]/.test(error.message || '') ? error.message : '安装未完成，请保留此错误信息以便检查：' + (error.message || error.code || '未知错误');
}
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
    if (platform !== 'win32') fail(4, '此读取组件只能在 Windows 上安装。');
    if (!path.isAbsolute(userData) || !path.isAbsolute(resourcesPath)) fail(4, '应用目录或资源目录无效，请重新运行完整安装程序。');
    await fs.mkdir(userData, { recursive: true, mode: 0o700 });
    userData = await fs.realpath(userData);
    settingsFile = path.join(userData, 'settings.json');
    before = await readStateFile(settingsFile, 16384);
    if (before.bytes && (await fs.lstat(settingsFile)).nlink !== 1) fail(4, '设置文件是链接文件，为保护原配置，已停止安装。');
    const settings = before.bytes ? validateSettings(JSON.parse(before.bytes.toString('utf8'))) : { ...DEFAULT_SETTINGS };
    gamePath = gamePath || settings.windowsMatchGamePath || settings.windowsReaderGamePath || '';
    if (!gamePath) fail(3, '尚未保存 FM 路径，请在安装程序中选择包含 fm.exe 的游戏目录。');
    if (!path.isAbsolute(gamePath) || /[\0\r\n]/.test(gamePath)) fail(4, 'FM 路径无效，请选择完整的游戏目录或 fm.exe 路径。');
    if ((await fs.lstat(gamePath)).isDirectory()) gamePath = path.join(gamePath, 'fm.exe');
    gamePath = (await inspectGame(gamePath)).gamePath;
    await validateReaderPayload(resourcesPath); // Hash all bundled producer files; never run the producer here.
    const payload = validateWindowsMatchPayload(path.join(resourcesPath, 'match-windows-x64'));
    const policy = payload.manifest.runtimePolicy;
    if (!policy || policy.interopMode !== 'local-metadata-no-unstrip' || policy.unityBaseLibrariesSource !== '' ||
        policy.unityLogListening !== false || policy.updateInteropAssemblies !== true || policy.runtimeDependencyDownloads !== false)
      fail(4, '安装包缺少已校验的离线运行配置，不能继续安装；不会联网补下载。');
    installer = createWindowsMatchInstaller({ userData, resourcesPath, platform, probeGame });
    // Exceptions require explicit native confirmation, never implicit migration or process termination.
    for (;;) {
      const value = await probeGame(path.dirname(gamePath));
      const running = typeof value === 'boolean' ? value : value?.running;
      if (running === false) break;
      if (running !== true) fail(5, '无法确认 FM 已退出，本次未修改游戏文件。请退出 FM 后重试。');
      if (silent) fail(3, '静默安装不能等待交互操作，请先退出 FM 再重新安装。');
      if (!await confirmException({ type: 'game_running', gamePath })) fail(2, '已取消安装；请先保存游戏并退出 FM。');
    }
    phase = 'deployment';
    const plan = await installer.plan(gamePath);
    if (!plan.canDeploy) fail(5, '发现不兼容加载器或被修改的文件，需要人工检查；本次未替换这些文件。');
    let migrateLoader = false;
    if (plan.needsMigrationConsent) {
      if (silent) fail(3, '发现旧加载器，备份并替换前需要明确确认；请使用非静默安装。');
      migrateLoader = await confirmException({ type: 'loader_migration', gamePath, files: plan.migrationFiles });
      if (!migrateLoader) fail(2, '已取消旧加载器迁移，未继续部署。');
    }
    let confirmSharedConfig = false;
    if (plan.needsSharedConfigConsent) {
      if (silent) fail(3, '已有 BepInEx 共享配置需要确认三项受限修改；请使用非静默安装。');
      confirmSharedConfig = await confirmException({ type: 'shared_config', gamePath, fields: plan.sharedConfigChanges });
      if (!confirmSharedConfig) fail(2, '已取消修改共享加载器配置，未继续部署。');
    }
    deployed = await installer.deploy({ planId: plan.planId, confirmationToken: plan.confirmationToken, confirm: true, migrateLoader, confirmSharedConfig });
    phase = 'settings';
    const next = validateSettings({ ...settings, windowsReaderEnabled: true, windowsReaderGamePath: gamePath,
      windowsMatchEnabled: true, windowsMatchGamePath: gamePath });
    savedRevision = await writeStateFile(settingsFile, JSON.stringify(next, null, 2) + '\n', before.revision);
    const success = result(0, '赛外和比赛读取组件已安装并启用，无需再到设置中安装。请正常启动 FM；首次在本机生成互操作文件可能需要一些时间。');
    await finalize(success);
    return success;
  } catch (error) {
    let recovery = error.recoveryState === 'recovery_required';
    // Only undo the deployment created by this invocation; prior receipt is restored by installer rollback.
    if (deployed) {
      try {
        const current = await installer.inspect(gamePath);
        if (current.deploymentId !== deployed.deploymentId) throw Error('部署记录已被其它操作修改，不能回滚不属于本次安装的内容。');
        await installer.rollback({ confirm: true });
      } catch { recovery = true; }
    }
    if (savedRevision !== undefined) {
      try {
        if (before.bytes) await writeStateFile(settingsFile, before.bytes, savedRevision);
        else {
          if ((await readStateFile(settingsFile)).revision !== savedRevision) throw Error('设置已被其它操作修改，不能覆盖新配置。');
          await fs.unlink(settingsFile);
        }
      } catch { recovery = true; }
    }
    return result(recovery ? 6 : error.installCode || (phase === 'validation' ? 4 : phase === 'settings' ? 7 : 5),
      recovery ? '安装未完成，需要恢复。请先退出 FM 并保留备份，不要手动删除部署记录；安装程序没有强制结束游戏。原因：' + installErrorMessage(error) : installErrorMessage(error));
  }
}
module.exports = { installWindowsReaders, installErrorMessage };
