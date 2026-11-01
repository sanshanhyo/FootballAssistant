# 依赖与许可证记录

记录本次实际选用、代码复用和固定研究基线；不替代完整发行审计。FootballAssistant 自有代码及相关文档采用 [MIT](../LICENSE)，范围与排除项见 [LICENSE-SCOPE.md](../LICENSE-SCOPE.md)。第三方代码、字体、角色与气泡素材不因本次变更被重新授权；应用打包时仍须保留各发行包自带的 notices。

## 已选用或实际复用

| 组件 | 版本/来源 | 许可证与范围 |
| --- | --- | --- |
| FastAPI / Uvicorn / Pydantic / PydanticAI Slim / python-dotenv | `uv.lock`：0.162.0 / 0.54.0 / 2.14.2 / 2.63.0 / 1.2.4 | [FastAPI MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE)，[Uvicorn BSD-3-Clause](https://github.com/encode/uvicorn/blob/master/LICENSE.md)，[Pydantic MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE)，[PydanticAI MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE)，python-dotenv BSD-3-Clause。仅记录直接运行依赖，完整解析版本由锁文件固定。 |
| `jsonschema[format-nongpl]` | `uv.lock` 4.26.0 | [MIT](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING)；用于 Draft 2020-12 Schema/格式校验。使用官方非 GPL extra；新增 rfc3986-validator、rfc3987-syntax、lark 的 wheel 均附 MIT 全文。规范文本和校验器是不同对象。 |
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

## 发布包许可证收集（2026-10-31）

`scripts/collect_backend_licenses.py` 从 PyInstaller `Analysis-00.toc` 的实际
文件映射到构建环境发行包，收集其许可证、COPYING、NOTICE 和作者声明，并收集
CPython 原始 LICENSE。输出位于 backend 的 `third-party-licenses/`，manifest
记录版本、文件 SHA-256、实际分析条目及待独立审查的原生库。缺少许可证直接令
构建失败；不联网补包、不以 SPDX 标签替代许可全文。

2026-10-31 的旧分析曾包含 `jsonschema[format]` 引入的 GPL-3.0-or-later
单文件 `rfc3987`。MIT 迁移改用上游 `format-nongpl` extra 并重新生成锁文件，
移除此模块；收集器若在实际分析中再次发现它，将阻止构建，且不再用项目根
LICENSE 为第三方补全文。三个 observation schema 使用 UUID 与 date-time；
启动时检查 checker 是否存在，测试同时覆盖合法、非法及缺失 checker 情况。
最终发行仍须使用干净环境重新生成对应平台清单，不能复用旧版 GPL 包的清单。
`logfire-api` 5.4.0 wheel 缺少 MIT 原文，固定版本官方副本及来源见
`packaging/licenses/README.md`。这不是完整对应源码归档：二进制发行前仍须
准备项目及适用第三方组件的对应源码、构建资料和适用 notices。

851 字体按作者独立条款随附，不重许可为 GPL；完整原作者条款已保存到字体目录。
角色资源授权另行说明。dsh-pet 未采用的限制性素材不会因根 GPL 自动获得授权。

本地 Linux 后端清单不替代 macOS/Windows 成品审查；发布前还应确认 Electron、
Chromium、Node 和生产 npm 依赖 notices 均留在成品，并复核 manifest 列出的原生
运行库。`python scripts/collect_backend_licenses.py --check --destination
<backend>/third-party-licenses` 可检查已收集 notices 是否缺失或被改动。

收集器另外输出并哈希绑定 `coverage.json`：发行包、标准库、本项目源码、
PyInstaller 无实体文件的 namespace 标记及其生成的标准库归档分别分类。
未认领的 Python 模块或 DATA 条目列入 unresolved 并阻断构建，不能因为 wheel
缺 RECORD 就静默跳过。AUTHORS/NOTICE 和 SPDX 标签仅为补充，不能单独替代
LICENSE/COPYING 全文；缺少完整许可文本仍须人工审核。

### Mac OpenSSL 独立缺口（2026-10-31）

真实 Mac 包的 Python 后端带 OpenSSL 3.0.16；此前 CPython LICENSE 不包含该组件
全文，不能拿 Electron/BoringSSL notices 混同替代。固定版本官方 LICENSE、作者与
致谢已放 `packaging/licenses/openssl-3.0.16/`。collector 在 Darwin 实际采集到
同目录 libssl/libcrypto 对且版本标记严格匹配时才收集，记录签名前二进制 hash；
应用重签改变二进制 hash 不等于许可文件损坏。最终保留文本仍由 manifest 哈希校验。
其它 native 项继续待审。该补项不修复版本安全问题：3.0 公共支持已结束，具体官方
公告与条件性风险见该目录 REVIEW.md，不代表已确认本项目可利用性。
