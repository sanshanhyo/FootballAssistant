# 最小观测协议 v0.1 草案

Schema 使用 JSON Schema Draft 2020-12，协议版本为 `0.1.0`。它是初始化讨论用草案，尚未用于真实游戏传输，也未宣称与任何 FM 导出器兼容。

- [Schema](schemas/observation-envelope.v0.1.schema.json)
- [Runtime 合成例子](examples/runtime-observation.json)
- [Save 合成例子](examples/save-observation.json)

本版本只定义 `capability_report`，避免在实机证据缺失时杜撰球员字段或内存布局。后续观测种类须以显式 Schema 版本扩展。信封不接收任意命令字段，不提供修改游戏的通道；运行时安全仍需适配器自身保证，Schema 无法保证代码只读。

| 字段 | 语义 |
| --- | --- |
| `schema_version` / `event_id` | 显式协议版本与生产者生成的唯一 UUID，Data Core 用于幂等 |
| `captured_at` | 信封创建时间，RFC 3339；不能作为游戏事实的发生时间 |
| `observed_at` | 实际观测时间，未知为 `null` |
| `synthetic` | 合成数据标志；本仓库两个例子均为 `true` |
| `source` | runtime/save、适配器身份/版本、平台与新鲜度；save 必须携带 `save_metadata` |
| `game` | 目标产品、已核验构建、会话标识、游戏内时间；未读取字段为 `null` |
| `status` | `available`、`partial` 或 `unavailable`，不能由缺省空值暗示成功 |
| `payload.capabilities` | 各能力的 `available` / `not_probed` / `unsupported` / `unavailable` 状态 |

`source.freshness` 表示来源性质，runtime 为 `live` 或 `unknown`，save 固定 `snapshot`；不构成“永不过期”的承诺。Data Core 未来需结合观测时间、当前会话和用途计算新鲜度。`save_metadata` 中的快照引用/摘要/文件时间/解析配置均可未知；生产真实观测时必须有实际来源依据。文件时间不等于游戏内时间。

传输候选是仅本机回环 HTTP + JSON，入口鉴权与限流见架构文档。本阶段不运行服务器，不向项目或全局环境安装校验依赖；Schema 验证使用 `Draft202012Validator`，并开启 UUID 与 date-time 格式校验。两个例子表示“尚未探测”，没有伪装成已读取游戏的成功观测。


## MVP v0.2 实现

Data Core 现已接受 `0.1.0` 能力报告，并新增 [0.2 Schema](schemas/observation-envelope.v0.2.schema.json) 与[纯合成事实例子](examples/synthetic-fact-snapshot.json)。0.2 的 `fact_snapshot` 只定义 `{entity_kind,entity_id,field,value,unit?}` 标量事实，不预设 FM27 私有字段或内存结构。两版使用同一来源与状态约束，额外字段/命令、非有限数值和错误 UUID/date-time 被拒绝；单次最多 2000 条事实，HTTP 默认 128 KiB。

真实来源与合成数据始终显式分开。合成例不能验收真实 FM27；只收到 `unsupported` 能力报告也不能称为已读取球队/球员。当前 API 与运行方式见 [Backend API](../docs/backend-api.md)。v0.1 上文仍描述最初草案，实际后端/依赖安装范围以 MVP 文档为准。


## MVP v0.3 来源证据

[0.3 Schema](schemas/observation-envelope.v0.3.schema.json) 在事实上强制逐字段 `provenance`，记录当前来源、adapter、experimental、验证方法、证据引用、当前 snapshot SHA、初始 UI sample SHA 和范围。Data Core 校验来源/adapter/当前摘要与信封一致；exact UI 方法要求当前 SHA 与 UI sample SHA 相等，格式检查方法允许两者不同，不以初始 SHA 锁死新保存。

当前独立 summary adapter 仅在已核验 build / schema31 下输出 `save_summary.club_label` 和 `game_date`，其他未知格式拒绝。精确原样本已获 UI 核对，新同构建保存仅继承初始样本证据并完成格式检查；每字段保持 experimental，不能扩展成完整球队、阵容或实时状态。可重复导入入口见 [Backend API](../docs/backend-api.md)。


## Continuous ingestion without a new observation version

Runtime captures continue using 0.2 / 0.3 fact snapshots. `game.session_id`, `game.build`, source adapter and synthetic flag scope each stream. New captures have unique UUIDs and real capture times even when values are unchanged. Transport heartbeat is independent from capture age; UUID retransmissions are not new measurements.

Data Core emits attributable low-level UI/raw-field differences and exposes cursor polling, field provenance, metadata inventory and independent runtime coverage. These monitoring/catalog API records are separate from observation payloads; enumeration does not grant invocation permission or imply readable coverage. See [Backend API](../docs/backend-api.md).

## Runtime registry sidecars

Business-registry diagnostics are separate from UI fact snapshots and static metadata catalogs. The passive `/v1/interfaces/probes` contract preserves nullable counts, source/session/build/hash context, a stable enumeration epoch and last-reported status. Count-only probes contain no entries and cannot self-certify completion.

`/v1/interfaces/registries/batches` registers real uint32 IDs in bounded batches. Expected count, dictionary version and source identity are fixed per epoch; duplicate IDs are idempotent, and only an explicit terminal batch with all expected unique IDs may complete. Zero and unknown are distinct. Completion covers ID inventory only; unread metadata/value fields stay unknown and `field_values_known` remains false. Dynamic registry state does not replace the UI source or grant getter invocation permission. Frozen request/response shapes and pagination are in [Backend API](../docs/backend-api.md).

## Native observer diagnostics

The separate `/v1/interfaces/native-observers` DTO carries only pointer-free header/stat observations from the reviewed native shim. UInt64 values are decimal strings/null, count flags preserve unknown versus zero, keys counts are UInt64-element counts and payload counts are bytes. The target is the dispatch thunk at the reviewed setter-anchor + 12 bytes; receiving diagnostics does not verify the setter export or all native APIs.

At most 16 headers are projected with an explicit total. Absolute install addresses are private and rejected by the API. Session/build and metadata/assembly/game-plugin/observer hashes scope history. Last HTTP receipt and last approximate observed-header callback time are distinct. Payload values remain unknown, complete remains false, and no game/Agent/model action is exposed. Full frozen fields and query behavior are documented in [Backend API](../docs/backend-api.md).
