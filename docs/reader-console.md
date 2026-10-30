# 独立读取层与命令框

读取层负责接收、保存和读取适配器的观测。助教可以以后作为这个 API 的客户端。独立 reader 不导入或初始化 Agent、PydanticAI、OpenAI provider，也不读取项目 `.env` 或需要模型服务、API Key、Electron。完整旧后端仍通过 `--extra agent` 提供聊天和记忆；本次没有增加推荐、等级或自动模型调用。

## 启动

在仓库目录双击 `scripts/Reader.command`（macOS Terminal）或 `scripts/Reader.cmd`（Windows 命令框）。两个脚本均处理带空格的项目路径，使用独立 `.venv-reader`，优先复用 runtime 文件指向的兼容服务。没有服务且配置端口空闲时，启动独立 reader 服务，日志为私有数据目录的 `reader.log`。不打开游戏或桌宠。

当前终端也可以启动，以下命令不会修改正在使用的 `.venv`：

```sh
cd "/path/to/Football Assistant"
UV_PROJECT_ENVIRONMENT=.venv-reader uv run --frozen python scripts/launch_reader.py
```

Windows PowerShell 设置 `$env:UV_PROJECT_ENVIRONMENT='.venv-reader'` 后运行相同 `uv run --frozen python scripts/launch_reader.py`。第一次需要 uv 安装依赖。已有开发环境可以用 `uv run --no-sync python scripts/launch_reader.py --no-start`，避免同步环境。

只读检查现有服务，不启动任何进程：

```sh
uv run --no-sync python scripts/launch_reader.py --check
uv run --no-sync python -m football_assistant_data.reader_cli status
```

直接启动独立服务：`UV_PROJECT_ENVIRONMENT=.venv-reader uv run --frozen football-assistant-reader-server`。它使用 `FOOTBALL_ASSISTANT_DATA_DIR`、`FOOTBALL_ASSISTANT_RUNTIME_FILE`、`FOOTBALL_ASSISTANT_PORT` 环境变量，默认 `local-data/runtime.json`、`127.0.0.1:17827`。不会覆盖活跃服务的 runtime 或停止占用端口的进程。同一数据目录的两个新服务由写入锁互斥；兼容旧服务的存活 PID 也会阻止第二 writer。独立验收应使用临时数据目录、runtime 和空闲端口。直接调用测试用 app factory 不负责进程级锁，生产入口应使用上述命令。

`--runtime-file "/path with spaces/runtime.json"` 可指定读取客户端的 runtime 文件；不要把 token 放进命令行。CLI 每次请求重读 runtime，401 时重读后重试一次，支持服务重新启动和 token 轮换。仅允许 literal loopback HTTP，禁用代理和重定向，默认超时 3 秒。运行器遇到不兼容服务、无认证 runtime 的占用端口或无响应的现有进程会明确失败并保留现场。

## 命令

每条结果都是 JSON Lines，可直接管道读取。未知命令返回 `unsupported`，不模拟数据。

| 命令 | 输出 |
| --- | --- |
| `help` | 固定只读命令列表 |
| `status` | 选中来源、连接与采样时间、事件游标、native 解码可用性 |
| `snapshot --limit 100 --after 0` | 当前来源的观测元数据与一页原始 facts |
| `snapshot --after 100 --event-id UUID` | 固定同一 snapshot 翻页，已变化返回 409；从 0 重读 |
| `raw-ui --limit 100` | 同一页中的 UI facts，保留来源和缓存限制；游标仍按全部 facts 计算 |
| `watch` | 从当前游标等待后续内容/连接变化；不回放整个历史 |
| `watch --after 42 --interval 1 --polls 5` | 从指定游标做有限次轮询 |
| `event 42` | 显式读取某条完整历史事件，包括被事件页摘要的 details |
| `native --limit 20` | 显式查看 sanitized native headers 诊断，默认不刷计数 |
| `quit` | 仅退出控制台，后端与游戏继续运行 |

Ctrl-C 停止 watch 并回到控制台。默认 watch 每秒至多一页、每页最多 100 事件，略过目录注册和 native 计数更新，只显示原始观测/连接变化。断线重试，错误状态改变时才输出；恢复有明确标记。事件分页遵从服务端 512 KiB 协议，保留 `details_truncated` 与原事件引用；`has_more` 但游标不前进时输出 `cursor_stalled` 并等待，避免忙循环。后端历史重置后从零恢复。

一次性和管道示例：

```sh
uv run --no-sync python -m football_assistant_data.reader_cli snapshot --limit 5
uv run --no-sync python -m football_assistant_data.reader_cli watch --interval 1 --polls 3
printf 'status\nraw-ui --limit 3\nquit\n' | uv run --no-sync python -m football_assistant_data.reader_cli
```

没有任意 HTTP method、eval、反射方法调用或游戏写入命令。不支持的球员、日期、邮件或比赛高层命令会报错；控制台只展示适配器已提供的观测。

## 数据能力与 API

新服务提供认证只读 `GET /v1/reader/status` 与 `GET /v1/reader/snapshot?after=0&limit=100&event_id=...`，遵循 Data Core 既有来源选择策略，不绕过策略直接查 SQLite。Snapshot 保留信封的 source、game、captured_at、observed_at、synthetic、status，以及 payload 元数据和字段 provenance。无数据明确返回空 facts 与 `partial:true`。

未重启的旧后端可通过已有 `/v1/status`、`/v1/monitoring/fields`、`/v1/events` 复用。这个窄兼容 adapter 明确标记 `reader_api:"legacy"` 和 `partial:true`；旧字段 API 没有完整信封 status，故 `observation:null`，不补造。字段原有 source/capture/provenance 保留。

UI 原文是受限观测，可能混入隐藏或缓存内容，位置路径不能作为球员实体 ID，也不能据此声称完整球队数据。`raw-ui` 只做种类过滤，不声称已完成缓存清理。

Native headers、回调次数、payload 字节数和 keys 数属于诊断，不能叫作足球字段值。当前 reader 明确 `awaiting_decoded_native_records`、`payload_decoded:false`、`field_values_known:false`。离线 packet grammar 的解码本身不等于球员/球队字段映射。未来经验证的 source adapter 可通过现有 observation envelope 发布实际 facts，本次没有假造 native 业务字段或全量接口目录。

## 验证边界

测试覆盖无 Agent/provider 导入、独立 reader 空数据与真实元数据、分页 snapshot 改变、回环限制、无代理/重定向、token 轮换、旧服务兼容、事件摘要/游标停滞/断线恢复，以及命令白名单和带空格路径。Windows 启动脚本完成静态测试；Windows 实机窗口仍需单独验收。真实 live 服务只读验证与临时独立服务验证均不调用模型。测试中的合成事实只用于测试临时目录。
