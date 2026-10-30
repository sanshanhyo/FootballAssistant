# Companion 前端阶段记录

日期：2026-10-30。开发分支：`feat/companion-ui`。起点：远程 `main` 的 `f7d1055eaac31cef1af3559195dadd94b239089f`。本阶段沿用 Electron，后端由 reader-semantics／后端开发线负责；不修改采集、协议解码或 Reader 数据模型。

## 本阶段范围与默认值

- 启动默认 **模拟模式**，不读取旧 `runtime.json`，不连接本机后端、游戏或聊天模型。明确切换真实模式时显示“后端尚未接入”，不会偷偷回退到模拟回复。
- 桌宠与设置分别为独立窗口。菜单栏（macOS）／系统托盘（Windows）提供显示、隐藏、设置与退出；右键桌宠也能打开设置。设置窗口只有说明占位，具体设置内容留待后续。
- 单击桌宠打开文字输入；长按启动麦克风录音，松手停止并转写到**可编辑草稿**，用户检查后手动发送。拖动超过阈值进入拖动，取消长按识别，避免误录音；Escape 可取消。
- 文本输出使用对话框，支持用户回复、主动消息、工具进度和观测卡。人格正文、最终角色素材及对话框素材等待用户提供；占位资源不确立伙伴身份。
- 表情由交互状态驱动，也可通过预览切换。音频播放默认手动触发，不因新消息、数据事件或启动而自动播报。
- 主动性默认 **80%**，前端可调整并保存。当前只演示显式触发的模拟主动消息，不把 80% 擅自定义为随机丢弃通知的算法；正式事件触发策略由后端接入时协调。
- 聊天历史与长期记忆分开。聊天默认仅在进程内保留，用户开启“保留历史”后才跨启动保存；历史可清空。长期记忆仅由用户明确保存，可查看及逐条删除，没有自动摘要、自动提炼记忆。
- 不增加本地模型费用上限；云端额度、认证及服务错误按实际结果显示。
- 转会、提交阵容、推进日期等动作不接入，界面中的动作执行保持不可用。

## 前端边界与事件合同

桌宠展示／输入 → 固定 preload IPC → 主进程 CompanionRuntime、语音服务及 ReaderClient 适配器。Renderer 保持 `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`，不持有服务密钥、不直接访问任意网络或 shell。TTS 的系统命令与可选 Edge CLI 为主进程固定实现，聊天文本不能指定可执行文件或参数模板。

`window.companion` 只暴露命名方法，所有调用返回 `{ok:true,value}` 或 `{ok:false,error,code?}`。没有通用 invoke、文件读取、任意命令或任意 URL 接口。

- 会话：`getState`、`setMode`、`sendMessage`、`cancelRequest`、`newConversation`、`setProactivity`、`simulateEvent`。
- 记录：`getHistory`、`clearHistory`、`setHistoryEnabled`、`getMemories`、`saveMemory`、`deleteMemory`。
- 窗口：`openSettings`、`showContextMenu`、`dragStart/Move/End`、`inputRects`、`quit`。
- 语音：`speechCapabilities`、`microphonePermission`、`transcribe`、`cancelSpeechOperation`、`speak`、`stopSpeech`。
- 订阅：`subscribe(callback)` 返回取消订阅函数；事件包含 `state`、`message`、`tool`、`request`、`speech`、`visibility` 和 `stop-speech`。

每次模式、后端标识或会话切换都会增加 `epoch`、生成新 `sessionId`、取消旧任务与语音。消息／工具事件带原请求、会话与 epoch；异步结果只有仍属于当前请求及会话时才能进入界面。并行请求保持独立 requestId，最多同时四个；旧请求返回不能覆盖新会话。

信息卡与消息保留 `metadata.source`、`sourceLabel`、`sessionId`、`sampledAt`、`partial`、`limitations`、`synthetic` 和 `freshness`。未知值保留 `null`，展示为未知，不能补成零。模拟卡包含缓存 UI 限制说明，不把原文解释为确认的当前球员属性；不存在的实体 ID 或字段含义不由前端补造。游戏文本只作为数据展示，不转换成系统指令。

`MockReaderClient` 与未连接的真实适配器具有相同展示边界。真实适配器本阶段不执行网络请求，功能状态为不可用／未知。watch 属于客户端订阅，具备取消生命周期；不会作为一次无限模型工具调用，也不会启动真实 watch。

## 语音配置

录音只在用户明确长按时开始。麦克风权限只允许本地桌宠主页面、主 frame、audio-only；摄像头、屏幕捕获、子 frame、设置窗口等请求均拒绝。Electron 的 request handler 使用 `mediaTypes:['audio']`，check handler 使用 `mediaType:'audio'`。macOS 包增加 `NSMicrophoneUsageDescription`。

当前分支保留原系统 TTS，并增加可选 Edge、OpenAI 兼容 TTS、Azure TTS 与 OpenAI 兼容 STT。基线仓库原实现只有系统 TTS，未找到已有 Edge 适配；本阶段新增的 Edge 路径不能宣称为已验证可用的既有功能。

