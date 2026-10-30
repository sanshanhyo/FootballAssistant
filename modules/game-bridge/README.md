# Game Bridge / Runtime Adapter

macOS Apple Silicon 的真实运行时链路已接通。FM27 私有 shadow 由 UnityDoorstop 4.6 引导 CoreCLR 10，直接调用本模块 `Doorstop.Entrypoint.Start`；CoreFoundation 主 runloop 每 3 秒执行有界 CAPI 读取，`pthread_main_np` 独立校验主线程。已实测完整复制现存三个 IdentifierSet 的 10,400 个真实 ID/名称；原生通道的实测阶段见 [运行记录](../../docs/runtime-bridge.md)。Windows x64 有离线构建/测试流程，尚未验证游戏内加载。

## 数据含义

UI 通道只输出原始 UI 对象树文字，永远 `partial`。实测可以读取菜单、日期和部分球员资料，但会遗漏自绘/虚拟化名单文字，也会混入缓存面板；它不等于当前屏幕像素可见性或完整足球数据库。新版字段为 `ui_tree_text`，旧运行版曾使用 `visible_text`，不能按该旧名称提高置信度。

与 UI 事实源分开的现存 IdentifierSet registry 诊断及真实 getter/field 读取证据已实测。静态 blob / parent / offset 读取已经实际二进制反汇编证明为纯读取；只从具体派生类的 closed generic parent 获取既有单例，null 就保留 `needs_context`。不调用 `get_Instance`、Register、cctor、setter、构造函数或游戏动作。仅看到字典计数时，逐条覆盖必须保持 0 / incomplete。实际完整结果为 Property 9130、Context 235、Reference 1035；只读了 ID/Name，未推断 Flag、owner、value_type 或业务值。

桥不调用模型、不处理教练决策或业务 SQLite。JSON 由 Data Core 规范化；UI 观测、registry 目录和接口可读性证据分别保存，不能互相替代。

## 调度与传输

- UI 采样约 15ms / 2500 节点 / 80 条文字上限；registry 诊断另有约 5ms 预算，不为补齐画面无限加预算。
- 后台发送，2 个快照有界队列、溢出丢旧，单次超时 1.5 秒；主线程不等待网络。
- UTF-8 信封最多 120000 字节，低于后端 128KiB 上限；生产 HTTP 关闭代理与自动重定向。
- 只允许字面量回环地址。每次发送重读受限 runtime 文件以恢复 token 轮换，不记录 token / API key。
- Getter token 证据只证明特定会话/现存对象上的一次成功读取，不推广为所有实例均可读。

## 构建与自测

从仓库根目录执行：

```sh
dotnet build modules/game-bridge/FootballAssistant.GameBridge.csproj \
  -p:BepInExCoreDir="/path/to/audited-bepinex-core"
dotnet run --project modules/game-bridge/tests/SelfTest.csproj
```

源码目标 net6.0，实际注入进程使用 arm64 CoreCLR 10.0.13。自测是独立 net10.0 程序，不加载游戏/注入器，覆盖线程门、CF 主线程回调与停止、中文字节上限、回环/重定向、token 轮换及 count 不等于枚举覆盖。

`Plugin.cs` 保留 BepInEx 插件入口作兼容路线；macOS 实测入口是直接 Doorstop/CoreCLR host，不需要生成 Unity interop DLL。源码不捆绑第三方 loader/core、游戏程序集或资源。所有实机缓存、日志和目录结果均放 ignored 的 local-game/local-data。

`scripts/sync_registry_entries.py --apply` 上传私有逐条结果并独立验证完整性；`scripts/sync_read_proofs.py --apply` 只更新有实际读取证据的 canonical member。`scripts/sync_native_observer.py --apply --watch` 将既有 native sidecar 持续投影到专用诊断接口，保留 uint64 十进制精度、最多 16 条 header 并报告原 poll 数量，不读取 payload、不安装 hook。所有脚本默认 dry-run，不打印连接 token。

registry 脚本也支持 `--watch`，仅发送每个当前 epoch 尚未确认的条目及显式完成 batch，稳定状态不重复上传。独立 `scripts/wire_decoder.py` 在游戏进程外解析已复制 bytes 的已知有界语法；完整协议、未知 tag、日期日历语义及 key 与 value 的关联仍未证明。当前实机 shim 已验证安装与首批 409 个 header，真实 payload 解码尚未验收。
