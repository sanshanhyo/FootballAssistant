# 分支整合计划

更新：**2026-10-31 16:31 UTC**。本次为隔离只读分析，未执行分支合并、历史改写、分支删除或 Release 发布。以下是未来操作建议，不代表现在已满足合并或发布条件。

## 结论

`feat/reader-semantics` 与 `feat/companion-ui` 已完整进入 `integration/alpha-reader-ui` 的提交历史，无需重复合并。最少安全路径是：

**保留最新 docs/update → 合入 integration → 对最终候选完成验证与评审 → 经确认合入 main。**

当前 MVP 的桌宠、API、页面投影及测试代码存在，不代表 Windows 真实读取与有依据的建议闭环已验收。无文本冲突也不代表 README 中全部功能声明已通过目标平台验收。现在不建议标为正式稳定版。

## 当前分支与来源

| 分支 | 本次远端 head | 内容与状态 |
|---|---|---|
| `main` | `f7d1055eaac31cef1af3559195dadd94b239089f` | 独立只读控制台与可选 Agent 分离；其余分支共同基线。 |
| `feat/reader-semantics` | `18acc2eb4d6f0541c0d2935bf5e9e1c6b8618655` | 业务契约/API、语义证据、展示投影、受控建议及 Windows 读取基础；已整合。 |
| `feat/companion-ui` | `13c1a6bf801821c4cff2c4586939035e6b8534c8` | 桌宠交互、设置、客户端、安全、语音服务、角色、气泡与字体；已整合。 |
| `docs/update` | `922497f126d20bf0dbaa328a2aabd535aaf48a38` | README（含用户 Road Map）、GPLv3 LICENSE、认可的 logo；尚未整合其提交历史。 |
| `integration/alpha-reader-ui` | `0b821f1f53a6766b4d0472339d5d5d5a56f56f4a` | reader/UI 汇合及后续接线、投影、配置、打包、桥接候选与修复；本次最新为 POSIX capture lock 修复。 |

上述为时间点快照。今晚后续诊断、贡献指南及其他提交，合并前须按最新 heads 再核。

### 已整合的历史证据

