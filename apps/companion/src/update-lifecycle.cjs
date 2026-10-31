'use strict';
// A fail-closed idle coordinator. It never kills the game and treats unknown
// activity/process inspection as busy. No renderer can request install directly.
function createUpdateLifecycle({ installedUpdater, inspectActivity, intervalMs = 15000, onError = () => {} }) {
  let timer = null, pending = null, stopped = false, reserved = false;
  async function check() {
    if (pending) return pending;
    if (stopped || !['ready_for_safe_exit', 'deferred'].includes(installedUpdater.status.state)) return installedUpdater.status;
    pending = (async () => {
      const activity = await inspectActivity();
      if (stopped || activity !== 'idle') return installedUpdater.status;
      reserved = true;
      try { return await installedUpdater.applyOnSafeExit({ normalQuit: true, sessionEnding: false }); }
      finally { reserved = false; }
    })().catch(error => { onError(error); return installedUpdater.status; }).finally(() => { pending = null; });
    return pending;
  }
  return {
    get reserved() { return reserved; }, check,
    start() { if (timer) return; stopped = false; timer = setInterval(() => { void check(); }, intervalMs); timer.unref?.(); },
    stop() { stopped = true; reserved = false; clearInterval(timer); timer = null; }
  };
}
module.exports = { createUpdateLifecycle };
