'use strict';
const fs = require('node:fs/promises');

function validateRuntime(value) {
  if (!value || typeof value.token !== 'string' || value.token.length < 16) {
    throw new Error('连接文件缺少有效访问令牌，请重新启动服务。');
  }
  const url = new URL(value.base_url);
  if (url.protocol !== 'http:' || !['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('只允许连接本机 FootballAssistant 服务。');
  }
  return { baseUrl: url.origin, token: value.token };
}

async function readRuntime(file) {
  const stat = await fs.stat(file);
  if (!stat.isFile() || stat.size > 16_384) throw new Error('连接文件格式无效。');
  return validateRuntime(JSON.parse(await fs.readFile(file, 'utf8')));
}

async function request(runtimeFile, endpoint, body, options = {}) {
  if (!['/v1/status', '/v1/chat', '/v1/companion/state', '/v1/monitoring'].includes(endpoint) &&
      !/^\/v1\/events\?after=\d{1,16}&limit=100$/.test(endpoint)) {
    throw new Error('不支持的服务接口。');
  }
  let runtime;
  try { runtime = await readRuntime(runtimeFile); }
  catch (error) {
    if (error.code === 'ENOENT') throw new Error('服务尚未启动，或尚未选择连接文件。');
    throw error;
  }
  let response;
  try {
    response = await (options.fetch || fetch)(runtime.baseUrl + endpoint, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${runtime.token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(endpoint === '/v1/chat' ? 120_000 : 5_000),
      redirect: 'error',
    });
  } catch (error) {
    if (error.name === 'TimeoutError' || error.name === 'AbortError') throw new Error('服务响应超时，请稍后重试。');
    throw new Error('无法连接本机服务，请确认它正在运行。');
  }
  const text = await response.text();
  if (text.length > 1_048_576) throw new Error('服务回复过长。');
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('服务返回了无效数据。'); }
  if (!response.ok) {
    const message = data?.detail?.message;
    throw new Error(typeof message === 'string' ? message.slice(0, 400) : `服务请求失败（${response.status}）。`);
  }
  return data;
}

module.exports = { validateRuntime, readRuntime, request };
