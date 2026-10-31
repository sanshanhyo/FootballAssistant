# UI 遍历诊断（兼容 0.2 scalar fact 协议）

每次 UI capture 额外输出最多 34 条 `ui_capture_diagnostic` fact；`field=capture_metrics`，`value` 为不含 UI 原文的 JSON 字符串。`diagnostic/capture` 给出 panels_available/panels_visited、visited_nodes、elapsed_ms、stop_reason、truncated、captured_texts 和固定预算。`diagnostic/panelN` 给出访问/通过可见性测试/visible=false/无效边界、TextElement/其他 widget/空文本/输出文本、深度/子节点上限跳过、待遍历节点和耗时。`diagnostic/transport` 单独报告 payload 字节预算造成的文本丢弃。0 文本时仍发送诊断，不补造 UI 事实。

`stop_reason` 为 complete、time_budget、node_limit、text_limit、stack_limit、panel_limit，或 domain_unavailable / panels_unavailable / root_unavailable。深度和子节点裁剪也令 truncated=true，即使全局没有停止。pending_nodes 是已知待遍历根节点数，不是其全部后代数；不可见节点的后代没有探测。elapsed_ms 仅为原有遍历预算区间，初始化/获取面板列表不在该区间，单个原生 getter 不能被中途抢占；15ms 不是硬实时保证。

读取面仍仅支持 `UnityEngine.UIElements.TextElement`（含派生类）的 `get_text`；其他 widget 计数不等于其一定有文字。可见性仍仅是 `get_visible` 与有限、正宽高 worldBound，不能证明视口裁剪、遮挡或当前页面。诊断不会自动识别页面或关联足球实体/字段。深度上限从 28 调整为 48，文字上限从 80 调整为 240；15ms、2500 节点、120000 字节、面板/子节点/栈上限均未提高，也未增加 getter。Reader 拉取上限为 274（240 原 UI 事实 + 34 诊断）；投影读取最多 240 UI 文本，模型证据另设字符预算，诊断不进入模型证据。

深度与路径准入：`max_depth=48`（根深度 0）、`max_path_length=128`。子节点超过任一边界时，在读取该子节点对象前跳过，分别增加 `depth_skipped` 或 `path_limit_skipped` 并令面板/采样 `truncated=true`。计数是被跳过的子树根，不是所有后代数。路径保持原始 `panelN/childIndex/...` 字符串，不截断、不哈希、不提升为稳定实体 ID；超过 128 字符的子树不会导致整个观测序列化失败。既有路径与 profile selector 语义不变；深入读取也不证明新文字的可见性或字段关联。

模型证据单独限制为 16000 字符（每条 literal path + text 长度之和，不含 JSON 编码开销），仅纳入完整前缀条目，不裁剪单条文字。所有最多 240 条 UI 事实仍需通过验证，包括未纳入模型的尾部。`evidence_truncated` 与 `evidence_budget` 显式报告采样/纳入/遗漏数量及字符计数；截断不代表完整页面。`capture_text_sha256` 仅用于生成后刷新时检查完整 UI 文本内容是否变化（含遗漏尾部、不含变化的诊断耗时），不是实体 ID，不建立相邻文字关联。
