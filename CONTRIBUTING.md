# 参与贡献

欢迎一起完善 FootballAssistant。反馈问题、补充测试、改进文档和提交小功能都很有帮助。这里以当前 Alpha 集成代码为准，帮助你在不接触真实游戏或付费模型的情况下开始贡献。

## 先了解当前边界

FootballAssistant 是面向 FM27 的非官方 AI 桌宠助教项目。当前技术栈是 **Electron 桌面 UI + Python Data / Agent + C# GameBridge**，不是 Flutter。

项目仍处于 Alpha，不能把打包成功、离线测试通过或某一次实机实验写成“完整 MVP 已完成”或“所有平台已支持”。尤其注意：

- 普通 Windows reader 目前仍是 `unsupported`，不启用原生游戏读取。独立 scheduler probe 和 metadata 实验已有实机成功记录，但它们不等于球员、战术或赛程数据读取成功。
- 独立 Windows UI candidate 的预算调整仍待实机复验。metadata/class resolve 成功、取得根节点或耗尽预算都不等于成功取得 UI 文本；UI 文本也不自动等于已核验的业务字段。
- macOS 的历史只读实验、存档摘要和某个 build 的证据不能推广到 Windows、其他游戏 build 或完整字段覆盖。
- `unknown`、`partial`、`stale`、`unavailable`、`unsupported` 与模拟结果应如实保留，不能用默认值、模拟数据或聊天回复掩盖未验证的数据。

实现细节见[模块边界](docs/module-boundaries.md)、[集成记录](docs/alpha-integration-notes.md)和 [Reader 语义](docs/reader-semantics.md)。旧验收记录是历史证据，请同时核对当前代码与对应提交。

## 从哪里开始

| 路径 | 适合贡献的内容 |
| --- | --- |
| `apps/companion/src/`、`apps/companion/test/` | Electron 主进程、Renderer、设置、桌宠交互与离线测试；当前源码主要为 JS / CJS |
| `modules/data-core/` | FastAPI、本机认证、Reader、状态与持久化；测试在该模块的 `tests/` |
| `modules/agent-core/` | 模型路由、工具与人格资源；关联回归也在 Data Core 测试中 |
| `modules/save-adapter/` | 有限存档适配与独立测试，不是完整 FM27 存档 reader |
| `modules/game-bridge/` | C# 只读桥接、隔离自测与独立 Windows 实验候选 |
| `contracts/` | 数据契约与 JSON Schema；变更时同时检查生产方和消费方 |
| `scripts/`、`.github/workflows/` | 开发、打包、诊断与 CI；涉及安装或真实游戏的脚本需单独审查 |
| `docs/` | 架构、操作边界、验证方法和证据记录 |