主进程从环境读取配置，Renderer 只看到服务是否可用及安全原因，不接收密钥或基础地址。配置变更后重启应用生效。

| 环境变量 | 用途 |
| --- | --- |
| `FA_SPEECH_OPENAI_BASE_URL` | OpenAI 兼容语音服务地址，默认 `https://api.openai.com/v1`；HTTPS 或本机 HTTP |
| `FA_SPEECH_OPENAI_API_KEY` | 对应语音服务密钥 |
| `FA_SPEECH_STT_MODEL` | STT 模型，未配置时明确不可用 |
| `FA_SPEECH_TTS_MODEL` | TTS 模型，未配置时明确不可用 |
| `FA_SPEECH_TTS_VOICE` | OpenAI 兼容 TTS 音色，默认 `alloy` |
| `FA_SPEECH_AZURE_KEY`、`FA_SPEECH_AZURE_REGION` | Azure TTS 密钥及区域 |
| `FA_SPEECH_AZURE_VOICE` | Azure 音色，默认 `zh-CN-XiaoxiaoNeural` |
| `FA_SPEECH_EDGE_PATH` | 可选 Edge CLI 的绝对路径；否则在主进程 PATH 中探测 `edge-tts` |
| `FA_SPEECH_EDGE_VOICE` | Edge 音色，默认 `zh-CN-XiaoxiaoNeural` |
| `FOOTBALL_ASSISTANT_TTS_VOICE` | 原有 macOS 系统 TTS 声音，默认 `Tingting` |

STT 服务未配置时不会悄悄返回模拟转写。只有明确选择模拟转写才会显示“模拟转写，未识别录音”；模拟播报不生成音频。真实云服务、音色或 CLI 缺失时保留原错误状态，不自动改走别的 provider。录音编码采用实际 MediaRecorder MIME，不冒充 WAV；上传大小与服务响应均有限制，操作支持取消和超时。云音频经 IPC 返回 ArrayBuffer，由 Renderer 使用 Blob 播放，结束／取消后释放对象 URL。

可选 Edge 依赖外置 `edge-tts` CLI，不随应用打包或自动安装。STT 最大 20 MB，支持实际 MIME 为 webm／ogg／mp4／mpeg／wav／flac；服务超时 45 秒。TTS 最长 12000 字，OpenAI 兼容接口额外限制 4096 字，音频响应最大 20 MB。

## 本地记录与旧版本数据

新记录保存在 Electron userData 下 `companion-ui.json`，含版本、主动性、用户选择保留的历史及显式记忆，使用临时文件加替换写入。退出前等待排队写入。

旧 Renderer localStorage 的 conversation ID／事件游标，以及后端 SQLite 历史，均不自动导入新会话或当作长期记忆；旧数据不被覆盖。损坏或过大的新记录文件会产生可见警告并保留原文件，避免启动即覆写。

测试应设置 `FA_COMPANION_USER_DATA_DIR` 为独立绝对路径；主进程创建该目录并覆盖 userData，避免测试读取或清空用户的真实聊天、记忆及配置。例如在系统临时目录创建一次性测试目录，再用该变量启动 Electron。`FOOTBALL_ASSISTANT_SMOKE_REPORT` 可指定仓库外 smoke JSON 路径；配合 `FOOTBALL_ASSISTANT_SMOKE_EXIT=1` 可在截图后退出。

`node test/electron-smoke.cjs` 是可复用的手动离线回归，不在 `*.test.cjs` 中，也不被产品打包。它使用已有 Playwright（可通过 `FA_PLAYWRIGHT_MODULE_PATH` 指定模块）与 Electron（可通过 `FA_ELECTRON_EXECUTABLE` 指定）；没有增加依赖。每次运行创建系统临时目录、隔离 userData、清除语音配置、阻止主进程 fetch／浏览器网络及外部语音进程，并使用 Chromium 假媒体设备和权限桩。其 6 项检查已经通过，网络／外部进程尝试及 Renderer 错误均为 0。它不使用用户的真实麦克风，也不代表系统权限框实测。

## 验收记录

本文件中的测试记录仅代表本分支实际完成的检查，不能沿用早期版本的真实模型／游戏验证作为新功能通过证据。

本轮 `npm run check` **32/32 通过**。macOS arm64／Electron 45.1.0 开发态 GUI 分三轮完成 **36/36 检查**，打包 Mac smoke **2/2 通过**；相关 pageerror／console error 均为 0。Browser plugin 不可用，因此使用 Playwright Electron 路径。另执行入库的可复用离线 smoke，**6/6 通过**。这些 GUI 录音检查使用假媒体设备与权限桩，未调用真实后端、模型、云服务或系统语音。

独立工作区首次安装时 Electron 的安装脚本未执行，已使用锁定版本的 `node node_modules/electron/install.js` 补齐本地运行时，没有改动全局 npm 策略、package 或 lock。随后实际 `npm start` 使用独立 userData 和清空云配置的环境启动并以 0 退出；`dev-start.json` 确认 Electron 45.1.0、mock、synthetic=true、bridge=true、nodeExposed=false。该启动没有调用后端、模型、麦克风或云语音。

