(function (root) {
  'use strict';
  function bind({ root: container, api, onError = () => {} }) {
    let value = null, plan = null, busy = false, closed = false, generation = 0, timer;
    const make = (tag, text, parent = container) => { const e = document.createElement(tag); if (text) e.textContent = text; parent.append(e); return e; };
    make('h2', '比赛读取组件'); const status = make('div'); status.setAttribute('role', 'status');
    const progress = make('div'), game = make('div');
    const details = make('details'); make('summary', '查看部署文件与冲突', details); const files = make('pre', '', details);
    const checkbox = text => { const label = make('label'); label.className = 'switch-row'; make('span', text, label); const box = make('input', '', label); box.type = 'checkbox'; return box; };
    const download = checkbox('同意首次启动联网下载 Unity 库并在本机生成互操作文件');
    const migration = checkbox('同意备份列出的旧加载器后替换；不修改其他 Mod');
    const confirmation = checkbox('已退出游戏，并确认上述部署文件');
    const rollbackConsent = checkbox('确认回滚本次部署并恢复备份（须退出游戏）');
    const actions = make('div'); actions.className = 'row-actions';
    const select = make('button','选择游戏',actions), inspect = make('button','检查部署',actions), prepare = make('button','生成部署计划',actions), deploy = make('button','确认部署',actions), connect = make('button','连接后台',actions), verify = make('button','检查加载',actions), rollback = make('button','回滚部署',actions);
    const labels = { deployed:'组件已部署，请启动游戏后检查加载', deployed_unconfigured:'组件已部署，尚未连接后台', disabled:'比赛组件未部署', not_installed:'比赛组件未部署', absent:'比赛组件未部署', planned:'请检查部署文件并明确确认', conflict:'发现加载器或 Mod 冲突，未修改游戏', modified:'部署文件已变更，不能自动覆盖', waiting_game:'组件已部署，等待启动游戏', loading:'首次加载中，最多检查 180 秒；不会停止游戏', loading_timeout:'180 秒内尚未完成加载；游戏仍运行，可继续等待后重试', loaded_waiting_match:'组件已加载，等待真实比赛数据', live:'已收到当前进程的新鲜比赛数据', hook_timeout:'比赛挂钩等待超时，请检查日志后重新启动游戏', plugin_stopped:'比赛组件已停止', backend_unavailable:'后台未连接', game_state_unknown:'无法确认游戏进程状态', deployment_error:'部署状态检查失败', rolled_back:'已回滚比赛组件', rollback_complete:'已回滚比赛组件' };
    function buttons() {
      for (const e of [select,inspect,prepare,connect,verify,rollback,deploy,download,migration,confirmation,rollbackConsent]) e.disabled = busy;
      deploy.disabled = busy || !plan || plan.canDeploy === false && !plan.needsMigrationConsent || !confirmation.checked || !download.checked || plan.needsMigrationConsent && !migration.checked;
      connect.hidden = !value?.canConnect; verify.disabled = busy || !value?.enabled;
      rollback.disabled = busy || !value?.canRollback || !rollbackConsent.checked;
    }
    function render(next) {
      value = next; container.hidden = next.supported === false; if (container.hidden) return;
      status.textContent = labels[next.state] || next.message || next.state || '状态未确认';
      if (next.restartRequired) status.textContent += ' · 请重启外部后台';
      game.textContent = next.gamePath || next.gameRoot || '';
      const log = next.loaderProgress;
      progress.textContent = log ? `${({generating_interop:'近期日志：包含互操作生成记录',downloading_unity:'近期日志：包含 Unity 库下载记录',loader_started:'近期日志：有加载器输出'})[log.phase]}${log.errorRecorded ? '；日志中出现错误，请检查' : ''} · ${log.updatedAt}` : '';
      if (next.planId) { plan = next; confirmation.checked = false; download.checked = false; migration.checked = false; }
      files.textContent = plan ? JSON.stringify({operations:plan.operations,conflicts:plan.conflicts,migrationFiles:plan.migrationFiles},null,2) : '';
      details.hidden = !plan; if (next.error) onError(next.error); buttons();
    }
    async function run(action, poll = false) {
      if (busy || closed) return; clearTimeout(timer); busy = true; const token = ++generation; buttons(); onError('');
      try { const result = await action(); if (closed || token !== generation) return; if (!result?.ok) throw Error(result?.error || '比赛组件操作失败'); if (!result.value?.cancelled) render(result.value);
        if (poll && result.value?.state === 'loading') timer = setTimeout(() => run(() => api.verifyMatch(), true), 2000);
      } catch (error) { if (!closed && token === generation) { onError(error.message); status.textContent = '操作未完成；游戏未被自动启动或停止'; } }
      finally { if (!closed && token === generation) { busy = false; buttons(); } }
    }
    for (const box of [download,migration,confirmation,rollbackConsent]) box.addEventListener('change',buttons);
    select.addEventListener('click',()=>{plan=null;return run(()=>api.selectMatchGame());});
    inspect.addEventListener('click',()=>run(()=>api.inspectMatchDeployment()));
    prepare.addEventListener('click',()=>{plan=null;return run(()=>api.planMatchDeployment());});
    deploy.addEventListener('click',()=>run(async()=>{const input={planId:plan?.planId,confirm:confirmation.checked,migrateLoader:migration.checked,allowFirstRunDownload:download.checked};plan=null;return api.deployMatch(input);}));
    connect.addEventListener('click',()=>run(()=>api.connectMatch()));
    verify.addEventListener('click',()=>run(()=>api.retryMatch(),true));
    rollback.addEventListener('click',()=>run(async()=>{plan=null;return api.rollbackMatch({confirm:rollbackConsent.checked});}));
    const ready = run(()=>api.inspectMatchDeployment());
    return {ready,dispose(){closed=true;generation++;clearTimeout(timer);}};
  }
  if (typeof module === 'object' && module.exports) module.exports={bind}; else root.FootballMatchDeployment={bind};
})(typeof window === 'object' ? window : globalThis);
