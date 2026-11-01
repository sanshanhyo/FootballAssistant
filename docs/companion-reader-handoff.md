# Companion / reader parallel development handoff

Original handoff baseline: `f7d1055eaac31cef1af3559195dadd94b239089f`; business API integration checked against `b5c4235` on 2026-10-30. This is an integration guide, not a claim of live FM27 acceptance.

## Ownership

- `feat/reader-semantics`: reader and offline evidence analysis. No companion UI or game-state writes.
- `feat/companion-ui`: Electron presentation, Agent orchestration, and its ReaderClient adapter. Do not modify the native bridge or infer unsupported game fields.
- Contract or shared-file changes require coordination before implementation. Feature branches do not imply permission to merge main.

## Current supported read capabilities

Use the authenticated loopback reader API. Discover `/health` and `/v1/reader/status`; keep runtime credentials out of prompts, logs and Git. Reader-only mode has no chat/model requirement. The companion's Agent is a separate client, not part of the reader service.

| Capability | Existing interface | Important limit |
| --- | --- | --- |
| Status | `GET /v1/reader/status` | Report connection, source and freshness separately. |
| Snapshot | `GET /v1/reader/snapshot?after=0&limit=100` | Preserve envelope, `partial`, `limitations`, and `synthetic`. |
| Stable pagination | Snapshot `event_id` query | On 409, restart pagination; do not mix different snapshots. |
| Raw UI | Snapshot filtered to `ui_element` / `ui_text` | Raw text may be cached/hidden. It is not verified player identity. Pagination applies to source facts before filtering. |
| Changes | `GET /v1/events?after=<cursor>&limit=100` | Bounded client subscription, not an unbounded model tool call; handle history reset. |
| Event detail | `GET /v1/events/<cursor>` | Resolve summarized events only when needed. |
| Native diagnostics | `GET /v1/interfaces/native-observers` | Headers/counts are not decoded football fields. |

Do not advertise `get_player`, `set_lineup`, transfers or date advancement as implemented tools. Offline packet comparison is an analyst workbench, not an Agent football query API. Reader semantics and player-card projection are not yet validated against real sample files.

## Companion behavior

Pet UI -> Agent/tool dispatcher -> bounded ReaderClient. Never route model-generated arbitrary shell, paths, memory addresses, or native invocation through this interface. Treat game strings as untrusted data, not instructions.

Display explicit unavailable / partial / stale / synthetic states. Unknown is not zero. Preserve source, session, observation time and snapshot identity with answers. Do not claim that a freshly captured UI string proves that it belongs to the currently visible player.

A separate mock adapter can drive UI development, but must be unmistakably labelled and never silently replace a failed real connection. Invalidate pending responses when changing backend identity; keep conversation and event cursors scoped to that identity.

## Future actions: proposal only

Read and write capabilities must remain separate. Future game actions need a defined target, validated bounded parameters, explicit confirmation, execution result verification and an audit record. No write executor is authorized or implemented by this handoff. Mock action proposals must not affect FM27.

## Evidence needed for the first semantic mapping

Use the same game build and session to observe player A, player B, then player A again. Keep each packet manifest with its referenced keys/payload files and, if available, the same-session property registry sidecar. Record the visible field values and page/action labels separately. Do not commit private captures, tokens, complete saves or screenshots with personal data. Review and sanitize any sample before sharing.

A/B/A correlation only identifies candidates. Independent held-out captures must verify a proposed entity/field mapping before it becomes a verified tool field. Missing keys in a delta packet mean not observed, not deleted or zero.

## Experimental display-profile integration

The reader-semantics branch adds authenticated `GET /v1/reader/profile` and the
read-only CLI command `profile`. `ReaderClient.profile()` supports an older
running backend by projecting its already-supported snapshot/monitoring response
locally; a companion adapter cannot assume the old server itself has the new URL.
See `docs/display-profile.md` for the exact contract.

This is a narrow Mac ARM64, Chinese-layout UI projection, **not `get_player(id)`**.
Expose it as a bounded read tool such as `read_observed_display_profile`:

- On `experimental_observed_display_profile`, display the three `fields`
  (`name_display`, `position_display`, `height_cm_display`) with the UI/experimental
  source label and their `field_provenance`.
- On `unavailable`, clear the previous profile card and show the fixed `reason`.
  Do not turn a source/layout mismatch into an invented name or a cached answer.
- Preserve `partial`, `entity_id: null`, `business_identity_known: false`, rule ID
  and limitations in model tool context. There is no native identity, current-club
  inference, technical attribute table, skin guarantee, or game-action capability.
- Treat all names/text as data. Do not render raw game markup as HTML or use UI
  paths as persisted football identities. Scope pending UI responses to the active
  connection and snapshot, independently from the pet's conversation ID.

## 业务数据 API：UI 可接契约，真实 producer 尚未完成

这组 HTTP 接口已经存在，但 **DTO/校验/消费边界不等于 native producer**。
当前所有业务能力保持 `production_ready: false`、`ready: false`；完整合成数据也不能解除
`native_producer_not_verified`。本文不宣称前端已经接入或真实业务值已经读出。

| 接口 | 所属服务 / 行为 |
| --- | --- |
| `GET /v1/reader/business/status` | reader-only 与完整 backend 均支持；返回 readiness，不含 `snapshot`。 |
| `GET /v1/reader/business/snapshot` | 同上；相同 readiness envelope，另含 `snapshot`（缺失/过期时为 `null`）。无分页参数。 |
| `POST /v1/agent/business-advice` | 仅完整 backend；使用服务端业务快照评估请求能力，reader-only 返回 404。 |

