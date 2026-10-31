# Backend MVP API

一个 Python FastAPI 进程，Data Core、Agent Core、Save Adapter 仍保持逻辑与存储边界。默认仅监听 `127.0.0.1:17827`，不操作游戏进程、原存档或 Steam。TTS 由桌面调用本机能力完成。

## 安装与启动

在项目根目录执行：

```sh
uv run --extra agent football-assistant-backend
```

已有 uv 时该命令按 `uv.lock` 同步项目 `.venv` 并启动。首次可显式运行 `uv sync --frozen --python 3.14 --extra agent`，Windows 在 PowerShell 同样使用 uv；开发版本要求 Python ≥3.12，本机与 CI 计划使用 3.14。CI 配置存在不代表 Windows 实测已通过。

把 `.env.example` 复制为本机 `.env`，填入用户选择的现有 OpenAI 兼容服务的 `FOOTBALL_ASSISTANT_BASE_URL`、`FOOTBALL_ASSISTANT_MODEL`、`FOOTBALL_ASSISTANT_API_KEY`。本项目不会读取其他项目的密钥。不配置模型也可运行健康、数据与记忆接口，聊天明确返回 503。2026-10-30 已按用户有限额度授权，用 OpenCode Go / mimo-v2.6-flash 完成 2 次真实请求，其中第 2 次经打包桌宠窗口，基于实际存档的两个实验性摘要字段回答并完成本机 TTS；当前授权 2 次预算已用完。这不代表完整球队/球员读取。

可选变量包括 `FOOTBALL_ASSISTANT_PORT`、`FOOTBALL_ASSISTANT_DATA_DIR`、`FOOTBALL_ASSISTANT_RUNTIME_FILE`、`FOOTBALL_ASSISTANT_MODEL_TIMEOUT` 与 `FOOTBALL_ASSISTANT_TOKEN`。路径由 pathlib 处理，允许空格与平台分隔符，不拼接 shell 命令。

## 本机令牌与状态

`FOOTBALL_ASSISTANT_TOKEN` 缺失时每次启动生成随机令牌。实际地址与令牌仅写入受限本机 `local-data/runtime.json`，形状如下；示意值不是可用令牌。

```json
{"base_url":"http://127.0.0.1:17827","token":"<per-run-secret>","pid":1234,"started_at":"2026-10-30T00:00:00+00:00"}
```

macOS/Unix 目录权限 0700、文件 0600；Windows 应放在当前用户独享目录，POSIX mode 不替代 Windows ACL。文件不应上传、展示或写入日志。桌面主进程可同用户读取，不把 token 暴露到 renderer。正常退出清理本次 runtime 文件，SQLite 持续保存。后端禁用访问日志与公开 API 文档，不启用 CORS，只接受本机 Host。HTTP 实际请求体上限默认 128 KiB。

除 `/health` 外所有接口需要 `Authorization: Bearer <token>`。免令牌健康仅返回服务名/版本，不包含数据、配置或凭据。

## 接口

| 方法与路径 | 请求 | 响应 |
| --- | --- | --- |
| `GET /health` | 无 | `{status:"ok",service:"football-assistant",version:"0.1.0"}` |
| `GET /v1/status` | Bearer | `{source_status,modelConfigured,modelStatus,memory:{messages,memories}}` |
| `POST /v1/observations` | 版本化观测 JSON | `{accepted:true,duplicate,event_id,source_status}` |
| `POST /v1/chat` | `{message:string,conversation_id?:string}` | `{reply,conversation_id,source_status}` |
| `GET /v1/companion/state` | Bearer | `{state:"idle",mood:"neutral",status,source_status}` |
| `GET /v1/memories` | Bearer | `{memories:[{id,content,source,created_at}]}` |
| `POST /v1/memories` | `{content:string}` | 201，记忆对象；`source` 为 `user_explicit` |
| `DELETE /v1/memories/{id}` | Bearer | `{deleted:true}`，不存在返回 404 |

`source_status` 具有 `availability`、`source`、`last_captured_at`、`observed_at`、`synthetic`、`game`、`facts_count`、`event_id`，已有观测另带 `source_freshness` 与 `adapter_id`。没有数据时来源、时间与 game 为 null，availability 为 `not_connected`；合成观测始终标 `synthetic`，真实数据按观测状态/时间标 `available`、`stale` 或 `unavailable`。存档仍保留 `snapshot`，不因最近收到就变实时。默认 300 秒后标 stale，观察时间未知也标 stale。

