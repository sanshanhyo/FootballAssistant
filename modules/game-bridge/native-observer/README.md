# Native data-response observer

此模块提供一个纯原生的 SendDataResponse 观察器。已完成独立测试，并在 2026-10-30 的受保护 fresh FM27 private PID 1555 验证安装与首批 409 个真实业务回调 header。它只记录返回通道的调用次数、线程、单调时间和两个 span header 的 count，不读取 keys/data 或 wire payload。

上述实机证据属于冻结的 header-only `39aebea4…` 构建。当前源码新增显式启用的有界单包复制扩展，legacy ABI 不变；新构建输出到 `build/packet-v1/`，不会覆盖现场版本。扩展已独立测试但尚未实机验证，合同与边界见 [PACKET_CAPTURE.md](PACKET_CAPTURE.md)。

## 已核验入口与边界

- `game_plugin` SHA-256：`2e915b0f264920ae1205b111f45d50e354ac0e7d0b6e136b99189c24b265f431`。
- anchor export：`game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr`。
- dispatch 为 anchor `+0xC`（RVA `0x16c24`），固定 36 字节必须仍匹配。
- ABI 为 `void(receiver_wrapper*, keys_header*, payload_header*)`。三个原始参数原样传给 relocated original，恰好一次。
- 两个 CppArray header 各 16 字节，count 为 offset 8 的 uint64。keys count 单位是 uint64 元素，payload count 单位为字节。
- Header 的有效性来自现有游戏调用 ABI；观察器没有通用的非法指针探测能力。null header 会标为 unknown；已知 count=0 保留为真实零。
- 完整返回序列化、字符串和对象 ownership 均未实现。header 记录模式不解引用 `data`，原指针不保存到队列；单包扩展仅在显式 arm 后复制有界 span 字节，不解码对象或引用。

这些边界基于 `local-data/interface-catalog/native-channel-abi/` 的离线指令与布局证据。源头是当前 macOS arm64 构建；不能据此声称 Windows 或其他游戏版本已验证。

## 构建与独立验证

不依赖 CMake，不安装全局工具。在本目录执行：

```sh
python3 scripts/build.py
build/packet-v1/release/observer_tests
build/packet-v1/release/packet_tests
build/packet-v1/release/observer_dobby_toy_test --dobby "/absolute/path/to/libdobby.dylib"
```

macOS 构建仅为自建 toy 测试程序添加局部 JIT/动态库 entitlement；不会修改系统安全设置、游戏或 Steam。新共享库位于 `build/packet-v1/release/libfootballassistant_native_observer.dylib`。`build/` 已忽略，旧 `build/release/` 保持不变。

可选内存与并发检测：

```sh
python3 scripts/build.py --sanitize address
build/packet-v1/address/observer_tests
build/packet-v1/address/packet_tests
python3 scripts/build.py --sanitize thread
build/packet-v1/thread/observer_tests
build/packet-v1/thread/packet_tests
```

Windows 可在 x64 Visual Studio developer prompt 运行同一构建脚本编译核心和 C ABI；安装器目前明确返回 `unsupported_platform`。本机没有 Windows 执行证据。实际游戏安装需要平台专属 ABI 与代码指纹验证，不能由跨编译代替。

## 安装控制面

公共声明均在 `include/fa_native_observer.h`。ABI version 为 1，结构按 8 字节自然对齐。

| 函数 | 合同 |
|---|---|
| `fa_observer_install(anchor, dobby_path, report, report_size)` | 仅使用已加载的 anchor；内部验证模块文件 SHA、真实导出与 RVA、36 字节指令、非空现有 callback、固定 Dobby SHA 和版本。不会调用 setter 或游戏业务函数。 |
| `fa_observer_start_capture()` | 只有已提交且通过校验的安装可开启；安装默认不采集。 |
| `fa_observer_stop_capture()` | 关闭复制，原函数继续执行；不卸载 hook/trampoline。已经进入的 capture 可完成一次记录。 |
| `fa_observer_drain(records, capacity, record_size, out_count)` | 后台消费者调用；最多 4096 条；record_size 必须为 48。 |
| `fa_observer_get_stats(stats, stats_size)` | 读取 88 字节统计；各原子计数是近似一致的并发快照。 |
| `fa_observer_monotonic_ns()` | 返回与记录相同基准的当前单调时间；用于计算队列年龄，不假定与 CoreCLR Stopwatch 基准一致。 |
| `fa_observer_result_message(result)` | 返回静态诊断字符串。 |