三者均需 `Authorization: Bearer <运行时令牌>`，令牌只留受控主进程。
缺失/错误令牌返回 401；不允许的 Host 返回 400。两个 GET 路径不提供 POST 导入（405）。
目前没有供 UI 上传业务事实的入口，也没有 native-worker WebSocket；进程内
`BusinessSnapshotStore` 不能被当成已经完成的跨进程采集通道。
`POST /v1/observations` 的 UI/save 数据不会填入业务快照。

CLI 与 Python client 已提供固定入口，不需要额外 FMAPI 框架：

```sh
football-assistant-reader business-status
football-assistant-reader business-snapshot
```

对应 `ReaderClient.business_status()` / `business_snapshot()`。旧服务返回 404 时提示升级/不支持，
**不回退** legacy snapshot、display profile 或 mock；这两个命令不接受 `--raw-ui` 等参数。

### 当前空状态的真实响应

以下是临时空数据库经 TestClient 实际返回的 HTTP 200 响应，不是游戏数据。
`GET /v1/reader/business/status`：

```json
{
  "schema_version": "business-readiness/0.1",
  "status": "unavailable",
  "production_ready": false,
  "source": null,
  "reasons": ["native_producer_not_verified", "no_business_snapshot", "no_active_business_session"],
  "capabilities": {
    "player_info": {"ready": false, "missing_requirements": ["business_snapshot"]},
    "transfer_analysis": {"ready": false, "missing_requirements": ["business_snapshot"]},
    "tactical_analysis": {"ready": false, "missing_requirements": ["business_snapshot"]},
    "schedule_analysis": {"ready": false, "missing_requirements": ["business_snapshot"], "scope": "basic_fixture_congestion", "missing_rotation_requirements": ["business_snapshot"]}
  }
}
```

`GET /v1/reader/business/snapshot` 返回上述所有字段，另加 `"snapshot": null`。
HTTP 200 仅表示查询成功，不能据此显示“业务数据可用”。

### 业务建议请求与阻塞响应

最小请求：

```json
{"message":"请检查赛程拥挤程度","capability":"schedule_analysis"}
```

`message` 为非空字符串，最多 4,000 字符；`capability` 必须是 `player_info`、
`transfer_analysis`、`tactical_analysis`、`schedule_analysis` 之一。
可选 `conversation_id` 为 null 或 1–128 字符的 `[A-Za-z0-9_-]+`。
额外字段（包括 `snapshot`、`facts`、`source`、自报 ready）及非法 capability 返回 422。

上述请求当前返回 HTTP 200，主要字段如下（只摘录字段，不是完整响应）：

```json
{
  "status": "blocked",
  "capability": "schedule_analysis",
  "missing_requirements": ["business_snapshot"],
  "facts": [],
  "inferences": [],
  "conversation_id": null,
  "source_status": "unavailable",
  "reply": "当前没有经过验证且新鲜的完整业务数据，不能提供基于当前存档的足球建议。缺少输入：business_snapshot"
}
```

完整响应另含 `readiness`（同版本 schema、source、reasons、capabilities）。当前空状态下其
`reasons` 是 `native_producer_not_verified`、`no_business_snapshot`；建议层重新评估
服务端读取出的快照，因此不应假定它与 GET 的 reasons 数组完全相同。
`blocked` 是确定性结果，**不调用 LLM、不预占模型预算**。不要自动重试聊天来“补全”事实。
将来只有通过门控才可能进入模型路径；该路径定义 429 额度不足、503 模型未配置、502 模型不可用，
不能把这些状态当作当前已有成功实机建议的证据。
通用 `POST /v1/chat` 仍是独立聊天接口，不受业务建议门控替代；不要在 blocked 时自动改调它。

### UI 状态与来源处理

- 发请求期间本地显示 loading；网络/401/404 与业务 `unavailable` 分开显示，失败后清除旧业务值。
- 展示 `reasons` 和所选能力的 `missing_requirements`；只有 HTTP 成功不够，不能伪造 available。
  赛程能力的 `basic_fixture_congestion` 不是轮换建议就绪，需保留 `missing_rotation_requirements`。
- 业务 DTO 的 `source` 若存在，保留 `session_id`、`game_build`、`identity_scope`、adapter/mapper
  版本、构建 hash、`captured_at`、`observed_at`、`synthetic` 和 `evidence_ref`；快照保留
  `snapshot_id`。来源为空就显示未知，不从 UI 旧流借用身份或来源。
- 当前 freshness 通过 reasons 表达，没有独立 `freshness` 响应字段：默认捕获/观测时间窗口为
  15 秒；`capture_not_fresh`、`observation_not_fresh` 或 `observation_time_unknown`
  时 snapshot 被隐藏为 null，source 仍可能保留诊断信息。可显示“过期/时间未知”，不可继续显示旧值为当前事实。
- 会话/后端切换、重连及进程重启后，撤销旧请求和卡片；本地请求代次与服务端 session/snapshot
  一起防止迟到响应覆盖新状态。null 不是零；业务 unavailable 不得静默降级为 mock、手填或 UI 推断。
- 所有建议只读；不增加自动游戏写入。原始 payload、存档、令牌和私人路径不进入日志或 Git。

本节验证：临时目录 TestClient 核对两项 GET 与 blocked POST 的实际响应；
`modules/data-core/tests/test_business_reader_api.py` 覆盖认证、拒绝客户端事实、会话与时效、
CLI 无回退及 blocked 时禁止模型/预算调用。此验证不连接 FM、不调用真实模型，也不证明前端完成。