新功能或跨模块改动可以先在 [Issues](https://github.com/sanshanhyo/FootballAssistant/issues) 简述需求和方案；修正错字、小 bug 或补充测试可直接提交 PR。不需要为了一个小修改建立复杂流程。

## 分支与工作目录

提交前先与维护者确认目标分支。当前 Alpha 代码在 `integration/alpha-reader-ui`；`docs/update` 是 README / roadmap 文档线，不应作为最新功能代码的基线。不要直接覆盖他人的分支，也不要把历史功能分支整包合入来“同步”已集成的代码。

从仓库目录创建自己的分支；下面以当前集成线为例：

```sh
git fetch origin
git worktree add -b docs/my-change ../FootballAssistant-my-change origin/integration/alpha-reader-ui
cd ../FootballAssistant-my-change
```

也可以使用独立 clone。每个任务使用独立工作目录，不在共享工作树里切换分支、清理他人文件或重置未提交修改。外部贡献者先 Fork，并按自己的 remote 名称调整命令。

- 一次 PR 尽量只解决一个问题，避免混入格式化、资源替换、版本号或发布配置修改。
- 推荐约定式提交，例如 `fix(reader): reject stale evidence`、`test(bridge): cover missing window`、`docs: clarify Windows limits`。
- 不必为提交贡献自行发布 Release、安装桥接器或修改用户游戏目录。合并和发布由维护者另行安排。

## 本地环境与启动

### 工具版本

- Git。
- Python **≥ 3.12** 和 `uv`。后端 CI 目前使用 Python 3.14、uv 0.9.9；桌面内嵌后端构建使用 Python 3.12。
- Node.js **≥ 22.12.0** 和 npm；桌面 CI 使用 Node 24。
- 修改 C# 桥接时安装 **.NET SDK 10.0.x**。

优先沿用 `uv.lock` 和 `apps/companion/package-lock.json`，不要为了本地安装方便批量升级依赖。版本与真实命令分别见 [pyproject.toml](pyproject.toml)、[package.json](apps/companion/package.json) 和 [CI 配置](.github/workflows/)。

### 安装并做离线检查

以下命令均从仓库根目录开始，适用于常见 shell 和 PowerShell，不需要游戏、API Key 或真实存档：

```sh
uv sync --frozen --python 3.14 --extra save --extra agent
uv run --frozen --extra save --extra agent pytest -q
npm --prefix apps/companion ci
npm --prefix apps/companion run check
```

普通 `pytest -q` 回归使用构造数据、替身或本机测试服务，不要求真实 API Key；不要为运行测试填写付费服务凭据。`--extra save` 与 `--extra agent` 安装相应可选依赖，不代表需要导入真实存档或调用模型。`npm run check` 执行配置中的语法检查和 Node 测试；项目目前没有统一的 `lint` 脚本，请不要在验证报告里写不存在的 `npm run lint`。

### 开发运行

只看桌面交互时：

```sh
npm --prefix apps/companion start
```

保持模拟模式；真实 backend 和模型连接需要显式配置。要开发后端，在另一个终端从仓库根目录运行：

```sh
uv run --frozen --extra save --extra agent football-assistant-backend
```

只开发独立 Reader、无需模型 SDK 时，可在另一份独立工作目录使用：

```sh
uv sync --frozen --python 3.14 --no-dev
uv run --no-sync football-assistant-reader-server
```

完整 backend 与独立 Reader 默认占用相同端口，不要同时启动；让桌面端与所选服务使用同一份 runtime 文件，详见[集成配置](docs/alpha-integration-notes.md)和[读取控制台](docs/reader-console.md)。不要通过关闭认证或扩大监听范围解决连接问题。

开发时使用独立数据目录：后端可设置 `FOOTBALL_ASSISTANT_DATA_DIR`，桌面可设置 `FA_COMPANION_USER_DATA_DIR`，均使用当前用户控制的绝对路径，避免覆盖日常历史与设置。不要复用他人的 runtime 文件或令牌。

真实模型测试并非贡献前提。确需测试时自行配置本地凭据、先确认费用与数据范围，并设置明确的正数请求上限。**`.env.example` 中 `FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT=0` 表示不设硬上限，不是禁用模型。** 不要把已有凭据与默认额度直接用于自动化测试。

## 提交前验证

按修改范围运行相关检查，并在 PR 中记录命令、平台、提交 SHA、通过 / 失败 / 跳过 / 未运行。只修改文档时，检查链接、路径、命令与 `git diff --check` 即可，不必声称运行了代码测试。

| 修改范围 | 最低验证 |
| --- | --- |
| Python、契约、Agent、存档适配 | 上述 `pytest -q`；新增行为应有回归测试，保持基础 Reader 安装不依赖模型 SDK |
| Companion | 上述 `npm run check`；交互改动补充对应 UI 验证，关注取消、重复点击、重连、关闭后重开和过期响应 |
| C# 公共桥接 | 下列 `SelfTest`、`DirectHostSmoke`；Windows 路径同时运行 `WindowsProbeTests` |
| 独立 Windows metadata / UI candidate | 下列对应 draft 自测；不能以这些测试替代 FM 实机验证 |
| 打包或启动器 | 目标平台的内嵌后端构建、smoke、桌面打包与安装/冷启动验证；参考现有 desktop workflow |

从仓库根目录运行的 C# 离线检查：

```sh
dotnet run --project modules/game-bridge/tests/SelfTest.csproj
dotnet run --project modules/game-bridge/tests/DirectHostSmoke.csproj
dotnet run --project modules/game-bridge/tests/WindowsProbeTests.csproj
dotnet run --project modules/game-bridge/windows-smoke-draft/DraftTests.csproj
dotnet run --project modules/game-bridge/windows-ui-smoke-draft/UiDraftTests.csproj
```

这些命令不要求安装游戏桥接器。Windows 原生 harness 的覆盖与纯逻辑分支应分开记录。

Companion 还有可选的隔离 Electron smoke（需要 Playwright 与可运行的 Electron 环境）：

```sh
cd apps/companion
node test/electron-smoke.cjs
```

可用 `FA_PLAYWRIGHT_MODULE_PATH` 指定已有 Playwright 模块。它使用模拟服务和假媒体设备，不证明真实麦克风、系统权限、音色或模型服务可用。详见 [Companion 开发说明](apps/companion/README.md)。

**Windows 优先，macOS 也必须保持兼容。** 当前 CI 范围如下，不等于全部实机验收已经完成：

- Backend：`windows-latest` + `macos-latest`。
- Desktop：Windows x64 + macOS arm64；各自构建内嵌后端、桌面产物并执行对应 smoke。
- Windows probe / metadata / UI candidate：Ubuntu + Windows 的离线策略、构建或 harness 检查。
- macOS bridge payload：macOS 上的隔离测试和候选构建，不是游戏安装验收。

Linux 通过不能替代目标平台通过；Mac 通过也不能推断 Windows 通过。没有对应机器时如实写明，由维护者结合目标平台 CI / 实机结果决定。CI 有路径过滤，某个检查未触发不等于它已通过。修改打包时以 [desktop workflow](.github/workflows/desktop.yml) 为准，先构建匹配架构的内嵌后端，再运行 `pack:mac` 或 `pack:win`，不要直接把开发目录当作可发布成品。

## Bug 报告与证据

请尽量提供：

1. 分支 / 提交 SHA 或实际安装版本，OS、架构及相关工具版本。
2. 最小复现步骤、预期行为、实际行为，是否可稳定重现。
3. 使用的是模拟模式、synthetic / fixture、本机 HTTP、真实模型，还是经授权的真实游戏实验。
4. 脱敏后的最小错误片段、状态码或裁剪截图；涉及游戏时另记游戏 build，勿把 save build 与 executable build 混为一谈。
5. 已执行检查与未覆盖范围。没有数据、超时、预算耗尽或 skipped 都不是成功证据。

优先提供人工构造的最小 fixture，并明确标为 `synthetic` / `fixture`。真实采样必须记录来源与验证边界；脱敏之后仍不能把 synthetic 结果改称“实机读到”。字段数量、静态清单规模、测试数量和方法解析数量都不是业务覆盖率。

**不要上传**游戏本体、DLL / 原始游戏资源、真实存档、原始内存 dump / 原始采样、个人数据库或完整聊天历史；也不要上传账号、API Key、token、`.env`、`runtime.json`、凭据配置或含这些内容的截图、日志、CI artifact。路径中的用户名、设备标识和其他个人信息也需脱敏。`.gitignore` 只是辅助，提交前仍要检查 diff 和待提交文件。

若问题涉及密钥泄漏或可利用漏洞，先通过维护者已公开的联系渠道说明问题，请勿在公开 Issue 中贴秘密或完整利用材料；若没有可确认的私密渠道，可先发不含敏感细节的联系请求。

## 当前 Alpha 的真实游戏实验边界

大多数贡献可用离线测试完成。以下只读要求针对当前 Alpha reader / bridge 实验，不是对未来功能的永久限制；未来若通过 FMAPI 等正式接口提供经授权的写入能力，应另行设计、审查和验证权限、确认与回滚机制。真实游戏实验不是普通测试命令的附带步骤：

- 仅使用合法取得且自己有权测试的游戏与数据。在自己的设备上自行测试无需逐次向维护者申请，但应事先明确测试范围、正常保存并备份，确认独立测试位置、变更清单与回滚办法。
- 操作他人的设备或数据，必须取得所有者对具体范围的明确授权。安装 loader、修改原始游戏安装、Steam 参数或系统权限，以及代为启动 / 重启游戏，不能从一次 PR 或历史实验推导出授权；自动化助手也不能自行扩大用户允许的范围。
- 不写入游戏状态，不绕过 DRM / 访问控制，不扩大原生调用范围；保持 unsupported 与 fail-closed 防线，不能移除平台拒绝来让测试“变绿”。
- 分清普通 reader、probe、metadata 和独立 UI candidate；没有对应阶段的新会话证据与授权，不自动晋级、重试或持续采样。
- 默认先用 fake / owned-buffer 测试验证预算、生命周期和失败路径。真实游戏实验遵守该候选的当前 runbook，不能照搬 Mac offsets、旧会话 HWND 或已消费请求。

参见 [Windows probe 边界](docs/bridge/windows-scheduler-probe.md)、[metadata candidate](modules/game-bridge/windows-smoke-draft/README.md) 与 [UI candidate](modules/game-bridge/windows-ui-smoke-draft/README.md)。这些文档描述实验方法，本身不授予安装或运行权限。

## 许可证与资源来源

项目根目录包含 [GNU GPL v3 许可证](LICENSE)。提交你有权贡献的内容；新增依赖或复用代码时，保留来源、版本、版权声明和原始许可证，并更新相关第三方记录。

**不要把所有字体、角色和第三方资源统一标成 GPL。** 第三方代码和字体保留各自条款；851 GBai Marker 字体有独立作者条款，角色与气泡资源的授权需单独说明。游戏名称、商标和游戏内容也不因本项目开源而获得再分发许可。不能确认来源或授权时，先讨论，不直接复制进仓库。

详见[依赖与许可证记录](docs/dependencies-and-licenses.md)和 [Companion 第三方声明](apps/companion/THIRD_PARTY.md)。收集 license 文件、通过测试或生成产物并不等于已经完成全部分发义务审查。

## PR 中写清楚这些就够了

- 改了什么，解决哪个问题，为什么采用这个方案。
- 影响哪些模块与平台，有没有数据 / 配置 / 契约兼容影响。
- 实际验证命令与结果，哪些是 fixture，哪些是真实环境，哪些还没验证。
- 如涉及交互，附脱敏前后截图；如引入依赖或资源，附来源和许可说明。

提交前运行 `git diff --check`，检查 staged diff 不含私有数据和无关文件。建议先开 Draft PR 方便讨论；没有完成的验收直接列出，不要为了“全绿”删除断言、关闭安全检查或淡化已知限制。
