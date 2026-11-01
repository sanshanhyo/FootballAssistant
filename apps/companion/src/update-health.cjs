'use strict';
const rendererHealthScript = `(async () => {
  if (document.readyState !== 'complete' || !document.getElementById('pet') || typeof window.companion?.getState !== 'function') return false;
  const reply = await window.companion.getState();
  return reply?.ok === true && typeof reply.value?.sessionId === 'string' && Number.isSafeInteger(reply.value?.epoch);
})()`;
async function rendererHealthy(webContents, timeoutMs = 5000) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => webContents.executeJavaScript(rendererHealthScript)).then(value => value === true),
      new Promise(resolve => { timer = setTimeout(() => resolve(false), timeoutMs); }),
    ]);
  } catch { return false; }
  finally { clearTimeout(timer); }
}
module.exports = { rendererHealthy, rendererHealthScript };
