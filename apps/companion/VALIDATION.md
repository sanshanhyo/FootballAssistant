# Companion MVP 验收记录

日期：2026-10-30。已打通真实 FM27 存档副本的两个实验性摘要字段到模型、桌宠和系统朗读；另已验证游戏内运行时 UI 原文连续上报到桌宠。真实模型问答验收的字段范围仍仅为球队标签和游戏日期；运行时原文采样没有冒充结构化阵容或球员属性。

| 检查 | 实际结果 |
| --- | --- |
| `npm run check` | JavaScript 语法检查通过，5 个行为测试通过，包括只读监听路由/游标请求约束 |
| 开发态 Electron 启动 | macOS arm64 / Electron 45.1.0 成功，renderer bridge 存在、`require` 未暴露 |
| 窗口 | `alwaysOnTop=true`；开发态与打包态 PNG 均为 RGBA，透明边角 alpha=0 |
| Electron 隔离 | `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true` |
| 实际界面交互 | Computer Use 操作伙伴收起/展开聊天、拖拽、中文消息输入与发送完成 |
| 本机后端连接 | 实际读取受限 runtime 文件连接 17827；后端重启/令牌轮换后自动恢复 |
| 缺模型配置 | 真实请求返回错误，界面显示“需要配置模型服务地址、模型名和 API Key。”，没有模拟模型回复 |
| 数据来源状态 | 初期 `save/unavailable/facts_count=0` 准确显示不可用；窄摘要适配后只读确认 `save/available/synthetic=false/facts_count=2`，界面显示存档快照 |
| macOS 中文 TTS | `createSpeech` 实际播放进程以 0 退出；系统 Tingting 生成 149784 字节 AIFF |
| Mac ARM64 打包 | `npm run pack:mac` 成功，Mach-O arm64；直接启动打包 `.app`，app.asar 页面与本机接口工作 |
| Windows x64 交叉打包 | `npm run pack:win` 在 Mac 成功，146 MB ZIP；EXE 为 PE32+ x86-64 |
| Windows CI 流程 | YAML 本地解析通过；包括 npm 测试、GameBridge .NET 10 离线传输 selftest、System.Speech 波形生成、x64 打包及实际 EXE 自退出 smoke；未推送或远程执行 |
| 真实模型与自动 TTS | 在打包 Mac 应用中仅发送一次获准请求，Go 真实回复“球队标签是曼联，游戏日期是 2026-07-13（实验性存档摘要）。”，自动 TTS 显示“朗读完成” |
| 基础记忆与额度 | 后端只读核对该次会话的 user/assistant 两条消息已持久化；测试预算恰为 2/2，没有重试或额外聊天 |
| 持续监听显示 | Mac 重包并正常重开后，真实本机 API 自动更新结构登记数量及 `interface_catalog_registered` 变化；随后真实运行时流从 0 变 1，经理中心观测约 34 个 UI 原文字段，接口探测数与实际观测字段数分别展示；没有新增模型请求或自动 TTS |
| 运行时页面变化 | 独立测试存档的一线队页约 37 个原文观测，哈里·马奎尔资料页约 80 个；自动产生 `ui_text_changed`，姓名富文本、位置、身高等与截图可对照。最后返回经理中心，日期仍为 2026-07-13 09:00 |

当前产物为本模块的 `dist/mac-arm64/FootballAssistant.app` 和 `dist/FootballAssistant-0.1.0-win-x64.zip`，均属于本地开发构建，未签名/公证、未发布。

实际截图、结构化 smoke 记录和 TTS 波形保留在本地未入库的验收证据目录，不包含访问令牌或模型密钥。PNG 由真实 Electron 窗口抓取；窗口与聊天错误另外用 Computer Use 核查。真实集成证据为 `e2e-status-before.json`、`e2e-reply.png`、`e2e-reply-ax.txt`；`e2e-result.json` 汇总结果并注明后端只读持久化核对的来源。

运行时采样目前只覆盖部分 UI 文本组件：一线队列表可见姓名、单人资料中的传球/头球等属性数值仍有遗漏，还会读到隐藏或缓存的旧面板文字。因此原文不是完整可见画面，也不是结构化足球对象。页面对照证据保留在本地未入库目录，包括 `private-roster.png`、`roster-api.json`、`private-player-profile.png`、`player-api.json` 和 `private-return-manager.png`。

尚待验证：完整的结构化球队/球员事实、Windows 实机运行、FM27 全屏空间中的叠加行为、多显示器热插拔实机行为。两个摘要字段经本机样本与只读游戏画面核对，不能推定其他 FM27 存档或版本兼容。Windows 交叉构建不能代替 Windows 实机运行。Mac 未签名开发包的本机启动也不能代替分发签名验证。

用户的模型额度有限；后续真实聊天请求仅由主线程协调，不运行自动发送循环。
