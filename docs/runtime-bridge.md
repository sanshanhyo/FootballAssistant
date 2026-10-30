# FM27 Runtime Bridge — 实机状态

更新于 2026-10-30。用户已明确授权侵入式只读接入；仍保护未保存生涯，不修改原游戏安装或 Steam 启动参数，不禁用 SIP/Gatekeeper，不使用 sudo，不调用模型。

## 已实测链路

实际 FM27 为 Steam AppID 4530370 / build 26227640，bundle 27.0.0.2486716，Unity 6000.3.18f1-custom / metadata 39。原生 game_plugin 在实际启动日志自报 27.0.0+2486695，与存档 summary 的版本相同；bundle 与业务插件构建分层记录。

私有 root 为 `/Users/husky/Developer/projects/Football Assistant/local-game/fm27-runtime`。复制并 ad-hoc 签名独立主 executable / Info.plist，其余 Frameworks、Resources、PlugIns、Data 与 GameAssembly 别名指向原件作输入。原件 SHA 在准备前后不变。只签私有 executable，未使用 `--deep`；Mach-O 自身签名有效，外链资源使整个 shadow bundle 的 strict resource 验证不能通过，二者不混淆。实际直接启动已成功，没有修改系统保护。

| 尝试 | 实际结果 |
| --- | --- |
| 1 · PID 24413 | 社区旧 Doorstop 被 dyld 加载，但未加载 CoreCLR；Unity 6.3 chained-fixups 未钩住 |
| 2 · PID 25680 | 官方 Doorstop 4.6 后 CoreCLR 10 / BepInEx 已加载；缺 basename GameAssembly 别名，插件未执行 |
| 3 · PID 27445 | 补只读别名后 runtime_invoke detour 已安装；缺 UnityEngine.CoreModule，链加载器异常退出，无生涯载入 |
| 4 · PID 31394 | 直接 Doorstop → 自己的 C# Entrypoint → CF main runloop 成功，3 秒真实 UI 采样持续上传 |

第四轮运行 DLL SHA 为 `351428afd8164eaeaf04b3f08ede744b429e00f1edfece93c46b11be35234e68`。该版本 6 份源码 hash 已存私有 `loaded-build-31394.json`；后续 registry/cleanup 源码是新构建，不能当作第四轮已运行的能力。

Data Core 短维护/token 轮换后，同一游戏 session 自动继续捕获，已实证 source=runtime / connected / fresh / synthetic=false。事件包括 source_connected、snapshot_received 和 ui_text_changed。未调用 Go；模型预算与只读采集独立。

## 数据覆盖的实测限制

media 先另存 `FootballAssistant-runtime-test-20261030.fm` 并正常退出原版，后只在 shadow 加载这份测试副本，日期保持 2026-07-13 09:00。

- 主菜单 11 条原始文字含足球经理27、27.0.0、曼联。
- 经理中心 34 条，包含 2026-7-13、09:00、伯恩利等，与屏幕对照。
- 一线队页面未采到屏幕可见的球员名单，并混入缓存的经理中心预算文字。
- 单人资料最多 80 条，读到部分姓名/位置/身高/人格等，但遗漏多项可见技术属性。

因此 UI 通道只能称 raw UI tree / partial。旧字段名 visible_text 是历史命名，不能代表像素可见性；新版改 ui_tree_text。没有用 UI 样例冒充完整业务接口或结构化球员/财务数据。

## 已实测：独立 registry / 接口证据

完整离线 IL2CPP inventory 已枚举 types/fields/methods/properties/events，但 metadata 登记不等于运行可读。游戏派生目录、二进制、token 索引均留在 ignored local-data/interface-catalog，不提交。

新构建的 `RuntimeInspection.cs`：

- 从 PropertyIdentifierSet、ContextIdentifierSet、ReferenceIdentifierSet 的具体 class 取得 closed generic parent。
- 仅在固定 GameAssembly SHA 下使用实际代码已证明为纯读取的 class_get_static_field_data/get_parent/field_get_offset，永不硬编码 Il2CppClass 偏移。
- 未初始化 storage / singleton 为 null 时报告 needs_context，禁止 get_Instance/Register/cctor/构造器 fallback。
- 现存对象字段通过 IL2CPP field metadata 读取；getter proof 记录实际成功 method token、type token、上下文与时间。
- count-only 诊断的 observed_unique_entries=0、complete=false；后续真实 uint32 ID 枚举必须独立报告实际 unique 数、版本和结束证据。
- 独立 POST /v1/interfaces/probes 与私有 sidecar，不挤进 UI 事实源。完整 registry entries 使用独立 batch 契约；不把 native exports / metadata_index 当实际业务 ID。

