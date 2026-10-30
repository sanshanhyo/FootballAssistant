# Companion 前端阶段记录

日期：2026-10-30。开发分支：`feat/companion-ui`。起点：远程 `main` 的 `f7d1055eaac31cef1af3559195dadd94b239089f`。本阶段沿用 Electron，后端由 reader-semantics／后端开发线负责；不修改采集、协议解码或 Reader 数据模型。

## 设置分离与输入条调整

本轮从 `3fe586434ea5d4d0a82e1304243c0eb37ea8adde` 继续，按用户提供的两张截图将原桌宠管理面板移入正式设置窗口。单击桌宠只展开横向文字输入条，右侧为发送按钮；消息、工具状态和信息卡继续由桌宠气泡展示。输入条不再承载连接、语音、表情或记录管理控件。

设置通过系统托盘／菜单栏或桌宠右键打开，独立窗口集中管理连接与模拟示例、语音服务选择、主动性与表情、聊天历史和显式记忆。设置窗口后打开时，从完整 state 恢复当前消息和工具状态，随后接收与桌宠相同的事件；清除历史、新对话及模式切换同时更新两窗口。

`state.preferences` 为 `{expression, sttProvider, ttsProvider}`。`setPreferences(patch)` 只接受固定键及预定义枚举，不接受服务 URL、可执行文件或密钥。偏好单独持久化，不依赖是否开启聊天历史；语音 provider 变更会停止主进程音频任务，并由共享偏好变化使桌宠取消录音／转写／播放，防止旧操作继续。主动性仍默认 80%。设置点击停止语音会额外通知桌宠释放本地录音／播放器；桌宠自身的停止请求不回送停止事件，避免迟到回声取消下一次语音操作。

设置窗口有独立的 preload 角色和 IPC 白名单，可以管理记录、取消已有工具请求和停止语音；不能发送聊天、请求麦克风、转写、播报或拖动桌宠。主进程同时核对发起窗口、主 frame 与精确本地页面 URL。设置页面的媒体权限始终拒绝。

本地语音转文字本轮只做方案研究；没有下载模型、安装识别引擎或把未实现的本地服务显示为可用。现有 STT 服务配置与明确模拟模式保持原合同。

