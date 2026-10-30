# MVP 路线图与验收记录

早期 72 小时 MVP 的目标日期为 2026-11-01（Asia/Shanghai）；存档摘要端到端记录仍保留为阶段历史。当前 active goal 是持续监控 FM27 并验证完整只读数据接口；目标尚未完成。以下状态按本轮实际证据更新。

| 状态 | 模块 | 验收与当前边界 |
| --- | --- | --- |
| 完成 | M0 FM27 实机识别 | 安装版本 `27.0.0.2486716` / Steam build `26227640`；Unity IL2CPP；Mac 主程序 arm64 与 x86_64。检查时游戏进程运行，但未附加。 |
| 完成，范围受限 | Save Adapter → Data Core | 首个稳定 FM27 存档副本经严格 schema 31 / save build `27.0.0+2486695` summary profile 导入；源文件未改写。fmsave 0.7.0 仅作 MIT 容器读取器，其标准 FM26 完整 reader 会拒绝 FM27。 |
| 完成，实验性 | 摘要 → Agent → Electron → TTS | 首个 profile 样本经游戏 UI 核对：`club_label=曼联`、`game_date=2026-07-13`。真实模型回复“球队标签是曼联，游戏日期是2026-07-13（实验性存档摘要）”，桌宠显示并由 macOS 中文 `say` 朗读，退出码 0。 |
| 完成 | 基础记忆 | 上述成功聊天写入 SQLite，服务重启后可恢复。 |
| 完成 | Companion | macOS Apple Silicon Electron 包实机运行通过；dsh-pet MIT 几何改编已带来源与许可文本。 |
| 完成，未在目标平台运行 | Windows 桌面包 | Windows x64 ZIP 交叉构建与 CI 准备流程检查通过；没有 Windows 实际运行证据。 |
| 正在运行，部分能力 | Runtime UI 文本监控 | 在私有副本上使用 Doorstop 4.6 对 Unity 6.3 的适配与自有 CoreCLR C# 入口；Unity CF 主线程 timer 约每 3 秒取样。已连续观察数百帧和多个只读页面，Data Core 为 connected/fresh；桌宠每 2 秒只读轮询状态/事件。采样是 `partial` UI 文本，不是完整结构化接口。 |
| 已盘点、待逐项验证 | managed/native 静态清单 | managed 283,147 项、native exports 16,613 项已各自完整枚举；当前经实测证明可读项为 0。清单总数不是足球字段数量。Registry count/proof/cleanup 阶段通过审阅，独立 getter/registry runtime probe 待实测。 |
| 部分原始 UI 覆盖 | 页面采样结果 | 经理页 34、Roster 页 37、Player 页 80 个 UI 元素；能读到姓名/位置/部分身高原文，名单与部分属性有遗漏，也混入隐藏缓存文本。这些是元素数量，不是已验证数据字段数。 |
| 独立验证，尚未挂入 FM | Native forwarding shim | 玩具程序、并发、ASAN/TSAN 验证通过；尚无 FM hook，native 返回语义还未解码。 |
| 持续中，Mac 有界授权 | Runtime 真实接入 | 用户已允许在私有副本、正常保存的测试存档范围内迭代。权限不覆盖修改原始安装、Steam 启动参数、任意游戏写入或全局 OS 安全权限。球队/球员完整 IdentifierSet 枚举、native 返回值语义、全域结构化事件仍未完成。 |
| 待平台验证 | Windows Runtime | 尚无 Windows x64 游戏实机验证；离线自测或 Mac 观察不能代替此项。 |

已验证的真实存档端到端能力仅两项 experimental summary 值。首样本 SHA 有 UI 交叉核验证据；后续同 build/schema 的新存档仅通过 format/grammar 检查，不继承首样本核验结果，也不被称为逐份 UI 验证。没有球员/阵容/属性或实时内存读取。

最近一次验证有 47 项后端 pytest 与 5 项桌面端测试通过。早期存档 MVP 端到端使用了两次真实 OpenCode Go 请求并完成当时的两次调用硬限额；它与当前 Runtime 监控会话分开。本轮持续监控没有调用聊天模型，当前 Go 配额为 2/2。服务仅更新来源状态/事件，`--check`、采样和桌宠监控都不触发模型。