`modelConfigured` 只表示三项配置存在，不能证明连接或模型可用。`modelStatus` 是 `unconfigured`、`ready` 或最近调用失败后的 `error`；`ready` 仍须真实请求验证。Companion status 对应 `model_unconfigured`、`ready`、`model_error`。

聊天输入最多 4000 字符，空白与未知字段拒绝。conversation_id 返回后交还同一值，可恢复近期 20 条消息；已成功的对话写入 `companion.sqlite`，重启可恢复。失败请求不会存成成功回答。基础长期记忆由用户显式创建，可列出和删除，最近 30 条在模型上下文中使用。此版本没有 RAG、自动记忆巩固、成长系统或多 Agent。

## 观测与 Save Adapter

Data Core 接受 Schema `0.1.0` 的能力报告、`0.2.0` 的能力报告/事实快照以及 `0.3.0` 的逐字段来源事实，使用 Draft 2020-12 与 UUID/date-time 格式校验，拒绝额外命令字段和非有限 JSON 数字。事件 ID 幂等：同 ID 的重复发送不新增行。适配器必须对其实际来源负责，HTTP token 不证明事实真实。

0.2 payload 为 `{kind:"fact_snapshot",facts:[{entity_kind,entity_id,field,value,unit?}]}`，最多 2000 条；value 只接受 JSON 标量，字段名由已验证适配器映射，不假定 FM27 内存结构。完整来源、synthetic、build、会话与时间仍在信封上。使用 `uv run football-assistant-import --fixture contracts/examples/runtime-observation.json` 可回放明确标记的合成能力报告；合成结果不能验收真实 FM27 数据接通。

可选存档探测安装 `uv sync --extra save`，再运行：

```sh
uv run --extra save football-assistant-save-probe --confirmed-copy "/path/to/stable-copy.fm"
```

这个诊断命令仅探测高层 fmsave 兼容性：`probe` 返回能力状态和来源，`read_snapshot` 对 FM27 保持 unsupported / observation null。固定 `fmsave==0.7.0`（MIT）的高层 Save API 只支持 FM26，此处没有绕过版本门。正常 MVP 导入使用另一条独立的 `read_summary_snapshot` 路径，只复用底层容器 reader，已从真实 FM27 build `27.0.0+2486695` 副本读出两个实验性摘要字段并通过 API 入库；该能力不等于完整球队/球员解析。可重复入口见下节 `football-assistant-import-save`。

## 错误与验证

认证失败 401；Schema/输入错误 422；请求过大 413；模型未配置 503 / `model_not_configured`；模型连接、超时或文本响应失败 502 / `model_unavailable`。业务错误使用 `detail:{code,message}`；框架输入验证错误仍使用标准 422 结构。错误响应不回显 API key、完整服务异常或模型请求正文，没有固定文本兜底伪装模型成功。可用 `FOOTBALL_ASSISTANT_MAX_OUTPUT_TOKENS` 限制输出，`FOOTBALL_ASSISTANT_MODEL_EXTRA_BODY` 传明确的兼容服务选项；`FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT` 与 `FOOTBALL_ASSISTANT_MODEL_BUDGET_ID` 使用 SQLite 持久请求计数，失败也计数，超限返回 429 / `model_request_limit`。当前有限测试配置总上限 2、输出 160、关闭 thinking、零自动重试，本轮不会自动提高或重置该授权预算。用户之后批准继续时，可手动把 `.env` 的 `FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT` 改为新的正整数总上限并重启后端，例如 3 表示现有 2 次后再允许 1 次；保持 `FOOTBALL_ASSISTANT_MODEL_BUDGET_ID`、数据目录和 SQLite 不变，不删除计数或聊天记录。

运行 `uv run --extra save --extra agent pytest -q`。覆盖本机鉴权、body 上限、Schema、观测重复、记忆重启/删除、失败模型连接，以及明确标记的本地 HTTP provider fixture 经过真实 PydanticAI/OpenAI SDK 的对话与历史通路。该 fixture 只证明接口联通，不是用户真实模型或真实游戏验收。Windows/macOS CI 已配置，只有实际跑出的结果才能作为跨平台通过证据。