初次 0.3.0（PID 91878，未载生涯、未安装 native observer）在 GC handle 释放处崩溃。实际 arm64 导出函数及实现证明，此 Unity 6.3 构建的 handle 是完整 64 位槽地址，旧 `uint` 会丢失高 32 位。修复统一使用 `nuint` 传递/保存 GC 根，业务 ID 保持 `uint32`，没有移除临时强根。

2026-10-30 的 fresh private PID 1555 加载冻结 DLL `d91fa04c61b0ed3fdd851875e677b062680a4edfd2af1f26858b9dc81540c8b9`。独立窄审通过后，先用一个现存字典做 `new → get_target 等于原对象 → free 一次`；非零 high32 gate 实机通过，完整一 tick 后才扫描条目。失败路径隔离句柄，不重复 free，也不放行扫描。

| 现存 registry | 实际唯一 ID/非空名称 | 字典版本 | 完整性 |
| --- | ---: | ---: | --- |
| PropertyIdentifierSet | 9130 | 9130 | unique == expected，complete |
| ContextIdentifierSet | 235 | 235 | unique == expected，complete |
| ReferenceIdentifierSet | 1035 | 1035 | unique == expected，complete |

这些条目经 109 个独立 batch 入库，服务器分别确认 complete，共 10,400 条。现存数组通过精确 token 的 `Array.GetValue(Int32)` 复制，字典/数组/boxed Entry 仅在当前回调内保留临时 GC 根；每帧最多 200 slot/5ms，并核对 key 与 info.ID。版本、数组或计数变化换 epoch。当前只读取 ID/Name backing field，未读取 Flag/owner/value_type，不代表已获得足球业务值。65 条有上下文的实际读取 proof 映射到 22 个 canonical method/field 并更新目录。

私有证据位于 `local-game/fm27-runtime/evidence/gc64-gate-1555/` 与 `evidence/registry-complete-1555/`，包括 host/session/DLL hash、gate、完整条目、字典版本、各文件 SHA。

## 已实测：原生返回通道 header

唯一 UI operator 实时确认 PID 1555 是 fresh 主菜单、尚未加载生涯后，控制面写入有效期 30 秒的一次性 checkpoint，绑定 PID/session/managed DLL SHA/game_plugin SHA。CF 主线程于 07:46:42 UTC 消费并安装已审 shim `39aebea4e1569fea801ac29a322199de1b7cc7be050dff5da55e447e6bd51182`。实际 report 为 result/Prepare/Commit 全 0、state 3、checks `0x1FF`，trampoline 与 target 不同；没有重试 patch。

安装成功后才由 UI operator 加载唯一独立测试存档，停在 2026-07-13 09:00 的经理中心。第一组实际业务回调为 409 次，均有两个已知 header count，9 个非空 drain frame 合计 409 个唯一 sequence，enqueue/drain 都为 409，overflow/contention/stopped 均为 0。keys 为 1–27 个 UInt64 元素，payload 为 6–17,590 字节，观察到同一个 native thread。原文件 executable/GameAssembly/metadata/game_plugin SHA 再次与原基线相同。

header 观测由独立 `sync_native_observer.py --apply --watch` 持续投影到 Data Core 专用接口；服务器确认 installed、真实计数与 callback 时间（来源 capture 减 header age 的近似），不会以空 poll 的 last_seen 冒充新回调。计数按 uint64 十进制字符串传输，最多投影 16 条 header，同时保留原 poll 数量；完整 drain 仍留在私有归档。`sync_registry_entries.py --apply --watch` 独立上传每个新 epoch 的新增 ID 与显式 complete，稳定 epoch 不重复上传。