| 场景 | 本阶段证据与状态 |
| --- | --- |
| 默认启动不连接真实服务／模型 | Runtime 单测、开发态 Electron 与打包 Mac smoke：默认 mock，无自动请求、开麦或播报 |
| 服务未启动／连接失效 | 真实适配器明确 unavailable，不回退 mock；真实断线恢复待后端接通验收 |
| 切换模拟／真实／后端标识 | Runtime 单测验证 epoch／session 更新与明确模式信息 |
| 旧请求迟到、取消、并行消息 | Runtime 单测：忽略 abort 的旧 transport 仍无法污染新会话；并行回复保留 requestId |
| 缺失／过期／模拟数据 | Runtime 单测：null 未知值、过期时间和完整来源元数据保持 |
| 聊天历史与显式记忆 | Runtime 单测：历史跨启动须 opt-in，清空聊天不删除记忆，记忆可逐条删 |
| 损坏本地记录 | Runtime 单测：警告且保留原文件 |
| 麦克风权限策略 | Runtime 单测：Electron 两种权限 shape、audio-only、主 frame 与可信页面限制 |
| 云语音请求格式／错误／取消 | Speech 专用测试使用注入 transport／进程 fixtures，不产生真实云调用 |
| 实际麦克风与操作系统授权框 | 未验证；不能以模拟媒体 fixture 或 provider 单测代替 |
| 实际云 STT／TTS、Edge 音色 | 未验证；未使用真实密钥／未产生服务请求 |
| macOS 原生窗口与托盘生命周期 | Electron 窗口隔离／透明／置顶与关闭后隐藏通过；右键菜单仅验证受控 popup 路由和菜单项，不宣称完整系统托盘人工验收 |
| 拖动、点击与长按 | GUI 验证拖动手势抑制录音且不误点开面板、长按假媒体录音及松手草稿；未断言实际操作系统窗口位移 |
| 小屏显示 | 340×570 窗口验证无横向溢出，展开面板可滚动；截图已人工查看 |
| 取消与语音终态 | GUI 验证 Escape／provider 切换、编码迟到、录音初始化失败时释放 tracks、工具取消终态及 TTS 先终态后 IPC 返回 |
| Windows 运行／系统权限框／游戏全屏／多显示器 | 未验证；交叉构建与假媒体回归不能替代 |
| 最终角色／对话框素材及人格 | 等待用户提供，当前为可替换占位 |

本阶段不变更依赖版本。构建／测试命令仍在 `apps/companion` 下使用 `npm run check`、`npm run pack:mac`、`npm run pack:win`；构建成功不等于实际麦克风、云端语音或 Windows 运行通过。

最终版本仍为 `0.1.0`。Mac ARM64 开发包 `apps/companion/dist/mac-arm64/FootballAssistant.app` 和 Windows x64 ZIP `apps/companion/dist/FootballAssistant-0.1.0-win-x64.zip` 构建成功；前者 Mach-O arm64、后者 EXE 为 PE32+ x86-64。Mac Info.plist 已包含麦克风用途说明。两个平台 `app.asar` 中的 `main.cjs`、`renderer.js`、`speech-service.cjs` SHA256 均与最终工作区源码一致；随后新增的验收脚本／文档不在 builder files 中，没有改变产品源码。Mac 未签名／公证，Windows 没有实机运行证据。

本地 GUI 证据保留于未入库目录 `/tmp/football-companion-qa-20261030/`：`report.json`、`regression-report.json`、`terminal-report.json`、`packaged-report.json`、`dev-start.json`。实际打包预览为 `16-packaged-pet-preview.png`，展开对话预览为 `14-packaged-chat-preview.png`；另复制到工作区 ignored 输出 `apps/companion/dist/companion-ui-preview.png`、`companion-chat-preview.png`。角色与气泡为当前占位资源，截图检查不代表最终素材验收。

## 后端／Reader 协调需求

以下为未来接入需求，本分支不修改后端来满足它们。

1. 提供稳定的能力清单与版本：status、snapshot、raw-ui、event、native 的可用性／限制，以及 player-query 是否存在；缺失能力应为 unsupported 或 unknown，不能从接口目录规模推断。
2. 提供服务实例及会话／事件历史重置标识，配合前端 epoch 防止后端切换、游标重置或旧请求造成上下文混用。
3. Reader 完整观测信封必须进入 Agent 工具结果，保留来源、采样时间、partial、limitations、synthetic 和会话；缓存 UI 与已确认语义事实有清楚界限。
4. Agent 提供有限请求的工具进度、消息／主动消息及取消合同。Reader watch 由客户端持有订阅生命周期，不能把无限循环包装成单次模型工具调用。
5. 球员等语义对象只消费 Reader 已验证的字段、实体 ID 及范围，不由模型或桌宠自行创造含义。未来动作需独立 action 工具及确认、校验、结果核验，本阶段没有执行入口。
6. 协调长期记忆与历史的真实持久化接口及删除语义；前端显式记忆不自动回灌为系统指令。主动性 80% 的含义、事件类别和通知节制策略另行定义。