安装顺序固定为 DobbyPrepare → 发布非空 original（release）→ DobbyCommit。Dobby、观察器和 trampoline 的引用保持进程生存期。准备/提交失败不猜测原地重试；应保留报告并由宿主决定受控重启。若提交返回成功但目标指令未改变，采集仍拒绝开启。

original 若为空、等于已将被修补的 target 或等于 observer replacement，均以 `invalid_original` 拒绝，且不发布或 Commit，避免递归转发。target 与 replacement 本身相同则在 Prepare 前拒绝。

模块 SHA 验证会读取原生库文件，属于安装控制面工作，不应安排在高频采样循环中。安装时机和正在执行代码的 patch 竞争仍须由运行时宿主管理；独立 toy 测试不能证明任意游戏线程时机安全。

安装没有“host 已验证”布尔旁路。发布版不包含 `fa_observer_test_install_toy`；它只存在于独立测试可执行文件，用来 hook 自建函数。

## 热路径与记录语义

游戏回调中没有托管回调、分配、互斥锁、文件/网络 I/O 或 payload 解码。队列容量 256，生产者最多执行 8 次 CAS；满或争用时丢诊断记录并增加明确计数，游戏原调用继续。

`fa_observer_record` 为 48 字节：

| offset | 字段 | 类型 |
|---|---|---|
| 0 | call_sequence | uint64 |
| 8 | monotonic_ns | uint64 |
| 16 | native_thread_id | uint64 |
| 24 | keys_count | uint64 |
| 32 | payload_count | uint64 |
| 40 | flags | uint32 |
| 44 | reserved | uint32 |

必须检查 `*_COUNT_KNOWN` flag；未知与零不同。超出 Int32/乘法范围也会保留真实 header count 并标异常 flag，不读取更多内存。单调时间基准只在当前机器/进程监控上下文使用。

多个生产线程的 call_sequence 是唯一入口序号，但入队顺序可能交错。宿主应给 HTTP 批次使用自己的递增序号，不把 call_sequence 直接当作 Data Core 的帧顺序。`overflow_dropped/contention_dropped` 非零表示诊断观测有缺口，不能宣称无损全量覆盖。

原始 native callback 的调用在观察代码之后，位于 catch 外且不是 noexcept。原函数的 C++ 异常保持原有 native unwind；不会穿过 CoreCLR 回调。本模块不提供卸载或恢复代码页的入口。

记录只证明进入派发点，包括随后原函数抛出异常的调用；它不证明接收器已成功处理或解码该响应。

## 来源与许可

观察器实现为本项目新增代码。Dobby 由宿主提供固定二进制，不打包进源码或 build 输出。

- 固定 Dobby binary SHA：`0cab79106f5b309409fd752ea5fe85e74c4b0c04b35d6508d5c2556bc297bac6`。
- 实际版本字符串：`Dobby-20260703-9d27180`。
- 对应源码与公共 ABI：<https://github.com/BepInEx/Dobby/tree/9d271803881f467aabfc24593c7dcaeb710fe861>。
- 许可：Apache-2.0，副本见 `third_party/Dobby-LICENSE`，来源说明见 `third_party/NOTICE.md`。

该固定 binary 的额外构建补丁未被证明全部与源提交一致，因此保留二进制指纹并要求真实 trampoline 测试。没有采用新 master 的 Instrument callback ABI。

## 当前验收

本机 macOS arm64 已通过：6 组核心测试（含 120,000 次并发 exactly-once 转发、参数保真、Stop、null/zero/oversize、发布顺序和 native 异常）、AddressSanitizer 与 ThreadSanitizer 核心测试，以及固定 Dobby 对 3 个独立 toy 目标的真实 hook。第三目标使用与实际 dispatch 相同的 ADRP/LDR/LDP/尾跳指令形状，验证了该类重定位和异常传递。

实际运行时在唯一 UI operator 确认的 fresh 主菜单使用 PID/session/DLL/module 绑定的一次性 checkpoint 安装；report 为 result/Prepare/Commit 全 0、state 3、checks 511。安装成功后才加载独立测试副本。首批 409 个 header 全部 enqueue/drain、无 overflow/contention，keys 1–27 个元素、payload 6–17,590 字节。证据和保护边界见 [运行记录](../../../docs/runtime-bridge.md)。

这同时验证了当前 FM27 trampoline 与实际 header 回调流量；payload 深拷贝、完整协议和业务值解码仍未实机验收。回调计数只证明进入派发点，不证明原接收器成功解码。
