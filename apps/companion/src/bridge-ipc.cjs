'use strict';
// The only path source is the native picker callback owned by main.
function createBridgeDeployment({ setup, chooseGame, canMutate = () => true }) {
  let busy = false;
  async function exclusive(action, mutating = false) {
    if (busy || (mutating && !canMutate())) throw Error('正在执行其他本机操作，请完成后重试。');
    busy = true;
    try { return await action(); } finally { busy = false; }
  }
  function noArgs(args) { if (args.length) throw Error('此操作不接受路径或其他参数。'); }
  function register(handle) {
    handle('bridge-inspect', (...args) => { noArgs(args); return exclusive(() => setup.inspect()); });
    handle('bridge-plan', (...args) => {
      noArgs(args);
      return exclusive(async () => {
        const selected = await chooseGame();
        if (!selected) return { cancelled: true };
        return setup.plan(selected);
      }, true);
    });
    handle('bridge-deploy', (...args) => {
      const input = args[0];
      if (args.length !== 1 || !input || Object.getPrototypeOf(input) !== Object.prototype || Object.keys(input).some(key => !['planId', 'enable', 'allowShadowSigning', 'allowJit'].includes(key)) || typeof input.planId !== 'string' || !input.planId || input.planId.length > 512 || input.enable !== true || input.allowShadowSigning !== true || input.allowJit !== true) throw Error('请先查看有效计划，并分别确认私有副本、重新签名和 JIT 权限。');
      return exclusive(() => setup.deploy({ planId: input.planId, enable: true, allowShadowSigning: true, allowJit: true }), true);
    });
    handle('bridge-rollback', (...args) => { noArgs(args); return exclusive(() => setup.rollback(), true); });
  }
  return { register, get busy() { return busy; } };
}
module.exports = { createBridgeDeployment };
