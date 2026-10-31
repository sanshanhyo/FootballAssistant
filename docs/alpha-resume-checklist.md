# Alpha 实机恢复验收清单

截至 **2026-10-31**：Windows 普通 reader 仍为 `unsupported`。独立 probe / metadata 的成功不等于 UI 或业务数据验收完成。本清单仅准备恢复访问后的操作，**不表示已经执行，也不授权无人值守安装、启动或扩大采样**。Windows 优先；macOS 另行验收。

本轮目标只有一个：在新会话中按三阶段请求验证独立 UI candidate 能否取得一条非空 UI 组件文本。候选预算修订为 [`65f3d1d055792146faab25cdc066e729f617a99a`](https://github.com/sanshanhyo/FootballAssistant/commit/65f3d1d055792146faab25cdc066e729f617a99a)，capture 为 **100ms 软预算 / 384 reserved native boundary units**。部署前重核实际产物对应源码与 hash；不能只看文件名、下载时间或某个 CI 绿色标记。后续若代码变化，先重新审阅本清单与 [candidate runbook](../modules/game-bridge/windows-ui-smoke-draft/README.md)。

## 1. 恢复访问与退出旧会话

- [ ] 确认 Windows 连接恢复，当前操作者有权访问该设备与测试数据；代用户操作时确认本轮部署、一次正常启动和三个显式阶段的范围。
- [ ] 先只读核对当前 FM 进程及实际可执行文件位置。运行时应只有目标游戏进程；出现多实例、路径不符或所有权不明即停止，不批量结束进程。
- [ ] 找到此前**自有部署 manifest / 备份记录**，核对已安装 loader proxy、配置、私有 DLL/runtime 的位置与 hash，以及每个文件由谁创建。它是已有部署记录，不假定项目提供了某个新 manifest 工具或固定文件名。
- [ ] 若游戏仍在运行，请用户正常保存并退出，确认进程已结束再继续。旧失败 session 保持终态，不重发请求、不删除状态来重置策略，不热替换进程已加载的 DLL。
- [ ] 若找不到自有 manifest、发现第三方改动或无法证明配置归属，停在只读核查阶段；不要覆盖配置或清理陌生文件。

## 2. 核对候选并准备部署

- [ ] 将候选放入获准的私有、当前用户控制的独立目录；核对 `source-commit.txt`、构建 provenance 与 `SHA256.txt`（若该 CI artifact 提供），并独立计算 DLL 的 SHA-256。产物自带 hash 只能证明相互一致，仍须核对可信构建来源与选定提交。
- [ ] 确认 `FootballAssistant.WindowsUiCandidate.dll` 和同版本两个 PowerShell helper 齐全；不要混用旧候选 helper。候选包不应包含预先启用的配置或请求。
- [ ] 核对当前游戏 build / 文件身份符合 helper 的已审阅 profile；hash 不匹配时停止，不修改白名单来绕过检查。

在 PowerShell 中先把以下变量填为**本机已核验的绝对路径**，不要把真实值贴到公开 Issue。只运行准备步骤：

```powershell
# $ExePath: 原始 fm.exe；$GameAssemblyPath: 同一安装的 GameAssembly.dll
# $CandidateDirectory: 私有候选目录；helper 与 DLL 来自同一构建
& (Join-Path $CandidateDirectory 'Prepare-UiCandidate.ps1') `
  -ExecutablePath $ExePath -GameAssemblyPath $GameAssemblyPath `
  -CandidateDirectory $CandidateDirectory
```

该 helper 在 FM 已退出时只读游戏文件 hash / FileID，并在私有候选目录写 `footballassistant.windows-ui.json`；它不安装 loader、不启动游戏、不创建读取请求。不把它的成功当作运行时读取成功。

- [ ] 备份并核对已有**自有** loader 配置，只把已获准的 `target_assembly` 更新到这份候选 DLL；保留已验证的私有 CoreCLR 路径及其他设置。保存变更前后 hash、精确 diff 与回滚位置。
- [ ] 本清单不新增 proxy，不替换游戏 exe / DLL，不改存档、Steam 参数、全局环境或系统安全设置。确需这些操作时另行确认方案与授权。

## 3. Steam 一次启动与新会话门控

- [ ] 由用户或在本轮明确授权下通过 Steam 正常启动**一次**。不循环启动，不使用自动点击跳转或自动重试。
- [ ] 私下核对 `windows-ui-private/session.json` 属于本次进程生命周期，且 PID / session / bridge hash 与当前候选一致；旧文件不能作为证据。
- [ ] `module-status.json` 必须为 `ready`，其 PID、session、bridge / game hash 与当前会话一致；`stage-state.json` 必须不是 terminal，且阶段尚未消费。
- [ ] 核对完整且唯一的目标 `UnityWndClass` 窗口证据：本次 PID、owner / callback TID、可见样式、正 client area 均符合候选检查。缺失、多义、扫描不完整或身份变化就停止。
- [ ] 请用户确认**本次会话当前页面稳定**（主菜单或已获准的测试生涯页面）。不能用上次截图或旧 HWND 代替。窗口样式与矩形也不能独自证明屏幕内容可见或 Unity 调用时机安全。

## 4. 逐阶段校验，禁止无条件批量执行

每条请求仅有效 30 秒，绑定本次 PID / session / nonce / bridge 与 game hash。每个阶段都必须确认当前会话页面稳定，等待并核验前一阶段成功后才进入下一阶段。可以在已授权范围内使用有状态检查的受控编排，无需用户逐阶段重复授予同一项许可；但不能把三条命令无等待、无结果检查地拼接执行。页面稳定与会话有效不能仅靠延时或上一阶段成功推断，无法确认时暂停并询问用户。

**阶段 A：metadata**

```powershell
& (Join-Path $CandidateDirectory 'Request-UiStage.ps1') `
  -CandidateDirectory $CandidateDirectory -Stage metadata -StableCurrentSessionPageConfirmed
```

私下检查 `ui-evidence.jsonl` 的该阶段成功结果及 `stage-state.json` 的 `metadata_succeeded`。它只证明这次 metadata 路径，不是足球数据。

**阶段 B：ui_resolve**，仅在 A 成功且本次会话仍有效时执行：

```powershell
& (Join-Path $CandidateDirectory 'Request-UiStage.ps1') `
  -CandidateDirectory $CandidateDirectory -Stage ui_resolve -StableCurrentSessionPageConfirmed
```

检查该阶段成功结果与 `resolve_succeeded`。这是同一 module lease / session 内的 class / method warm-up，预算为 250ms 软时间 / 2048 reserved units；成功不授予自动 capture 权限。

**阶段 C：ui_text**，仅在 B 成功且重新确认稳定页面后执行一次：

```powershell
& (Join-Path $CandidateDirectory 'Request-UiStage.ps1') `
  -CandidateDirectory $CandidateDirectory -Stage ui_text -StableCurrentSessionPageConfirmed
```

上限：100ms 软时间、384 reserved units、1 panel、32 nodes、depth 8、每节点 8 children、至多 1 条 128 UTF-16 units 文本。软预算不能抢占单次 native 调用或首次 JIT；reserved units 不是精确调用次数，必要清理另受自身上限约束。不得现场扩大预算。

## 5. 结果判定与停止

| 结果 | 本轮结论与下一步 |
| --- | --- |
| 非空文本且相应阶段成功 | 仅记为“本构建 / 本会话取得一条真实 UI 组件文本”；私下与当前页面交叉核对，停止采样 |
| `no_eligible_text` / `bounded_no_text` 或其他空结果 | 本次未取得合格文本；不推断游戏无数据，不重试 |
| `time_budget` / `native_call_budget` / 节点等预算终止 | 记录停止阶段、耗时与 reserved units；不是成功，也不是放宽预算的自动授权 |
| `backend_failure`、身份 / 模块 / 窗口拒绝、异常 | 保留私有诊断并停止；不绕过门控，不自动进入下一阶段 |
| 请求后暂无确定结果 | 仅只读检查状态，先确定是否消费；不因“没输出”重发请求或重启来碰运气 |

失败、空结果、预算终止以及完成的 capture 均不能在旧 session 内再来一次。若状态文件恰在写入而读取失败，可重新只读检查；原生阶段是否消费不明时不要重新执行请求 helper。后续实验须先审查结果，再经正常退出 / 新会话和新确认开始，不能删状态恢复权限。

一条组件文本不证明屏幕无遮挡、字段语义、稳定球员身份或完整业务覆盖。任何结果都不能把普通 Windows reader 从 `unsupported` 改报为支持。

## 6. 故障与回滚

- [ ] 游戏卡顿、崩溃、窗口身份失效、候选来源不明或 native 错误时立即停止新增请求。先让用户正常保存 / 退出（若仍可操作）；无响应时不要擅自强杀或反复启动，先说明保存风险并确认处理方式。
- [ ] 确认进程结束后才改部署。按 manifest 核对当前自有配置仍等于本轮写入版本，再恢复精确备份；发现别人改过则停止，不盲目覆盖。
- [ ] 仅撤回本轮清单列出的自有文件 / 配置变更；不删除整个目录，不碰游戏 exe、原始 `GameAssembly.dll` 或任何存档，不删除旧失败证据。需要卸载此前 loader 时另行核对其自有清单与授权。
- [ ] 回滚后核验文件 hash 与配置 diff。是否再次启动验证需另行确认，不把回滚变成自动重启循环。

公开结果只记录源码提交、产物 hash、脱敏阶段结论与未验证项；真实路径、PID、session、测试存档名、原始文本 / 采样 / 日志、凭据与 keys 留在私有证据中。

## 7. 这一步之后仍需验收什么

- **字段与生产 Reader**：验证语义、身份、单位、来源、freshness、完整性与会话隔离；一条 UI 文本只用于诊断，不能替代有稳定对象 / 字段契约的后台读取，也不能自动启用持续采样。
- **桌宠端到端**：选定构建冷启动 → 真实认证 backend → 已核验字段 → 卡片 / 回答；验证断连、过期与重连不混入旧事实。真实模型调用另定供应商、隐私范围与正数额度，不以 fixture 代替实机证据。
- **macOS 本地 App**：只在访问恢复且获准后，核对对应 arm64 构建、内嵌后端、实际本地启动、窗口 / 退出 / 重启、真实连接及故障状态；模型、语音与游戏读取分别验收。今晚不操作 Mac，不以 Windows 或历史 Mac 结果代替本次验证。

每项报告分开写通过、失败、未运行；完成此清单也不等于完整 Alpha / MVP 已验收。
