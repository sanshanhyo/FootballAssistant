# Companion 前端

沿用 Electron 的桌宠前端阶段：默认明确标记为模拟模式，提供消息气泡、表情切换、文字输入、按住说话、语音播报接口、工具进度、信息卡，以及分开管理的聊天历史与显式记忆。角色、人设和对话框为可替换占位，等待用户素材。后端由另一开发线提供，本阶段启动不连接游戏、Reader 或聊天模型。

## 开发运行

需要 Node.js ≥22.12。在本目录执行：

```sh
npm ci
npm start
```

若当前安装环境跳过了 Electron 安装脚本，导致运行时文件缺失，可在本目录执行 `node node_modules/electron/install.js` 补齐锁定版本，再运行 `npm start`；本轮已完成该修复并验证实际启动，无需修改全局 npm 配置。

无需启动后端。单击桌宠只展开横向输入条，右侧发送；长按说话，松手后转写进入可编辑草稿，检查后手动发送；拖动移动，右键打开设置。应用常驻 macOS 菜单栏／Windows 系统托盘，关闭桌宠会隐藏，退出使用菜单或设置按钮。

连接与模拟示例、语音服务选择、陪伴与表情、历史与记忆集中于独立设置窗口。设置中的偏好会即时同步桌宠并保存，桌宠消息气泡保留回复、工具进度、信息卡及其来源限制。

主动性默认 80%，仅作为待后端使用的偏好保存，模拟主动消息通过按钮演示。切换“真实后端”会明确显示尚未接入，不会自动返回模拟回复。新对话或切换后端会取消旧请求和语音；信息卡保留来源、采样时间、会话、未知／过期／部分／模拟标记。

聊天历史默认只在进程内保留，勾选后才跨启动保存。显式记忆由用户逐条保存、查看和删除；清空聊天不删除记忆。旧版 localStorage 和后端历史不会被自动导入或覆盖。

## 语音

保留原有 macOS 系统 `say`／Windows `System.Speech`，新增可选 Edge CLI、OpenAI 兼容 TTS、Azure TTS 和 OpenAI 兼容 STT。只有手动点击“读回复”才播报。云服务未配置、Edge 未安装时明确不可用，不自动切换供应商；模拟转写与模拟播报持续标明并非真实识别／音频。

语音服务的密钥配置仅由主进程读取环境变量，密钥不进入 Renderer。设置中可以选择服务，但没有密钥编辑功能。本地转写方案仍在选型，没有自动下载模型或显示未实现服务为可用。配置项、请求边界、接口合同及完整验收记录见 [Companion 阶段记录](../../docs/companion-ui.md)。

## 验证与打包

```sh
npm run check
npm run pack:mac
npm run pack:win
```

Mac 开发包为 `dist/mac-arm64/FootballAssistant.app`，Windows 为 `dist/FootballAssistant-0.1.0-win-x64.zip`。当前版本 `0.1.0`，Mac 包未签名／公证；Windows 交叉构建不代表 Windows 实机验证。

可复用的离线 Electron smoke 不包含在普通单元测试中：

```sh
node test/electron-smoke.cjs
```

该脚本需要已有 Playwright，可通过 `FA_PLAYWRIGHT_MODULE_PATH` 指定模块路径；可用 `FA_ELECTRON_EXECUTABLE` 指定已有 Electron，否则使用本目录依赖。脚本为每次运行建立系统临时目录和隔离用户数据，清除语音服务环境配置，阻止网络与外部语音进程，只使用 Chromium 假媒体设备和模拟服务。报告、截图保留在其输出的临时目录中；它不能验证真实麦克风、系统权限框或真实语音音色。

原生手动测试同样可设置 `FA_COMPANION_USER_DATA_DIR` 为独立绝对路径，避免影响真实历史与记忆。本分支验证结果见 [阶段记录](../../docs/companion-ui.md)；[早期 MVP 验收](VALIDATION.md)仅供历史追溯，不代表新增功能已完成真实后端或语音验收。

## 复用边界

保留 `dsh-pet` 的 MIT 多显示器几何代码和许可，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。没有导入上游角色、动画、提示词、字体、视频或其他限制素材；当前足球伙伴为 CSS 占位资源。