建议后续使用 [whisper.cpp](https://github.com/ggml-org/whisper.cpp) 的 multilingual `small` 作为跨 macOS／Windows 的离线起点；官方模型表中未量化权重为 466 MiB。按住录音、松手整段识别可复用现有交互，但需要将 MediaRecorder 音频正确转换为 16 kHz、单声道、16-bit PCM WAV，并由主进程使用固定识别程序、固定模型路径及模型校验；不让 Renderer 指定任意命令。实际中文、英文球员姓名效果、内存与延迟尚未测试，不能把模型可用视为本机体验已经达标。

## 本阶段范围与默认值

- 启动默认 **模拟模式**，不读取旧 `runtime.json`，不连接本机后端、游戏或聊天模型。明确切换真实模式时显示“后端尚未接入”，不会偷偷回退到模拟回复。
- 桌宠与设置分别为独立窗口。菜单栏（macOS）／系统托盘（Windows）提供显示、隐藏、设置与退出；右键桌宠也能打开设置。管理控件集中于设置窗口，桌宠仅保留消息气泡、横向输入条和角色交互。
- 单击桌宠打开横向文字输入条，右侧发送；长按启动麦克风录音，松手停止并转写到**可编辑草稿**，用户检查后手动发送。拖动超过阈值进入拖动，取消长按识别，避免误录音；Escape 可取消。
- 文本输出使用对话框，支持用户回复、主动消息、工具进度和观测卡。人格正文、最终角色素材及对话框素材等待用户提供；占位资源不确立伙伴身份。
- 表情由交互状态驱动，也可通过预览切换。音频播放默认手动触发，不因新消息、数据事件或启动而自动播报。
- 主动性默认 **80%**，前端可调整并保存。当前只演示显式触发的模拟主动消息，不把 80% 擅自定义为随机丢弃通知的算法；正式事件触发策略由后端接入时协调。
- 聊天历史与长期记忆分开。聊天默认仅在进程内保留，用户开启“保留历史”后才跨启动保存；历史可清空。长期记忆仅由用户明确保存，可查看及逐条删除，没有自动摘要、自动提炼记忆。
- 不增加本地模型费用上限；云端额度、认证及服务错误按实际结果显示。
- 转会、提交阵容、推进日期等动作不接入，界面中的动作执行保持不可用。

## 前端边界与事件合同

桌宠展示／输入 → 固定 preload IPC → 主进程 CompanionRuntime、语音服务及 ReaderClient 适配器。Renderer 保持 `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`，不持有服务密钥、不直接访问任意网络或 shell。TTS 的系统命令与可选 Edge CLI 为主进程固定实现，聊天文本不能指定可执行文件或参数模板。

`window.companion` 只暴露命名方法，所有调用返回 `{ok:true,value}` 或 `{ok:false,error,code?}`。没有通用 invoke、文件读取、任意命令或任意 URL 接口。

- 会话：`getState`、`setMode`、`sendMessage`、`cancelRequest`、`newConversation`、`setProactivity`、`setPreferences`、`simulateEvent`。
- 记录：`getHistory`、`clearHistory`、`setHistoryEnabled`、`getMemories`、`saveMemory`、`deleteMemory`。
- 窗口：`openSettings`、`showContextMenu`、`dragStart/Move/End`、`inputRects`、`quit`。
- 语音：`speechCapabilities`、`microphonePermission`、`transcribe`、`cancelSpeechOperation`、`speak`、`stopSpeech`。
- 订阅：`subscribe(callback)` 返回取消订阅函数；事件包含 `state`、`message`、`tool`、`request`、`speech`、`visibility` 和 `stop-speech`。

以上是桌宠角色的接口全集。设置角色仅获得固定管理子集；`sendMessage`、麦克风权限、`transcribe`、`speak`、单项语音操作取消、右键菜单与拖动接口仅桌宠可用。`state.tools` 保存当前会话工具快照及完整来源元数据，包含完成／取消／失败终态，供后打开的设置窗口恢复；会话切换时清空。

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

新记录保存在 Electron userData 下 `companion-ui.json`，含版本、主动性、界面与语音偏好、用户选择保留的历史及显式记忆，使用临时文件加替换写入。退出前等待排队写入。旧版本没有偏好字段时使用明确的默认值，未知或不支持的偏好忽略，不升级为任意配置。

旧 Renderer localStorage 的 conversation ID／事件游标，以及后端 SQLite 历史，均不自动导入新会话或当作长期记忆；旧数据不被覆盖。损坏或过大的新记录文件会产生可见警告并保留原文件，避免启动即覆写。

测试应设置 `FA_COMPANION_USER_DATA_DIR` 为独立绝对路径；主进程创建该目录并覆盖 userData，避免测试读取或清空用户的真实聊天、记忆及配置。例如在系统临时目录创建一次性测试目录，再用该变量启动 Electron。`FOOTBALL_ASSISTANT_SMOKE_REPORT` 可指定仓库外 smoke JSON 路径；配合 `FOOTBALL_ASSISTANT_SMOKE_EXIT=1` 可在截图后退出。

`node test/electron-smoke.cjs` 是可复用的手动离线回归，不在 `*.test.cjs` 中，也不被产品打包。它使用已有 Playwright（可通过 `FA_PLAYWRIGHT_MODULE_PATH` 指定模块）与 Electron（可通过 `FA_ELECTRON_EXECUTABLE` 指定）；没有增加依赖。每次运行创建系统临时目录、隔离 userData、清除语音配置、阻止主进程 fetch／浏览器网络及外部语音进程，并使用 Chromium 假媒体设备和权限桩。其 6 项检查已经通过，网络／外部进程尝试及 Renderer 错误均为 0。它不使用用户的真实麦克风，也不代表系统权限框实测。

## 验收记录

本文件中的测试记录仅代表本分支实际完成的检查，不能沿用早期版本的真实模型／游戏验证作为新功能通过证据。

首轮提交 `3fe5864` 的 `npm run check` **32/32 通过**。macOS arm64／Electron 45.1.0 开发态 GUI 分三轮完成 **36/36 检查**，打包 Mac smoke **2/2 通过**；相关 pageerror／console error 均为 0。Browser plugin 不可用，因此使用 Playwright Electron 路径。另执行入库的可复用离线 smoke，**6/6 通过**。这些 GUI 录音检查使用假媒体设备与权限桩，未调用真实后端、模型、云服务或系统语音。

本轮 `npm run check` **37/37 通过**，包含新 `settings.js` 语法检查；其中 runtime／安全测试 **13/13 通过**，增加跨窗口偏好广播及持久化、原子白名单校验、设置后开恢复工具及取消终态、设置与桌宠角色权限隔离，以及设置停止语音通知与桌宠停止不回声。

正式设置与新输入条的双窗 GUI **28/28**，额外录音／已开始的假 Audio 清理 **3/3**，合计 **31/31 通过**；Mac 打包应用的双窗 smoke **4/4 通过**，pageerror／console error 均为 0。验证了横向输入条及中文输入法回车、各设置分类、共享偏好、完整来源信息、两窗口记录／会话同步、设置停止录音与播放器、取消转写上传和设置角色拒绝麦克风及禁止 IPC。测试只使用假媒体、隔离 userData 与阻断网络／外部语音进程的夹具，不代表真实麦克风或服务通过。

可复用 `node test/electron-smoke.cjs` 已适配新桌宠／设置选择器，**6/6 通过**，退出码 0，网络／外部进程尝试及 Renderer 错误为 0。其六项为明确模拟启动、单击聊天及来源卡、设置切换后端隔离旧回复、显式记忆独立删除、模拟录音草稿、离线与控制台检查。这是完整 GUI 的子集；跨窗口语音选择会等待桌宠实际应用共享状态并恢复窗口焦点，再执行假媒体长按。脚本仅使用 fake-device，没有使用会绕过权限判断的 fake-ui 参数。

本轮 Mac ARM64 与 Windows x64 ZIP 均构建成功；Mac 包已实际运行，Windows 未实机运行。两个 `app.asar` 的全部 17 个 `src` 文件 SHA256 与冻结源码一致，运行时 package 元数据一致；builder 正常剥离开发／构建字段，不做 package 文件逐字节相等的错误断言。此后仅更新未被 builder 收录的文档和 smoke 脚本，未改产品源码。当前预览输出为 ignored `apps/companion/dist/companion-pet-preview.png` 和 `companion-settings-preview.png`，已实际查看；详细离线 QA 证据保留于 `/tmp/football-companion-dualwindow-qa-20261030/`。真实麦克风／系统授权框、云端 STT／TTS／Edge、真实后端、Windows 实机、完整人工托盘操作、游戏全屏及多显示器仍未验证；本轮未安装 whisper.cpp 或模型。

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
