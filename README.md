# FootballAssistant

FootballAssistant 是面向 Football Manager 的 AI 伙伴 Mod 与桌面玩具。macOS Apple Silicon 上已通过一条**实验性两字段端到端路径**：FM27 存档摘要 → Data Core → Agent → Electron 桌宠 → 中文 TTS，并验证基础对话在 SQLite 重启后持久化。

## 当前目标：持续监控 FM27 并验证完整数据接口

当前工作仍在进行中，不能标为完整数据接口已接通。私有副本上的自有 CoreCLR 入口与 Unity6.3 兼容的 Doorstop 4.6 已持续取样数百帧、多个只读页面约 3 秒一帧；Data Core 显示 connected/fresh，桌宠每 2 秒只读更新状态和事件。此流程未触发聊天模型；本轮 OpenCode Go 硬限额仍为 2/2。

目前得到的是受限的原始 UI 文本：经理页 34 项、球员列表页 37 项、球员页 80 项 UI 元素；可见姓名、位置、部分身高等原文字段，但列表/属性仍有遗漏，且有隐藏缓存文本混入。元素数量不能当作足球字段数量或完整数据覆盖率。管理对象静态清单 283,147 项与 native export 清单 16,613 项已各自完整枚举，当前经实测证据确认可读的条目仍为 0；这是待测清单规模，不是足球数据计数。

当前任务聚焦于逐个验证只读 getter/registry 的值与清理语义、native 返回值解码，以及完整的球队/球员结构化变化事件。Native forwarding shim 已独立通过玩具程序、并发、ASAN/TSAN 验证，尚未挂入 FM。Windows 游戏实机尚未验证。用户已授权在私有副本和正常保存的测试存档范围内迭代；授权不包含改原始游戏安装、Steam 启动参数、任意游戏写入或全局 OS 安全权限。

## 既有验证记录：早期存档 MVP

- UI 交叉核对的 FM27 样本只有两项摘要事实：`club_label=曼联`、`game_date=2026-07-13`。此严格 profile 针对存档 build `27.0.0+2486695` 和 schema 31。fmsave 0.7.0 的完整 FM26 reader 仍会拒绝 FM27；适配器仅使用它的 MIT 容器读取 API，加本项目独立 summary 解析器。
- 同 build 的后续存档只做格式/profile 校验，不继承首样本的 UI 核验；输出仍明确标为 experimental。它不提供球队实体 ID、球员名单/属性或实时内存数据。Snapshot 不是实时数据，刷新需要手动再次导入。
- 一次真实 OpenCode Go 模型回复引用这两项实验性摘要，在桌面 UI 显示并由中文系统 `say` 朗读（退出码 0）。真实对话写入 SQLite，并通过后端重启恢复检查。
- 最近一次验证有 47 项后端 pytest 与 5 项桌面端测试通过。早期端到端验证使用的本机两次模型请求硬限额已用完；这是之前服务预算的历史状态，不是当前 Runtime 监控会话的 Go 2/2 剩余限额。
- Electron macOS Apple Silicon 包在本机实测通过。Windows x64 ZIP 已构建且 CI 准备检查通过，但尚未在 Windows 实机运行。
- C# Runtime Bridge 已在受限私有副本上持续采样原始 UI 文本；结构化球队/球员数据接口仍未验证完整。静态清单已完整枚举，但经验证可读项为 0；native forwarding shim 尚未挂入 FM。

实机 M0 读取的安装版本为 FM27 `27.0.0.2486716`、Steam build `26227640`、Unity `6000.3.18f1-custom`，含 IL2CPP 与 arm64/x86_64 主程序。该 M0 build 标识与实验性存档中的 save build 分别记录，不能混为一谈。此前两字段存档实验的历史记录见下文；当前重点是 Runtime UI 数据的逐项验证。

## 导入真实存档摘要

只在 FM27 完成保存、文件稳定后显式导入；输入必须是存档文件。导入器检查源文件稳定性与哈希，创建受限的独立副本，再只读解析并将支持的事实写入本机后端。此操作不调用模型或改写原文件。

```sh
cd /path/to/FootballAssistant
uv run --frozen --extra save football-assistant-import-save \
  "$HOME/Library/Application Support/Sports Interactive/Football Manager 27/games/example.fm"
```

将示例路径替换为自己的存档路径；该导入流程对上述首个样本实测退出码为 `0`。成功后打开桌宠并聊天，可基于这份快照回复；保存新进度后需再次手动运行命令。退出码 `2` 表示格式/build 不受支持且没有事实被导入；`1` 表示稳定性、文件、后端或导入错误。未经 UI 逐份核对的新 snapshot 不得称为已交叉验证。

## 启动 Companion

```sh
cd /path/to/FootballAssistant
uv run --frozen --extra save python scripts/run_mvp.py --check
uv run --frozen --extra save python scripts/run_mvp.py
```

`--check` 只检查 `uv`、当前平台桌面包与后端健康状态，不启动或停止进程。默认命令复用健康的本机服务，或在未运行时启动服务并打开已打包桌宠。后端日志写入 `local-data/backend.log`；macOS 下目录属当前用户且权限为 `0700`，日志为 `0600`。缺少桌面包时，macOS 构建命令为 `cd apps/companion && npm ci && npm run pack:mac`，Windows x64 为 `cd apps/companion && npm ci && npm run pack:win`。

Companion 聊天明确显示模型或数据状态；打开桌宠本身不自动调用模型。模型调用硬限额当前已用完。更多接口、配置和限制见[后端 API 记录](docs/backend-api.md)。

## 模块

| 模块 | 技术 | 当前职责 |
| --- | --- | --- |
| Save Adapter | Python / fmsave 容器读取 API | 独立的严格 FM27 summary31/build profile，两项实验性事实；不冒充 FM26 full-reader 支持或实时数据。 |
| Data Core + Agent Core | Python、FastAPI、PydanticAI、SQLite | 观测来源校验，持久化事实和基础对话，调用 OpenAI 兼容服务。 |
| Companion | Electron / TypeScript | 桌宠、聊天 UI 与本机 TTS；复用 dsh-pet MIT 多屏几何代码，不复制其限制素材。 |
| Game Bridge / Runtime Adapter | C# / .NET、BepInEx 兼容接口 | 在私有副本运行并连续传输 `partial` UI 文本；结构化字段覆盖仍在验证，native forwarding shim 尚未接入 FM。 |

本地私有数据与构建产物由 `.gitignore` 排除；源码以 Git 提交保存。

## 项目记录

- [72 小时路线图](docs/roadmap.md)
- [架构](docs/architecture.md) 与 [模块边界](docs/module-boundaries.md)
- [依赖、复用与许可证](docs/dependencies-and-licenses.md)
- [参考实现评估](docs/reference-assessment.md)
- [Runtime Bridge 证据与限制](docs/runtime-bridge.md)