模型接入依据 [PydanticAI 兼容 API 官方文档](https://pydantic.dev/docs/ai/models/compatible-apis/)，使用 `OpenAIChatModel` + `OpenAICompatibleProvider`，显式服务地址/密钥，模型 SDK 不重试；事实上下文、人格和显式记忆随每轮请求发送给用户所选服务。


## 可重复导入新保存

```sh
uv run --frozen --extra save football-assistant-import-save "$HOME/Library/Application Support/Sports Interactive/Football Manager 27/games/example.fm"
```

后端先保持运行。命令只读检查源文件稳定性，创建私有副本，校验源/副本 SHA-256 与源文件状态，再调用独立 summary adapter 并带本机 Bearer 导入；不会调用模型、修改原件或自动反复读取。含空格与中文的路径由参数列表处理。返回 0 导入成功，2 格式/构建不支持且没有观测，1 文件/稳定性/服务等失败。副本与 `.import.json` 来源记录保存在受限本机目录，不进仓库。

窄 adapter 严格限 summary schema31 与 build `27.0.0+2486695`，依次读取长度前缀字符串/数量/不透明 grammar 节点/日期 codec；不使用绝对字段偏移或查找硬编码标签/日期。容器目录 compressed_size 上限 2 MiB、decompressed_size 上限 1 MiB，在解压前检查。schema/build/长度/UTF-8/日历不满足时明确不支持，不回退为空值或假事实。

Schema 0.3 每字段带 source、adapter、experimental、validation_method、当前 snapshot SHA、初始 UI evidence sample SHA 和 scope。原样本 exact 方法要求两个 SHA 相同；新同构建保存的当前 SHA 不受白名单限制，方法为 `format_checked_initial_sample_ui_crosschecked`，明确没有逐次 UI 核对。当前仅 `save_summary.club_label` 原文标签和 `game_date` 两字段，不输出 ID 680、球队对象、阵容、经理或时刻。另一份不同摘要的真实 backup 副本已做只读结构对照，但不能取代新的 UI 语义核对。

## Continuous runtime monitoring

The existing 0.2 / 0.3 observation envelopes remain valid. No new observation version is required. Each runtime capture has its own event UUID, producer capture/observation timestamps, stable adapter ID, real game build and process-session ID. Bundle version is a separate catalog field and is not substituted for the runtime game's self-reported build.

Data Core partitions streams by source kind, adapter, game build, session and synthetic flag. An active real runtime stream takes priority over save snapshots; a newer save import cannot replace it. When runtime disconnects, a save fallback is explicitly labelled by `selection_reason`. Synthetic streams cannot mask a real source. Older out-of-order captures remain attributable in history but do not rewind the selected snapshot.

Capture reception and data freshness are independent. `last_seen_at` is server receipt time, and connection timeout uses server monotonic elapsed time rather than producer timestamps or desktop polling. Defaults are connected → stale after 10 seconds → disconnected after 30 seconds. Configure `FOOTBALL_ASSISTANT_RUNTIME_STALE_SECONDS` / `FOOTBALL_ASSISTANT_RUNTIME_DISCONNECT_SECONDS` if the collector cadence changes. A backend restart marks persisted runtime connections disconnected until a new capture/heartbeat arrives.

`capture_age_seconds` and `observation_age_seconds` retain producer-data age. A heartbeat or retry can prove that transport is alive without making old facts fresh. `data_freshness` is `fresh`, `stale`, `unknown` or `unavailable`, separately from `connection_state`. Save sources remain `snapshot` and never become live connections.

Every unique event retains a receipt with stream/capture metadata. Consecutive equal payloads reuse stored content while advancing capture/last-seen state; a repeated UUID is an idempotent retransmission. Reusing a UUID for different content returns 409. Low-level change events compare raw values, preserve duplicate text multiplicity, and do not infer football entities from UI node paths.

| Endpoint (Bearer required) | Purpose |
| --- | --- |
| `GET /v1/monitoring` | Selected source, all streams, catalog coverage, recent changes, latest event cursor and timeout settings |
| `GET /v1/events?after=0&limit=100` | Durable cursor polling; returns events, next/latest cursor, has_more and cursor_reset_required |
| `GET /v1/monitoring/fields?stream_id=...` | Current fields with source/session/build/capture information and observed-value/null state |
| `POST /v1/monitoring/heartbeat` | `{stream_id,state:"connected"|"disconnected",detail?}` for an already registered runtime stream |
| `POST /v1/interfaces/catalog` | Register/upsert a bounded metadata batch; never invokes a member |
| `GET /v1/interfaces/catalogs` | Inventory completeness and independently counted last explicit runtime-probe coverage |
| `GET /v1/interfaces?catalog_id=...&after=0&limit=100&access_status=...` | Paginated metadata and readability records |

A desktop can poll monitoring/events every 2 seconds without calling chat. Preserve `next_cursor`; reset to zero only when `cursor_reset_required` is true. Connection kinds are `source_connected`, `source_stale`, `source_disconnected`. Data kinds are `snapshot_received`, `ui_text_changed`, `raw_fields_changed`, and `capabilities_changed`. Catalog completion is `interface_catalog_registered`. These are raw observation / inventory events, not goals, transfers, injuries or other football interpretations. Each event retains `synthetic`, stream and source-event attribution.

There is no automatic model dispatch, chat request, TTS or game operation on ingest/events. The event cursor is an integration point for future Agent scheduling; this version records and exposes events only. The existing Go budget remains 2/2.

## Interface inventory versus runtime coverage

Catalog requests have `catalog_id`, `catalog_version`, `adapter_id`, `game_build`, optional `bundle_version` and `session_id`, `metadata_sha256`, `metadata_version`, `captured_at`, `synthetic`, `total_expected`, `complete` and `records`. Each batch is at most 100 records and still subject to the 128 KiB request limit; byte-bounded batches below 100 KiB are recommended. Only the final batch requests complete, and its unique registered count must equal total_expected. Catalog counts/status totals are maintained incrementally, so registering or polling a large inventory does not scan all member records.

Records retain `interface_id`, assembly, namespace, type, `member_kind` (`type`, `field`, `property`, `method`, `event`), name/signature/visibility, nullable `is_static`, `declaring_token`, embedded parameter metadata, reason and side-effect policy. Access states are unknown / not_probed / needs_context / verified_readable / blocked / unsupported / error. Event inventory does not subscribe to it; setter/add/remove/raise or mutating members can be labelled do_not_invoke. A property getter's name does not establish safety or readability.

Verified-readable records require explicit verification text, a timezone-qualified verification timestamp, a read_only policy and a game session; the stored record retains that verification session. Static inventory re-registration does not erase a measured probe. `inventory_complete` only means enumeration is complete. `runtime_verified_coverage` describes last explicit probe evidence, never blanket live coverage or permission to call every member. Observed fields and active-source heartbeat are exposed independently. No member is probed just because it appears in the catalog.


## Bounded event polling

`/v1/events` limits the final UTF-8 serialized JSON envelope to 512 KiB, independently from the requested event count. Clients advance to `next_cursor` and continue while `has_more` is true; large Chinese text does not turn a page into an endlessly rejected oversized response. Empty pages keep the supplied cursor, and a cursor beyond the retained maximum sets `cursor_reset_required`.

If one event alone exceeds the budget, the page returns that cursor as an explicitly marked summary: `details_truncated:true`, `details.summary_only:true`, original detail byte count/SHA and `original_event_ref`. The full DB row remains intact. `GET /v1/events/{cursor}` requires the same Bearer token and explicitly retrieves the complete original event; it may be larger than the normal polling budget and should not be automatically fetched by the compact desktop poller.

`/v1/monitoring` uses the same bounded event builder for recent changes and caps its final response at 512 KiB. Its `recent_changes_after`, `recent_changes_next_cursor`, `recent_changes_has_more` and `recent_changes_ref` expose continuation. Large stream/catalog summary lists are explicitly labelled by total/truncated fields rather than silently presented as complete. The durable event cursor retains all events; these response budgets do not delete or rewrite history.

Native export inventory uses a separate `catalog_id` and `inventory_kind:native_exports`, with `native_module` and `native_module_sha256`; managed inventories are labelled `managed_metadata`. `member_kind:native_export` denotes a native symbol rather than a managed method. Current native registrations are strictly not_probed / do_not_invoke / is_static:null, and registration performs no native invocation. Managed and native inventory counts remain separate from runtime readability and from actual football-field coverage.

## Passive business-registry diagnostics and enumeration

`POST /v1/interfaces/probes` accepts the runtime inspector's existing sidecar shape. Common source fields are `adapter_id`, `session_id`, `game_build`, nullable `bundle_version`, lowercase `metadata_sha256` / `game_assembly_sha256`, timezone-qualified `captured_at`, and `synthetic`. Each of at most 100 probes has `probe_id:registry:<RegistryName>`, `kind:runtime_registry`, status (`available`, `needs_context`, `unsupported`, `error`, `not_probed`), `context_ref`, reason, nullable `values.id_count` / `name_hash_count`, enumeration metadata and `entries:[]`.

Counts describe last-reported runtime context, not an entry inventory or live property values. Unknown counts remain null. Diagnostics can declare an epoch descriptor, but actual observed entries stay zero and complete stays false until registry batches are registered. Repeated unchanged diagnostics update capture/receipt timestamps without repeated history or change-event spam. Older captures cannot replace the latest state. The diagnostic source never replaces the UI observation source and never invokes a method or runs Agent Core.

Responses return `accepted`, `changed_count` and `results`, including `probe_key`, values, authoritative enumeration state and `field_values_known:false`. Query latest records with `GET /v1/interfaces/probes?after=0&limit=100&session_id=...`; query state-change history with `GET /v1/interfaces/probes/history?probe_key=...&after=0&limit=100`. Latest-list cursors enumerate records; history cursors enumerate changes. Both are byte-bounded pages. Monitoring includes a compact `registry_summary` for the relevant session, with explicit synthetic/source scope and timestamps; these are last-reported diagnostics rather than an assertion that a past object remains live.

Complete ID inventories use a separate endpoint:

```text
POST /v1/interfaces/registries/batches
{
  <same source header>,
  registry_id: "PropertyIdentifierSet",
  enumeration_id: "<stable epoch UUID>",
  dictionary_version: <actual int or null>,
  expected_count: <actual count or null>,
  complete: false,
  entries: [{id: <real uint32>, name: null, owner: null,
             display_name: null, value_type: null}]
}
```

Each request still has the 128 KiB / 100-item limits. IDs come from the actual registry's uint32 dictionary, including zero; metadata indexes, synthetic substitute IDs, booleans and numeric strings are not accepted. Nullable metadata means unread, not an invented default. Optional metadata can be enriched from null, but conflicting known values inside one epoch are rejected.

An epoch fixes adapter, session, registry, source hashes/build, expected count and dictionary version. A changed context/version/expected count needs a new enumeration ID. Unique counts are incrementally maintained; retries are idempotent and do not scan/count the whole entry table. A terminal batch can set complete only when received unique IDs equal the known expected count. Unknown expected counts cannot complete. Expected zero requires an explicit empty terminal batch before `known_empty:true`; a count-only probe cannot declare an enumeration complete.

The POST returns `enumeration_key`, expected/observed counts, complete/known_empty and inserted/enriched counts. `GET /v1/interfaces/registries/{enumeration_key}` returns the authoritative descriptor. `GET /v1/interfaces/registries/{enumeration_key}/entries?after=0&limit=100` returns byte-bounded entry pages, source/epoch attribution, capture timestamps and known metadata fields. Complete means `uint_id_inventory_only`, not known property values. Probe completion is resolved from this registered inventory rather than trusted from a client counter.

Registry state events are `registry_probe_changed` and `registry_enumeration_completed`, explicitly diagnostic/inventory events. Managed/native static inventories, dynamic business IDs, actual getter readability and property values remain separate dimensions. Actual getter evidence continues to use catalog verification upserts. These APIs do not provide RPC, reflection or game invocation, and never trigger model requests. This is registry observation/storage infrastructure; the full interface-reading goal is not complete.

## Pointer-free native observer diagnostics

`POST /v1/interfaces/native-observers` is a passive diagnostics sink, not hook installation, capture control, getter invocation or a payload decoder. It does not alter the UI fact source, registry state, catalog readability or Agent/model budgets. Latest records are paged at `GET /v1/interfaces/native-observers`; state history is `GET /v1/interfaces/native-observers/history?observer_key=...&after=0&limit=20`. All require Bearer authentication; request and final paginated-response byte budgets remain 128 KiB and 512 KiB.

The DTO extends the registry source header with `game_plugin_sha256`, `observer_sha256`, a stable retry `sample_id`, status, ABI version 1 and this specific target:

```json
{"kind":"dispatch_thunk","anchor_export":"game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr","anchor_offset_bytes":12,"dispatch_rva":"0x16c24"}
```

The observed target is the dispatch thunk at anchor + 12 bytes, not proof that the setter export body was read or is safe to invoke. Source session/build, metadata/assembly/module/observer hashes scope each record. Installation flags are reported facts, not commands; concurrent stats are approximate snapshots and are not forced into impossible cross-counter equalities.

Nullable `installed`, `capture_enabled` and `install_state` distinguish unavailable state from false/zero. Every UInt64 is a canonical decimal **string** or null, including known zero: `invocation_count`, `enqueued_count`, `drained_count`, `overflow_dropped`, `contention_dropped`, `stopped_invocations`, `in_flight`, `queue_size`, `queue_capacity`, header sequences/thread IDs/counts and `records_total`. JSON numbers, negative values, overflow and noncanonical encodings are rejected. Consumers must not convert these strings to JavaScript Number.

At most 16 sanitized `records` retain call sequence, nullable thread ID, nullable keys/payload counts, UInt32 flags and nullable native header age. Known-count flags must match nullable counts; known zero stays "0". **keys_count counts UInt64 elements; payload_count counts bytes.** `records_total` describes the original drained poll, not the included subset. Projection truncation is explicit. Installation reports may contain ABI/size/result/state/check/prepare/commit codes, but absolute target/original addresses and all other pointer fields are rejected without echoing their values in validation responses. The relay must strip private control-plane addresses before posting.

`last_seen_at` is HTTP receipt time. `last_callback_at` is only a source-capture-minus-native-header-age approximation for the last observed header; empty polls keep the previous value or unknown, never replace it with receipt time. Counter growth without a header does not invent a timestamp. Callback evidence proves entry into the dispatch observer, not successful original-handler processing, payload decoding or understood football values. Overflow/contention/stopped counts can show observation gaps; `complete`, `field_values_known`, payload-decoded and lossless-capture claims stay false.

Monitoring exposes `native_observer_summary` only for the matching selected runtime session/build/synthetic scope. No report is unknown/null, not a fabricated zero. After backend restart or stale/absent native updates, primary current-state installation flags become unknown while last-reported evidence remains attributable. History/samples are session-scoped and idempotent; ordinary event polling emits state/first-callback/gap edges rather than an event for every counter increment. This endpoint never marks the native export inventory verified-readable. Real FM installation/callback evidence must be validated separately; this diagnostic interface alone does not complete the full goal.

### Experimental focused schedule UI association

Authenticated `GET /v1/reader/schedule` returns a current-capture preview without
model calls or unrelated raw UI evidence. It works in reader-only mode too.
For `schedule_analysis`, `POST /v1/agent/ui-advice` now includes
`schedule_projection` in its prepared result. This is **not** native business
readiness: `production_ready=false`, partial and capture-local throughout.
The alpha profile pins FM27 build `27.0.0+2486695`, runtime UI adapter `0.4.0`,
macOS arm64, one explicit focus root, and the Chinese `赛程安排` title.
It maps only complete observed rows at indices 0–9 to date display, opponent
display, 主/客 display and competition display. Indices and paths are **not**
fixture/team IDs. Each mapped field carries its exact path, profile, event,
session, capture time, scope and full-capture fingerprint. Missing rows are not
inferred from adjacent text. Unsupported profile, duplicate paths, invalid
columns and unsupported markup yield no projected rows.

Two-digit years retain their displayed spelling and numeric year/month/day
components. Century, ISO date and kickoff remain unknown; this cannot support
full schedule-congestion or precise cross-year rest calculations. Only the
existing balanced, allowlisted TMP link/style/color markup is stripped; arbitrary
HTML is rejected. Title matching does not independently verify visibility.

When this profile matches, the model payload is narrowed to the structured
four-field projection and its source/limitation metadata: unrelated raw UI text
is **not** sent to the provider. Raw evidence remains local in the API result.
The refresh fence also checks the projection fingerprint and clears projected
rows on a changed/expired capture. Schedule requests that do not match the profile are blocked before any provider
call; there is no raw-text fallback. Other capabilities retain their existing
generic UI evidence behavior. No new model requests, model configuration,
Mac deployment or production-native capability are enabled by this change.
