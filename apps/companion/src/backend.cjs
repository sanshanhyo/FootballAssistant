'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

function defaultRuntimeFile(env = process.env, argv = []) {
  const index = argv.indexOf('--runtime-file');
  if (index !== -1 && (!argv[index + 1] || argv[index + 1].startsWith('--') || argv.indexOf('--runtime-file', index + 1) !== -1)) {
    throw new Error('--runtime-file 需要一个明确的连接文件路径。');
  }
  const file = env.FOOTBALL_ASSISTANT_RUNTIME_FILE || (index !== -1 ? argv[index + 1] : '') || path.join(env.FOOTBALL_ASSISTANT_DATA_DIR || path.resolve(__dirname, '../../..', 'local-data'), 'runtime.json');
  return path.resolve(file.startsWith('~/') ? path.join(os.homedir(), file.slice(2)) : file);
}

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
  const post = ['/v1/chat', '/v1/agent/business-advice', '/v1/agent/ui-advice'].includes(endpoint);
  const get = ['/v1/reader/ui-change-preview', '/v1/reader/schedule', '/v1/reader/tactics', '/v1/reader/current-page-attributes', '/v1/status', '/v1/companion/state', '/v1/monitoring', '/v1/reader/business/status', '/v1/reader/business/snapshot'].includes(endpoint) || /^\/v1\/events\?after=\d{1,16}&limit=100$/.test(endpoint);
  if ((!post && !get) || (post !== (body !== undefined))) throw new Error('不支持的服务接口或请求方法。');
  options.signal?.throwIfAborted();
  let runtime;
  try { runtime = await readRuntime(runtimeFile); }
  catch (error) {
    if (error.code === 'ENOENT') throw new Error('找不到本机连接文件；桌宠启动不代表 backend 已启动。请使用 scripts/run_mvp.py 启动，或设置 FOOTBALL_ASSISTANT_RUNTIME_FILE / --runtime-file 指向 backend 的 runtime.json；不会回退到模拟。');
    throw error;
  }
  let response; let responseText;
  const timeout = AbortSignal.timeout(options.timeoutMs ?? (post ? 120_000 : 5_000));
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    response = await (options.fetch || fetch)(runtime.baseUrl + endpoint, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${runtime.token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      redirect: 'error',
    });
    responseText = await response.text();
  } catch (error) {
    if (options.signal?.aborted) throw Object.assign(new Error('请求已取消。'), { name: 'AbortError', code: 'cancelled' });
    if (error.name === 'TimeoutError' || error.name === 'AbortError') throw new Error('服务响应超时，请稍后重试。');
    throw new Error('无法连接本机服务，请确认它正在运行。');
  }
  options.signal?.throwIfAborted();
  const current = await readRuntime(runtimeFile);
  if (current.baseUrl !== runtime.baseUrl || current.token !== runtime.token) throw Object.assign(new Error('服务连接已变化，请重新连接后重试。'), { code: 'connection_changed' });
  const text = responseText;
  if (response.status === 401) throw Object.assign(new Error('本机服务认证失败，请重新启动服务并检查连接文件。'), { code: 'unauthorized' });
  if (response.status === 404) {
    const message = ['/v1/agent/business-advice', '/v1/agent/ui-advice'].includes(endpoint)
      ? '当前服务不支持业务建议接口；reader-only 服务不能提供建议，请启动完整 backend。'
      : endpoint.startsWith('/v1/reader/business/')
        ? '当前服务版本不支持业务数据读取接口，请升级 backend。'
        : '当前服务不支持此接口，请检查服务版本或启动完整 backend。';
    throw Object.assign(new Error(message), { code: 'unsupported' });
  }
  if (text.length > 1_048_576) throw new Error('服务回复过长。');
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('服务返回了无效数据。'); }
  if (!response.ok) {
    const message = data?.detail?.message;
    throw new Error(typeof message === 'string' ? message.slice(0, 400) : `服务请求失败（${response.status}）。`);
  }
  return data;
}

module.exports = { validateRuntime, readRuntime, request, defaultRuntimeFile };
