# Companion MVP

72 小时冲刺先采用 Electron，Flutter 延期。当前实现透明置顶足球伙伴、拖动、透明余量点击穿透、中文聊天与服务/数据来源状态、持续监听显示、系统 TTS 和会话标识恢复。窗口只访问本机 Python 服务，不读游戏、存档或模型密钥。人格、事实和 SQLite 记忆由 Python 服务负责。

## 开发运行

需要 Node.js ≥22.12。先在仓库根目录启动后端 `uv run football-assistant-backend`，再在本目录运行：

```sh
npm ci
npm start
```

开发态默认读取仓库的 `local-data/runtime.json`，令牌仅由 Electron 主进程持有。可以设置 `FOOTBALL_ASSISTANT_RUNTIME_FILE` 为服务连接文件的绝对路径，或在窗口中点击“选择连接文件”。已选择的文件路径保存在本机应用配置中，不保存令牌副本。打包应用首次运行时可能需要选择连接文件。

聊天按 Enter 发送、Shift+Enter 换行；点击伙伴收放聊天框，按住伙伴拖动。若模型未配置、服务失联、数据尚未接入或仅有合成数据，界面会明确显示，不能把这些状态视为真实 FM27 已接通。

监听区每 2 秒只读更新本机 `/v1/monitoring` 和带游标的 `/v1/events`，独立于聊天；默认显示连接、最近更新时间和最近显式探测的已验证数据状态，接口结构数量、探测数及目录完整性收在“开发诊断”中。原生包头接收不等于字段值已解码，业务数据仍部分待解码；结构登记和最近探测均不代表当前会话或持续采集。页面原文或原始字段变化只作低层提示，不自动认作进球、转会或伤病事件，也不会触发模型或 TTS。

## 朗读

macOS 调用系统 `/usr/bin/say`，默认中文 `Tingting`，可通过 `FOOTBALL_ASSISTANT_TTS_VOICE` 指定已安装声音（`say -v '?'` 可查看）。Windows 使用系统 PowerShell / System.Speech，优先选择已安装的中文声音。中文声音的实际可用性取决于系统配置。

朗读文本只通过子进程标准输入传递，不拼接进命令或脚本。可停止本应用启动的朗读进程；不会停止其他应用的语音。朗读失败会显示错误，不影响已取得的聊天回复。

## 验证与打包

```sh
npm run check
npm run pack:mac
npm run pack:win
```

Mac 产物为 `dist/mac-arm64/FootballAssistant.app`，当前开发包未签名、未公证。Windows 产物为 x64 ZIP；`.github/workflows/desktop.yml` 提供 macOS/Windows 的安装、测试、打包和 Windows 系统 TTS 波形验证流程。尚未执行的 CI 或 Windows 运行不得算作已通过；实际验收见冲刺记录。

测试覆盖本机地址约束、令牌轮换、模型错误传递、TTS 文本不进入命令参数、停止语音、多屏空洞与恢复。Electron 运行时还需实际验证窗口、拖拽、焦点和系统朗读。

## 复用边界

真正复用了 `dsh-pet` 的 MIT 多显示器几何代码，并参考其主进程指针轮询/穿透策略，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。MIT 原文与原作者版权随应用保留。没有导入上游角色、动画、提示词、字体、视频或其他限制素材；当前足球伙伴由本项目 CSS 几何绘制。

不包含复杂成长、长期语义检索、多宠物、语音识别或游戏自动操作。基础记忆在后端持久保存，会话标识在本机窗口恢复。
