# 显式单包复制扩展 ABI 1

此扩展只为离线解码取得一份完整、有界的 keys 和 payload。默认不 arm；没有持续 payload trace，不主动调用游戏 parser/池/工厂。它保留 legacy record48 / stats88 / install-report48，使用单独的 `fa_native_packet.h`、版本和尺寸检查。

当前构建仅通过独立测试，尚未在 FM27 中验证。现场 header-only `39aebea4…` 不被覆盖；新库和证据位于 `build/packet-v1/`。

## 控制流程

1. 宿主先成功安装现有 observer 并开启 legacy capture。
2. `fa_observer_packet_default_request` 建立 request，宿主可将最小 payload 改为 64 字节。
3. 显式 `arm` 分配当前进程内唯一递增的 capture ID。
4. callback 只竞争这一份槽。符合条件时，在原 callback 返回前复制全部 keys 和 payload；完整复制后才 release 发布 READY。
5. 后台查询 manifest，再向调用方自有缓冲 `copy`。函数不自动 release。
6. 宿主在后台计算文件哈希、写明 PID/session/新 shim SHA、manifest 和两份二进制；最后显式 `release`。

不能保留或稍后读取原始指针。manifest 不包含地址，原参数仍原样转发恰好一次。COMPLETE 仅代表两份 owned buffer 已完整复制，原接收器处理结果始终未知。

## 状态与结果

状态为 IDLE=0、ARMED=1、WRITING=2、CANCELLING=3、READY=4、CANCELLED=5。

- READY/CANCELLED 未 release 时拒绝新 arm；WRITING/CANCELLING 不可 release 或重用。
- cancel ARMED 直接取消；cancel WRITING 返回 pending，复制线程完成后进入 CANCELLED；cancel 已 READY 返回 ALREADY_READY，不丢弃已有快照。
- legacy Stop 与 arm 通过控制面互斥线性化。Stop 取消 pending 单包，保留已 READY 数据供读取/释放，游戏原调用继续。
- copy/release/arm 使用控制面互斥，callback 不取锁。consumer 的复制完成前不可能 release/rearm 覆盖 owned buffer。
- version 未知、capture ID 错误、尺寸不足、未知 flags/reserved 均明确拒绝。`get_manifest(version=1,id=0)` 可查当前槽；未 arm 时返回 OK/IDLE、capture_id=0、无 counts-known/complete，表示未知数据而不是空包。

结果码：0 OK；100 invalid argument；101 unsupported version；102 buffer too small；103 not installed；104 legacy disabled；105 busy；106 wrong ID；107 not ready；108 cancel pending；109 cancelled；110 needs release；111 already ready；112 no capture；113 ID exhausted；114 control exception。完整名称见 header。

## 固定布局

request 为 48 字节、pack 8：8 个 uint32（version、size、min_keys、max_keys、min_payload_bytes、max_payload_bytes、max_total_bytes、flags），随后两个必须为零的 uint64 reserved。

默认 keys 为 1..4096，payload 为 4..65536 字节，总字节上限 98304。宿主当前使用 min payload=64。min/max 和总量的组合必须有效；任何超限都 skip，不截断。

manifest 为 112 字节、pack 8：

| offset | 字段 | 类型 |
|---|---|---|
| 0/4/8/12 | version / size / state / flags | uint32 |
| 16 | capture_id | uint64 |
| 24 | call_sequence | uint64 |
| 32 | monotonic_ns | uint64 |
| 40 | native_thread_id | uint64 |
| 48/56 | original_keys_count / original_payload_count | uint64 |
| 64/72 | copied_keys_bytes / copied_payload_bytes | uint64 |
| 80/88 | checked_packets / skipped_packets | uint64 |
| 96/100 | last_skip_reason / reserved | uint32 |
| 104 | busy_skipped_total | uint64 |

flags：COUNTS_KNOWN=1、COMPLETE=2、ORIGINAL_RESULT_UNKNOWN=4、LEGACY_DISABLED=8、CANCEL_REQUESTED=16。READY 且采集开启时为 7。未 READY 不设置 known/complete；原 count 和复制长度应按未知处理。busy_skipped_total 是进程累计值，其他检查计数属于当前 arm。

## 可读范围与热路径边界

header 本身有效属于既有 callback ABI 的前提，legacy header 观察器仍按此合同工作。本扩展先验证 header 非空、count 乘法、cap、data 非空以及 `uintptr_t(data)+length` 不溢出。

仅本进程的两段 span 使用内核检查复制：macOS 为 `mach_vm_read_overwrite(mach_task_self(), …)`，Windows 源使用 `ReadProcessMemory(GetCurrentProcess(), …)`。一个候选最多两次，没有同包失败重试；失败或短 copy 不发布 READY。没有远程 task/进程句柄、任意地址 RPC 或权限更改。header 借用生命周期和输入一致性仍由游戏原 ABI 提供；这不是通用非法 header 探测器。

callback 不进行用户层堆分配、互斥、文件/网络 IO、哈希或解析；缓冲静态预分配为 32KiB keys + 64KiB payload。内存复制的 OS 调用可能调度或缺页，不构成硬实时延迟承诺。超限、null、不可读和取消均保留明确 skip reason，零长度是可知的零但不满足本扩展的最小候选条件。

## 独立测试

`packet_tests` 覆盖源缓冲回调后修改/释放、最大 96KiB、未知版本/ID/flags、null/zero/overflow、不可读/跨受保护页面、8 producer 唯一完整获胜者、300 次 producer/consumer/cancel/rearm/Stop 竞态及原始转发/异常。

release、ASan 和 TSan 均运行同一组；真实 Dobby toy 还通过 hook 取得一份完整包、释放原 source 后逐字节比较，未碰 FM 进程。测试使用人工字节，不读取真实业务 payload。实际 FM packet 与离线 decoder 的验证由 runtime owner 在受保护新 host 中完成。