[汇合提交 7653b16](https://github.com/sanshanhyo/FootballAssistant/commit/7653b16b582c137f64ae3b2a5c95ef87fab0e623) 的两个父提交分别为 UI `13c1a6b…` 和 reader `18acc2e…`。最新核验：

| 对比（左分支 / integration） | merge-base | 左右独有提交数 |
|---|---|---|
| main | `f7d1055…` | 0 / 69 |
| reader | `18acc2e…` | 0 / 60 |
| UI | `13c1a6b…` | 0 / 64 |
| docs | `f7d1055…` | 8 / 69 |

reader/UI 后续被修正的文件不一定逐字等于源分支，这是正常迭代，不代表漏合。另已确认上一检查点的本地 `ebe8586…` 与远端 `098a8e0…` 虽 commit SHA 不同，tree 同为 `87240d15ee81d1d62e4ac3808a7ce6b6073b909a`；不能仅因 SHA 不同就认定代码全面分叉或使用 force-push。后续工作应基于最新远端历史提交增量。

## 文档保留与冲突检查

本次运行：

```sh
git merge-tree --write-tree \
  0b821f1f53a6766b4d0472339d5d5d5a56f56f4a \
  922497f126d20bf0dbaa328a2aabd535aaf48a38
```

退出码 **0**，无冲突条目；预测合并结果 tree 为：

`88c3132267d5cf6d7c4e12da458ccb7250cf351a`

结果相对 integration 仅修改 `README.md`、新增 `assets/logo.png`，不会回退任何代码。结果中 README/logo 与用户最新 docs 分支的 blob 完全一致：

- README：`11c8c5d65691d044420476321fdef81bb80c2f4d`
- logo：`c51c7a3df199a958c4b3081f72bb93a3f9c8b7e3`
- 双方 LICENSE 已相同：`f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`

main 与 integration 的模拟合并 同样退出 0，结果为 integration 当前 tree `f6bcadde7c17dce06bc5a7e0a9e30573658de1f2`。这不是实际合并，也不保证未来新提交无冲突。

**保留原则：**保留用户 README 结构、Road Map、logo 与许可证，不从 docs 分支复制整棵旧树覆盖新代码。`docs/roadmap.md` 虽存在，但不属于 docs/update 相对 main 的净变更。README 的“已支持页面读取”等表述应按实际平台/构建补足限制，经用户确认后处理；不要自行把 Windows 未完成能力写成完成。旧验收文档中的历史 SHA 和状态应标明日期或追加新证据，不将不同构建的历史成功拼成一次完整验收。

## 建议合并顺序与策略

1. **刷新并冻结评审快照。**重新抓取 main、docs、integration，检查新提交和现有 PR。今晚新增贡献指南/修复只纳入审阅过的增量，不夹带旧 README 或整树替换。
2. **docs/update → integration。**优先普通 merge commit，保留用户作者信息与历史。若新冲突出现，逐段处理；不要整体采用 ours/theirs。检查最终 diff 没有回退 reader/UI/桥接代码。
3. **验证最终候选，开 integration → main 的 draft PR。**说明已包含 reader/UI，列清已测、未测、Windows 限制与产物证据。无需再开重复功能合并。
4. **达到门槛并获确认后，以 merge commit 合入 main。**随后核对 main SHA/tree、CI及构建产物。发布和打 tag 单独决定，不由合并自动触发。

本次不建议整体 squash/rebase integration：它包含已共享的双分支历史及安全修正，保留 ancestry 有利于审计、继续开发和避免重复合并，也便于以一个整合点回滚。Cherry-pick 仅用于明确独立的修复或本地/远端历史不同的新补丁，先比较 patch/tree；不能重新挑选已整合的 reader/UI 全部提交。未来短小独立分支可另选 squash，无需重造 develop/release 分支体系。

## 合并门槛与发布门槛

### 开发基线合入 main 前

- 对**最终候选 SHA**验证 reader 基础安装不依赖模型 SDK，并完成后端全量测试：`uv sync --frozen --python 3.14 --extra save --extra agent`、`uv run --frozen --extra save --extra agent pytest -q`。
- 从仓库根目录执行桌面检查：`npm ci --prefix apps/companion`、`npm run check --prefix apps/companion`，核验对应平台 CI 的嵌入后端、打包、冷启动/退出、NSIS安装/重装/卸载与升级测试、macOS签名完整性。签名完整性不等于公证完成。
- 核验 bridge payload、Windows scheduler probe、metadata/UI candidate 的离线测试、构建与打包；实验授权门控不应被生产默认启用，不增加自动重试或扩大采集范围。
- 复核断连/重连、token轮换、会话隔离、过期和缺失事实、无静默 mock 回退、模型预算、私有数据不入包、第三方许可与文档链接。路径过滤导致 CI 未触发不能记为通过。
- 无未解决的高风险问题；用户确认文档口径。CI 必须对应最终候选，而不是引用较早 head 的绿灯。

### Windows Alpha 与稳定发布另行验收

须用明确 commit、产物 hash、游戏 build/session 与真实样本证明：桌宠运行 → 连接真实 reader → 授权范围内读取 → provenance/partial/freshness 正确 → 依据真实字段给出建议。缺失/过期必须明确报告，切存档不得沿用旧会话事实。

metadata、一次 UI 组件文字、fake/native fixture 或桌宠成功启动，都不等于稳定实体身份、完整业务字段或真实 Windows 后台读取成功。完整读取与建议范围沿用项目验收目标，不以局部测试替代；模型调用仍须处于用户授权额度内。

若用户选择先发范围更窄的预览，应由用户明确决定，发布说明逐项列出已通过/未通过范围；本计划不替用户降低既定 MVP。**开发基线合并、预览发布、正式稳定是三个不同决定。**

## main 保护、回滚与分支收尾

- 建议 main 要求 PR 评审和必要 CI，禁止 force-push/删除；审批数量按实际维护人数设置，避免自锁。不应同时强制与 merge 策略冲突的线性历史。实际保护规则尚需核验。
- 合并前记录 main head 与产物 hash。出现问题优先 revert 整合提交，核对 main 父链后选择正确主线；不 reset/force 改写共享历史，不删除用户数据或重置模型额度。安装回退要先确认配置/数据兼容性。
- 未来获准发布时，用唯一、不复用的 `v0.0.x-alpha.n` 类注释 tag 绑定已测 main commit 与产物 hash；不移动旧 tag。Alpha tag 不表示稳定认证。
- reader/UI 仅在最新 heads 已成为 main 祖先、验收通过、无未推送工作且用户确认不再续写后才建议删除。docs 仍由用户持续更新，不应自动删除其工作入口。integration 保留至整合、CI、相应验收与回滚安排完成且无未合新提交，再决定收尾。

## 核验范围

本次完成 Git 提交关系、tree差异、文件保留与冲突预测。较早 PR 查询为空，实际执行前须再查；CI结果、分支保护、发布tag及真实 Windows 最新会话另行核验。本次分析未重跑应用测试或操作用户电脑，不能作为运行验收证据。

固定快照：[main…integration](https://github.com/sanshanhyo/FootballAssistant/compare/f7d1055eaac31cef1af3559195dadd94b239089f...0b821f1f53a6766b4d0472339d5d5d5a56f56f4a) · [main…docs](https://github.com/sanshanhyo/FootballAssistant/compare/f7d1055eaac31cef1af3559195dadd94b239089f...922497f126d20bf0dbaa328a2aabd535aaf48a38) · [PR](https://github.com/sanshanhyo/FootballAssistant/pulls) · [CI](https://github.com/sanshanhyo/FootballAssistant/actions)
