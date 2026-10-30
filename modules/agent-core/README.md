# Agent Core MVP

已有 Python / PydanticAI 真实模型调用模块，使用用户显式配置的 OpenAI 兼容 Chat Completions 服务，不读取其他项目密钥。人格为独立基础 system prompt，事实来自 Data Core，缺数据时不能虚构游戏情况；无模型配置返回 503，连接/响应失败返回 502，没有固定回答伪装模型成功。

`companion.sqlite` 独占保存成功对话的近期历史，以及用户显式创建的基础记忆。相同 conversation_id 可在重启后恢复近期 20 条消息；记忆支持添加、查看、删除，最近 30 条作为上下文。这是简单持久记忆，没有 RAG、自动巩固、关系演进、多 Agent 或成长系统。

本地 provider fixture 验证 SDK 通路和历史恢复；2026-10-30 已获用户有限额度授权，用 OpenCode Go 的 mimo-v2.6-flash 完成 2 次授权请求，其中第 2 次经实际桌宠窗口返回真实存档摘要的标签与日期，并完成本机 TTS。这只证明两字段窄数据通路，不证明完整球队/球员读取。当前验证配置使用 160 输出 token、关闭思考、零自动重试，SQLite 持久限制总请求次数为 2，当前 2 次额度已用完，后续真实模型请求需要新的用户授权。详见 [API](../../docs/backend-api.md)。
