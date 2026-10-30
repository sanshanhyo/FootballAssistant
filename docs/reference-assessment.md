# 参考实现评估

核验基线固定于 2026-10-30。本页区分当前实际复用的代码、仅作外部构建引用的组件和只读研究过的候选；许可仅适用于相应代码或素材范围。

## dsh-pet：Companion 的实际复用

[PC2005-cloud/dsh-pet `main@34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226`](https://github.com/PC2005-cloud/dsh-pet/commit/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226)，包版本 0.3.8，采用 Node.js、TypeScript、React、Cordis 与 Electron。项目的 `src/host` 管状态、配置、模型与持久化，`src/client` 提供浏览器/React UI，`src/shared` 保存物理、菜单和多屏逻辑；Electron helper 管原生透明桌面窗口。

源码中实际有透明置顶窗口、跨工作区、多屏/DPI、拖拽抛掷、碰撞、点击反馈、动作动画、聊天气泡与托盘通知。本项目没有移植完整宿主或 React 页面；只把多屏几何逻辑适配到自有 Electron Companion。pointer-hit-test 仅参考实现思路。

| 当前代码/素材 | 来源与处理 |
| --- | --- |
| `apps/companion/src/vendor/displays.cjs` | 改编 `dsh-pet/src/shared/displays.ts` 的显示器区域解析与边界夹取，服务拖动时处理多屏、断开显示器和屏幕间空隙。 |
| 主进程指针 fallback | 参考 `runtime/electron-helper/pointer-target.js`、`main/windows.js`；无上游代码复制。 |
| MIT 声明 | `apps/companion/src/vendor/dsh-pet-LICENSE.txt` 和 `apps/companion/THIRD_PARTY.md` 保留版权、commit 与来源路径；应用打包带 MIT 文本。 |
| 宠物外观与资源 | 本项目使用原创 CSS 几何外观；未导入上游角色、动画、提示词、字体、表情图片、视频或音频。 |

上游代码为 MIT；但 README 将动画/生成提示词/源视频另列为开源可用、禁止商用，并将大肥鱼形象声明为 CC-BY-NC-SA-4.0。字体与表情素材无逐项权利清单，因此均未复制。MIT 代码许可不覆盖这些素材条件。

对话实现里，dsh-pet 会将完整聊天存入 `memory.json`，发送给模型的上下文默认为最近 5 轮；人格由实例级 system prompt、名称和日期背景构成。[chat-memory.ts](https://github.com/PC2005-cloud/dsh-pet/blob/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226/dsh-pet/src/host/plugin/chat-memory.ts) 的持久聊天不等于长期语义记忆或成长系统。其独立 app 发布工作流只生成 Windows x64 包；源码的 Darwin 路径不证明 Apple Silicon 已发行或通过验证。

## FM 游戏参考

| 项目 | 固定来源与许可 | 本项目决定及证据限制 |
| --- | --- | --- |
| [rhiever/fmsave](https://github.com/rhiever/fmsave/tree/e7b65cf60caaf0191330201b755bdcfe458777fa) | v0.7.0，MIT；`pyproject.toml` 声明 Python ≥3.12、OS independent | 实际安装为 optional `save` extra；标准 FM26 Save reader 明确拒绝 FM27。summary adapter 仅使用容器 `read_index`/`read_section`，由本项目独立解析严格限定的两字段 profile，不修改 fmsave 版本门。 |
| [fredGob/FMdataExport](https://github.com/fredGob/FMdataExport/tree/c08fa8c1c5f591c6c1ddb0aff93b81eaa4592bdf) | 未发现主项目许可证；仓库提供 DLL/README，缺少插件 C# 源码 | 只参考采集结果与分析分开的思路；不复制。README 的 FM26 Windows / Linux Proton 路径不证明 Mac 或 FM27 可用。 |
| [mavarobli/FMSuperScout](https://github.com/mavarobli/FMSuperScout/tree/c24acb6bf62d8a3527c248a39583d2ef5e9387ed) | 未发现主项目许可证；`MemScan.cs` 使用 `kernel32.dll` | 只看架构，不复制 Windows 内存读取实现。 |
| [BepInEx](https://github.com/BepInEx/BepInEx/tree/b782da4ac54e1072d2857f4a2f77c80c3ef08005) | LGPL-2.1；Game Bridge 构建时引用第三方 DLL，不捆入自己的插件输出 | 主线 IL2CPP 表列 Windows，OSX 和 ARM 不支持；通用 Unity/macOS 能力不代表 IL2CPP Apple Silicon 可用。 |
| [Il2CppInterop](https://github.com/BepInEx/Il2CppInterop/tree/81a6f78c8b653e0da4a3420ac4cd00819e8b6292) | 此主线 `Directory.Build.props` 声明 LGPL-3.0-only | 社区 patched 1.5.1 的 NOTICE 另写 LGPL-2.1；不能把主线结论移用到社区 DLL。 |
| [DadMych/fm26-player-export-macos](https://github.com/DadMych/fm26-player-export-macos/tree/463074f78ed86779cd5c72b5b3708fd1277ddbca) | 仓库根为 MIT 文本；[NOTICE](https://github.com/DadMych/fm26-player-export-macos/blob/463074f78ed86779cd5c72b5b3708fd1277ddbca/NOTICE.md) 列明其他依赖和来源 | 从该固定包取 BepInEx compatibility DLL 作为隔离的构建引用，不运行其安装器、不复制导出插件或素材。Mac shadow 启动仍未加载 FM27 验证，未改原游戏/Steam。 |

FM27 UI 与受限 summary adapter 的数据边界见[架构说明](architecture.md)。Mac Runtime Bridge 目前只离线编译、自测和准备默认 dry-run；没有注入、签名或创建私有 shadow app。FM26 工具与补丁均不视为 FM27 游戏内兼容证据。
