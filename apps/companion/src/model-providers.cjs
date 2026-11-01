'use strict';
// Main-process only. Fixed destinations; never follow a provider redirect with a key.
const PROVIDERS = Object.freeze([
  { id: 'opencode-go', name: 'OpenCode Go', baseUrl: 'https://opencode.ai/inference/go/openai/v1', modelsUrl: 'https://opencode.ai/inference/go/v1/models' },
  { id: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'commandcode-goat', name: 'Command Code GOAT', baseUrl: 'https://api.commandcode.ai/provider/v1' },
  { id: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { id: 'openrouter', name: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'groq', name: 'Groq', baseUrl: 'https://api.groq.com/openai/v1' },
  { id: 'mistral', name: 'Mistral AI', baseUrl: 'https://api.mistral.ai/v1' },
  { id: 'openai-compatible', name: '自定义 OpenAI 兼容服务', baseUrl: '', custom: true },
].map(Object.freeze));
function destination(provider, baseUrl = '') {
  const preset = PROVIDERS.find(item => item.id === provider);
  if (!preset || preset.disabled) throw Error('服务商暂不可用，请确认官方服务信息。');
  if (typeof baseUrl !== 'string' || baseUrl.length > 2048) throw Error('服务地址无效。');
  const supplied = baseUrl.trim().replace(/\/+$/, '');
  if (!preset.custom && supplied && supplied !== preset.baseUrl) throw Error('预设服务商地址不可修改。');
  const base = preset.custom ? supplied : preset.baseUrl;
  let url; try { url = new URL(base); } catch { throw Error('请输入有效的 HTTPS 服务地址。'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || /[\x00-\x20\x7f]/.test(base)) throw Error('服务地址须为不含账号和查询参数的 HTTPS URL。');
  return { provider, baseUrl: base, modelsUrl: preset.modelsUrl || `${base}/models` };
}
function normalizeModels(body, { requireChatEndpoint = false } = {}) {
  if (!body || !Array.isArray(body.data) || body.data.length > 10000) throw Error('服务商返回的模型列表格式不受支持。');
  const models = new Map();
  for (const item of body.data) {
    // Command Code routes Claude and decision models to different protocols.
    if (requireChatEndpoint && (!Array.isArray(item?.supported_endpoints) || !item.supported_endpoints.some(route => route === '/v1/chat/completions' || route === '/provider/v1/chat/completions' || route === '/chat/completions'))) continue;
    const id = typeof item?.id === 'string' ? item.id.trim() : '';
    if (!id || id.length > 512 || /[\x00-\x20\x7f]/.test(id)) continue;
    const name = typeof item.name === 'string' && item.name.length <= 512 && !/[\x00-\x1f\x7f]/.test(item.name) ? item.name : id;
    models.set(id, { id, name });
  }
  return [...models.values()].sort((a, b) => a.id.localeCompare(b.id));
}
function createModelDiscovery({ credentials, fetchImpl = globalThis.fetch, timeoutMs = 15000 }) {
  let active = null;
  function cancel() { if (active) active.abort(); active = null; }
  async function list(input) {
    cancel();
    if (!input || Object.getPrototypeOf(input) !== Object.prototype || Object.keys(input).some(key => !['provider', 'baseUrl', 'apiKey'].includes(key))) throw Error('模型查询参数无效。');
    const target = destination(input.provider, input.baseUrl);
    if (input.apiKey !== undefined && (typeof input.apiKey !== 'string' || input.apiKey.length > 8192 || /[\x00-\x20\x7f]/.test(input.apiKey))) throw Error('API Key 格式无效。');
    const saved = credentials.getPublicConfig();
    // An omitted key is reusable only for the exact saved provider AND destination.
    const key = input.apiKey !== undefined ? input.apiKey : saved.provider === target.provider && saved.baseUrl === target.baseUrl ? credentials.backendEnv().FOOTBALL_ASSISTANT_API_KEY : '';
    const controller = new AbortController(); active = controller;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(target.modelsUrl, { method: 'GET', redirect: 'error', signal: controller.signal, headers: { Accept: 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) } });
      if (!response.ok) {
        if ([404, 405, 501].includes(response.status)) throw Error('服务商不支持读取模型列表。');
        if ([401, 403].includes(response.status)) throw Error('无法读取模型，请检查 API Key 与访问权限。');
        if (response.status === 429) throw Error('模型列表请求过于频繁，请稍后重试。');
        throw Error('服务商暂时无法提供模型列表。');
      }
      const reader = response.body.getReader(); let size = 0; const chunks = [];
      while (true) { const { value, done } = await reader.read(); if (done) break; size += value.byteLength; if (size > 4 * 1024 * 1024) { await reader.cancel(); throw Error('模型列表超过大小限制。'); } chunks.push(Buffer.from(value)); }
      const models = normalizeModels(JSON.parse(Buffer.concat(chunks).toString('utf8')), { requireChatEndpoint: target.provider === 'commandcode-goat' });
      if (controller.signal.aborted || active !== controller) throw Error('模型查询已取消。');
      return { provider: target.provider, baseUrl: target.baseUrl, models };
    } catch (error) {
      if (controller.signal.aborted) throw Error('模型查询已取消或超时，请重试。');
      // Never surface transport exceptions or provider bodies (either can echo credentials).
      if (/^(服务商|无法读取模型|模型列表|模型查询)/.test(error.message)) throw error;
      throw Error('无法连接服务商或解析模型列表。');
    } finally { clearTimeout(timer); if (active === controller) active = null; }
  }
  return { list, cancel, providers: () => ({ providers: PROVIDERS.map(({ modelsUrl, ...provider }) => ({ ...provider })) }) };
}
module.exports = { PROVIDERS, destination, normalizeModels, createModelDiscovery };
