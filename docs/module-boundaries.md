# MVP 模块边界

| 模块 | 输入 | 输出 | 当前能力与边界 |
| --- | --- | --- | --- |
| Save Adapter | 用户显式指定的稳定 FM27 存档 | 带摘要验证状态的观测 | 安全复制并校验 SHA；`fmsave 0.7.0` 只用于 MIT 容器读取；自有严格 summary31/build profile 仅输出两项实验性事实。不修改原件。 |
| Data Core | Save observation / Runtime observation | 带来源状态的事实、只读查询 | Schema 校验、来源保留、幂等存储；不解析存档、不加载游戏程序集。 |
| Agent Core | 用户消息与 Data Core 的受控查询 | 有人格的回复、近期持久会话、基础记忆 | 经 OpenAI 兼容接口调用模型；事实须与模型推断区分。已用完本机两次模型调用硬限额。 |
| Companion | 用户互动、Agent 响应与状态 | Electron 桌宠、聊天 UI、中文 TTS | 持有模型令牌以外的连接令牌于受控主进程；TTS 通过本机系统能力执行；已在 macOS 实机通过。 |
| Game Bridge / Runtime Adapter | FM27 运行时的受限可见 UI 文字 | `partial` 原始观测 | C# 代码离线编译/self-test 通过，采用 BepInEx compatibility 接口；未加载、未注入、未验收实时足球字段。 |
| Contracts | 版本化 JSON Schema | 两种采集来源共用事件格式 | 事件标来源、状态、时间和 snapshot 元数据；未知值保留未知。 |

## Save snapshot 的验证范围

目前 summary adapter 只接纳 schema 31、build `27.0.0+2486695` 的狭窄格式。首个已核对样本通过 UI 交叉验证，事实为：

- `club_label = "曼联"`，代表存档 summary 中的原始球队标签，不是已解析俱乐部实体或 UID。
- `game_date = "2026-07-13"`，代表解析出的日历日期，不含时间或当前实时游戏状态。

之后匹配同 profile 的新存档只核验摘要语法/UTF-8/长度规则，不逐份做 UI 交叉验证。所有 facts 仍 `experimental`。不输出球员、阵容、属性、赛果或隐藏数据；未支持、解析失败及缺少元数据均不转成空列表或默认值。快照不会随游戏变化，要刷新需手动再次导入稳定副本。

输入明确要求已确认副本。CLI 记录原件与副本的身份/大小/时间/摘要，检查复制过程稳定和副本 SHA 一致，然后只读取副本。摘要/profile 不匹配时不进入 Data Core。

## Runtime 与调用所有权

Runtime 与 Save 互不调用，也不能相互冒充。Game Bridge 只在主线程有限采样并异步发送读取到的 UI 文字；实际加载和字段意义尚待验证。Data Core 是事实规范化入口；Agent 不自行读取游戏或存档。正常 Companion 启动不会自动发起聊天模型请求。

Python 服务在本机回环运行，SQLite 分别保存观测与伙伴会话。Agent 只做受控只读事实查询。长期语义记忆、复杂成长、多人格演进、自动游戏操作和高级教练功能延期。
