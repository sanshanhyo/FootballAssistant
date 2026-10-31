# UI 遍历诊断（兼容 0.2 scalar fact 协议）

每次 UI capture 额外输出最多 34 条 `ui_capture_diagnostic` fact；`field=capture_metrics`，`value` 为不含 UI 原文的 JSON 字符串。`diagnostic/capture` 给出 panels_available/panels_visited、visited_nodes、elapsed_ms、stop_reason、truncated、captured_texts 和固定预算。`diagnostic/panelN` 给出访问/通过可见性测试/visible=false/无效边界、TextElement/其他 widget/空文本/输出文本、深度/子节点上限跳过、待遍历节点和耗时。`diagnostic/transport` 单独报告 payload 字节预算造成的文本丢弃。0 文本时仍发送诊断，不补造 UI 事实。

`stop_reason` 为 complete、time_budget、node_limit、text_limit、stack_limit、panel_limit，或 domain_unavailable / panels_unavailable / root_unavailable。深度和子节点裁剪也令 truncated=true，即使全局没有停止。pending_nodes 是已知待遍历根节点数，不是其全部后代数；不可见节点的后代没有探测。elapsed_ms 仅为原有遍历预算区间，初始化/获取面板列表不在该区间，单个原生 getter 不能被中途抢占；15ms 不是硬实时保证。

读取面仍仅支持 `UnityEngine.UIElements.TextElement`（含派生类）的 `get_text`；其他 widget 计数不等于其一定有文字。可见性仍仅是 `get_visible` 与有限、正宽高 worldBound，不能证明视口裁剪、遮挡或当前页面。诊断不会自动识别页面或关联足球实体/字段。未提高预算或增加 getter。Reader 拉取上限为 114（80 原 UI 事实 + 34 诊断）；投影和模型证据仍最多 80 UI 文本，诊断不进入模型证据。
