# 依赖与许可证记录

记录本次实际选用、代码复用和固定研究基线；不扩展传递依赖审计。应用打包时仍应保留各发行包自带的 notices。FootballAssistant 自身许可证尚未选定。

## 已选用或实际复用

| 组件 | 版本/来源 | 许可证与范围 |
| --- | --- | --- |
| FastAPI / Uvicorn / Pydantic / PydanticAI Slim / python-dotenv | `uv.lock`：0.162.0 / 0.54.0 / 2.14.2 / 2.63.0 / 1.2.4 | [FastAPI MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE)，[Uvicorn BSD-3-Clause](https://github.com/encode/uvicorn/blob/master/LICENSE.md)，[Pydantic MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE)，[PydanticAI MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE)，python-dotenv BSD-3-Clause。仅记录直接运行依赖，完整解析版本由锁文件固定。 |
| `jsonschema[format]` | `uv.lock` 4.26.0 | [MIT](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING)；用于 Draft 2020-12 Schema/格式校验。规范文本和校验器是不同对象。 |
| `fmsave` | optional extra `save`，`uv.lock` 0.7.0 | [MIT](https://github.com/rhiever/fmsave/blob/e7b65cf60caaf0191330201b755bdcfe458777fa/LICENSE)；只使用容器 `read_index` / `read_section` API。其完整 FM26 reader 拒绝 FM27。FM27 summary31 grammar 和 build gate 是本项目独立实现，限两项实验性元数据。 |
| pytest / HTTPX | `uv.lock` 9.2.0 / 0.28.1，开发测试依赖 | pytest MIT；HTTPX BSD-3-Clause。 |
| Electron / electron-builder | `apps/companion/package.json` 与 `package-lock.json`：45.1.0 / 26.18.0 | 上游 MIT；打包输出同时带上游发行 notices。 |
| dsh-pet 几何代码 | `PC2005-cloud/dsh-pet@34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226` | [源代码 MIT](https://github.com/PC2005-cloud/dsh-pet/blob/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226/LICENSE)；实际改编 `displays.ts` 为 `apps/companion/src/vendor/displays.cjs`，同时将 MIT 文本放入应用包并在 `apps/companion/THIRD_PARTY.md` 记录。素材另有限制。 |
| BepInEx compatibility 编译引用 | DadMych FM26 社区包 `@463074f78ed86779cd5c72b5b3708fd1277ddbca` 中固定 SHA 的 DLL | 只作外部 C# 编译引用；没有把 core DLL 捆进 FootballAssistant 插件或在 FM27 安装/加载。上游各组件许可不同，未来分发需逐件核实。 |
| .NET SDK / Flutter / Dart | 本机 .NET SDK 10 编译；Flutter/Dart 延期 | Game Bridge 目标 `net6.0`，依赖清单不含 NuGet 包；BepInEx DLL 是外部 HintPath。Flutter/Dart 目前未选为 MVP 实现依赖。 |

可复核文件：[Python 直接依赖与 console scripts](../pyproject.toml)、[Python 锁文件](../uv.lock)、[Electron 依赖与打包声明](../apps/companion/package.json)、[Companion 第三方来源说明](../apps/companion/THIRD_PARTY.md)、[Runtime Bridge 项目引用](../modules/game-bridge/FootballAssistant.GameBridge.csproj)。

## 参考项目及限制

以下固定提交用于复核，不代表当前安装了其完整应用或复用了所有内容。

| 项目 | 许可证/复用决定 | 已知限制 |
| --- | --- | --- |
| [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet/tree/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226) | [代码 MIT](https://github.com/PC2005-cloud/dsh-pet/blob/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226/LICENSE)；本项目已改编多显示器几何并附许可证。上游角色、动画、提示词和视频未导入。 | [README 素材说明](https://github.com/PC2005-cloud/dsh-pet/blob/34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226/README.md#L309) 对动画/提示词/源视频另有限制性条款，角色声明 CC-BY-NC-SA-4.0；素材不按代码 MIT 处理。 |
| [rhiever/fmsave](https://github.com/rhiever/fmsave/tree/e7b65cf60caaf0191330201b755bdcfe458777fa) | MIT；当前安装 0.7.0，仅调用容器层供独立摘要 adapter 使用。 | 标准完整 reader 仅支持 FM26 并拒绝 FM27；本项目不绕过版本检查。 |
| [BepInEx](https://github.com/BepInEx/BepInEx/tree/b782da4ac54e1072d2857f4a2f77c80c3ef08005) | 固定上游的 [LICENSE](https://github.com/BepInEx/BepInEx/blob/b782da4ac54e1072d2857f4a2f77c80c3ef08005/LICENSE) 为 LGPL-2.1；未来分发需审查对应条款。本次 DLL 只作外部编译引用。 | 上游 IL2CPP 支持表列出 Windows，macOS/OSX 与 ARM 不支持；不能称主线已支持 FM27 Apple Silicon。 |
| [BepInEx/Il2CppInterop](https://github.com/BepInEx/Il2CppInterop/tree/81a6f78c8b653e0da4a3420ac4cd00819e8b6292) | 上游固定主线的 [LICENSE](https://github.com/BepInEx/Il2CppInterop/blob/81a6f78c8b653e0da4a3420ac4cd00819e8b6292/LICENSE) 为 LGPL-3.0-only；社区派生包须按其二进制和 NOTICE 区分。 | FM26 macOS 社区补丁不能证明 FM27 兼容；本项目 Runtime Bridge 仅完成离线编译和自测。 |
| [fredGob/FMdataExport](https://github.com/fredGob/FMdataExport/tree/c08fa8c1c5f591c6c1ddb0aff93b81eaa4592bdf) | 未发现主项目许可证或插件 C# 源码，不复制。 | README 所列 FM26/Windows、Linux/Proton 不能推出 FM27 或 macOS 支持。 |
| [mavarobli/FMSuperScout](https://github.com/mavarobli/FMSuperScout/tree/c24acb6bf62d8a3527c248a39583d2ef5e9387ed) | 未发现主项目许可证，不复制。 | 其内存采集直接使用 Windows `kernel32.dll`，仅研究设计。 |
| [DadMych/fm26-player-export-macos](https://github.com/DadMych/fm26-player-export-macos/tree/463074f78ed86779cd5c72b5b3708fd1277ddbca) | 根 MIT 文本不替代其 NOTICE 中被捆绑第三方组件的许可。只提取兼容层外部编译引用，没有运行安装脚本或移植导出插件。 | FM26 社区 beta 的重签名和 shadow 启动路线不是 FM27 验证；私有 shadow 尚未创建。 |

保留的许可证边界：dsh-pet 代码的 MIT 许可不延伸到其声明非商用的素材；BepInEx/Il2CppInterop 各自许可证不可互相替代；没有主项目许可证的 FM 导出工具仅作参考。逐项证据及可复用细节见[参考实现评估](reference-assessment.md)。
