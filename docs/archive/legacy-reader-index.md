# 历史 Reader 路线归档索引

本索引基于 `integration/alpha-reader-ui@b7ca833bb273001a891cd3f7f00ec657a05d5a68` 整理。当前 MVP 聚焦 **Windows**，数据读取主线转向 Windows 比赛与赛外业务内存 Reader。早期 macOS 桥接、UI 对象遍历和页面采集路线在此归档，保留研究过程、实现、测试及已记录的局部成果。

归档采用原位索引：不移动或删除源码、文档、素材和旧分支，不改写历史结论，不改变现有运行入口或 CI 配置。下列文档中的“当前”“已支持”“尚未验证”等表述均应结合其记录阶段和固定构建理解，不能直接当作当前产品支持矩阵或新环境验收结果。

## 历史路线与证据入口

| 历史内容 | 原始入口 | 现在如何使用 |
| --- | --- | --- |
| macOS Apple Silicon 私有 shadow、Doorstop/CoreCLR 桥接及本机交付探索 | [Game Bridge 说明](../../modules/game-bridge/README.md)、[运行记录](../runtime-bridge.md)、[桥接部署](../bridge-deployment.md)、[Alpha 本机交接](../alpha-runtime-handoff.md) | 查阅当时的加载、调度、构建约束和局部验证；不作为当前 macOS 游戏数据功能的支持承诺。 |
| Unity UI 对象树文字、聚焦子树及页面字段投影 | [UI 遍历诊断](../ui-capture-diagnostics.md)、[显示资料投影](../display-profile.md)、[NativeUiReader](../../modules/game-bridge/src/NativeUiReader.cs) | 保留采集边界和字段来源研究。对象树文字可能包含缓存或遗漏虚拟化内容；路径和相邻文字不能自动升级为稳定业务身份。 |
| macOS 原生派发观察、packet 与 registry 诊断 | [原生观察器](../../modules/game-bridge/native-observer/README.md)、[packet 采集契约](../../modules/game-bridge/native-observer/PACKET_CAPTURE.md)、[离线语义工作台](../reader-semantics.md) | 用于理解历史通道、复制完整性及语义探索。回调计数、目录枚举或 A/B/A 对比不等于完整足球业务数据 API。 |
| 将既有 UI 路径带到 Windows 的 staged／finite 采集实验 | [metadata candidate](../../modules/game-bridge/windows-smoke-draft/README.md)、[UI scalar candidate](../../modules/game-bridge/windows-ui-smoke-draft/README.md)、[有限行采集](../../modules/game-bridge/windows-ui-batch-draft/FINITE_ROWS.md)、[页面采集](../../modules/game-bridge/windows-ui-batch-draft/PAGE_CAPTURES.md)、[显示投影原型](../../modules/game-bridge/windows-display-draft/README.md) | 同属历史 UI 采集路线，不能因平台是 Windows 就视为当前业务内存 Reader。原有一次性授权、预算和失败停止约束仍应保留；本索引不授权重跑实验。 |
| 早期规划、验收与接口交接 | [M0 只读勘察](../m0-readonly-survey.md)、[Alpha 验收](../alpha-0.0.1-acceptance.md)、[恢复检查单](../alpha-resume-checklist.md)、[Companion／Reader 交接](../companion-reader-handoff.md) | 保留各阶段的目标与缺口。含通用接口和仍复用设计的文档按段落理解，不把整份文档或其全部实现判为废弃。 |

## 与当前 Windows 读取主线的区别

历史 UI 路线通过 Unity 对象、可见性／边界检查、固定页面路径和文本投影取得显示状态；它依赖页面布局与采样上下文，不能据此假定完整名单、稳定球员 ID 或跨页面业务关系。

当前工作入口是 [比赛 Reader](../../modules/game-bridge/match-reader/) 与 [赛外 Reader](../../modules/game-bridge/offseason-reader/)。这条路线围绕具体 Windows 构建下的比赛数据和人员／球员内存结构开展验证，不以旧页面文本路径充当业务字段来源。两条路线的采集证据、身份保证和可用范围不能互换。

这些目录的存在不代表全量业务 API 或所有游戏版本已支持。例如赛外 `PersonLookup` 明确是有界的单人查询，并非完整球队名单 API；具体字段、版本、关联关系和实时性仍以对应实现、测试及独立验收为准。Windows-only 是本阶段产品范围，不是对全部 Windows 读取能力的完成声明。

## 继续保留和复用的内容

- [Companion 桌宠应用](../../apps/companion/) 的 Electron 界面、角色显示、设置和跨平台桌面代码不在“废弃实现”范围内。保留 macOS 构建或 UI 代码不等于承诺 macOS 游戏数据读取支持。
- [Data Core](../../modules/data-core/)、[contracts](../../contracts/) 以及认证回环接口、来源标注、未知／过期状态、生命周期与安全边界等通用设计继续按各自用途维护。历史文件中仍使用的代码不因被本索引引用而停用。
- 原有离线测试、合成 fixture、第三方署名与许可、角色／字体／气泡素材均保留。归档不重新授权这些内容，也不改变独立的许可迁移分支。

## 历史材料的保留边界

本索引只链接已经入库的源码和说明，不引入新的实机数据。历史本机原始采样、完整存档、packet/payload、游戏副本、截图中的私人信息、会话标识、runtime token 和模型凭据继续留在原私有位置，不上传到归档目录或 GitHub。需要公开举例时另行审阅并使用合成或脱敏材料，不能直接打包旧工作目录。

后续若恢复某条历史路线，应另外说明目标平台、固定构建、复用范围与需要补做的验证；旧文档或旧成功记录本身不构成当前支持或执行授权。