随后 operator 于 08:15:44.908 UTC 打开一线队（28 人名单），新增 122 个 header；08:16:21.511 打开哈里·马奎尔概览，新增 96 个；08:16:55.841 返回经理中心，新增 1 个。累计 628 个全部 enqueue/drain，仍无 overflow/contention，实际 keys 最大 34 个、payload 最大 36,050 字节。每一步截图日期仍为 2026-07-13 09:00，全程未保存、推进日期或修改业务设置。分步时间/sequence 证据位于 `evidence/native-headers-pages-1555/` 与 `evidence/native-headers-player-1555/`；后者同时保存原安装与原始 `A A-曼联.fm` 的基线哈希复核，不声称共享 overwrite backup 始终未变。

这些结果只证明已经进入原生 dispatch 点，不证明原业务接收器随后成功处理。当前 shim 不读 keys 内容或 payload bytes，`field_values_known=false`、`payload_data_read=false`、整体 `complete=false`。安装与第一组 header 分布、服务器回读分别保存在 `evidence/native-installed-1555/`、`evidence/native-headers-live-1555/`。

下一阶段的独立 `scripts/wire_decoder.py` 已实现反汇编证明的基础 tag 与扩展 10/32/34 的有界语法，保留未知 prefix、opaque reference pairs、encoded GameDate 和 property 顺序/重复；unknown tag、截断、超预算或未消费尾字节会停止整次解码。17 项 Python 测试通过（7 relay、10 wire）。当前真实 payload 验证仍为 0，不调用游戏自身池/工厂/parser；必须先在同步原生回调内取得一份完整有界深拷贝，再做进程外解析与实际业务值对照。

## 组件、私有路径和复现

官方 [UnityDoorstop 4.6.0](https://github.com/NeighTools/UnityDoorstop/releases/tag/v4.6.0) 明确修 Unity 6.3 chained fixups，许可为 [LGPL-2.1](https://github.com/NeighTools/UnityDoorstop/blob/v4.6.0/LICENSE)。本机 debug archive SHA `04d89d6cba16680429c401c1696c3205541665ad6ed53a55b32bc65a97c1005a`，dylib SHA `04c5f13bc38172c176c88c5b868afe000625c114cfeada9e0080da908349b77c`。原社区 NOTICE 的 Doorstop 许可不能替代此实际版本。

BepInEx core 保留固定 DadMych 提交 463074f78ed86779cd5c72b5b3708fd1277ddbca 的单独构建引用；macOS 当前不执行其链加载器，也不需要 generated Unity wrappers。未复制 vinteset 的导出器/Display Fix。各 LGPL/native 组件单独记录来源，游戏派生程序集不分发。

`prepare_isolated.py` 默认 dry-run；实际准备使用 --apply，只接受已验证输入，不下载/解压/执行第三方安装器，拒绝覆盖既存私有 root。需要已有固定兼容层目录、arm64 runtime 和经核验的 Doorstop 4.6 dylib。

`launch_isolated.py` 默认打印计划；--launch 前拒绝任何已运行 FM27，检查 bundle/exe 指纹和私有可写子树的 symlink/hardlink。只从私有 root 作 CWD，TMP/日志/diagnostics/core/config/cache/生成目录均私有。每次 attempt 日志与 DLL hash 独立保留；原资源链接从不作为写入目的地。

```sh
.venv/bin/python modules/game-bridge/scripts/prepare_isolated.py \
  --compat-dir "/path/to/fixed-compatibility-source" \
  --runtime-dir "/usr/local/share/dotnet/shared/Microsoft.NETCore.App/10.0.13" \
  --doorstop-path "/path/to/verified/doorstop-4.6.0/libdoorstop.dylib" --apply
.venv/bin/python modules/game-bridge/scripts/launch_isolated.py --launch
```

游戏内已有生涯时先保存/正常退出；不强杀未保存游戏。退出 shadow 后正常从 Steam 启动原件即可回退，无需修复原安装或 Steam 参数。原始存档不作诊断写入，页面验证只用独立测试副本。

## 验证边界

net6 构建及独立 net10 自测通过，包括真实 CF main runloop/线程门、停止后无回调、中文 120000 字节预算、回环限制、生产 HTTP 拒绝 302、token 重读与 count 不等于完整枚举。macOS UI 采集、10,400 条现存 registry 完整枚举、已审原生 observer 安装及第一组 409 个 header 已实机验证。独立 loopback 集成验证覆盖 registry watch 的增量发送、零/u32 最大值、显式 complete、稳定轮次去重与 token 轮换。完整业务值与 Windows 游戏内接入仍未验证，不能按 metadata/编译结果宣称完成。
