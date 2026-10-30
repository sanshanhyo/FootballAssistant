# Alpha 桌宠 / backend 集成记录

本次隔离集成以 UI `13c1a6b` 与 reader `18acc2e` 为基线；不覆盖两个开发分支，不修改外观、字体、角色资源、README 或路线图。这里记录连接能力，不宣称 FM27 业务读取完成。

## 已接通的路径

- 在设置中显式选择 real 模式后，桌宠通过主进程的受限本机 HTTP 客户端访问 backend。
- 普通陪聊、一般 FM 知识问题使用 `/v1/chat`；实际回答仍需 backend 中配置模型并设置明确请求额度，默认额度为零。
- 显式业务 capability 或有限的当前存档请求使用 `/v1/agent/business-advice`。业务阻塞不会改调聊天或 mock 来补造事实。
- 数据查询使用 `/v1/reader/business/status`、`/snapshot`。当前没有验证过的 producer，返回 unavailable 是正确结果。
- 认证失败、旧服务不支持、超时、断开与业务数据缺失分开处理。会话切换、取消、重连和令牌变化会淘汰过期请求；重试成功可恢复连接状态。

自然语言路由只用于常见请求的交互分类，不是理解所有意图的保证或安全边界。确需指定能力时使用 `player_info`、`transfer_analysis`、`tactical_analysis`、`schedule_analysis`；所有事实仍由 backend 校验。

## 本机配置

backend 和桌宠必须读取同一个 runtime 文件。桌宠优先使用 `FOOTBALL_ASSISTANT_RUNTIME_FILE`，其次 `FOOTBALL_ASSISTANT_DATA_DIR/runtime.json`，开发环境默认仓库 `local-data/runtime.json`。打包运行建议设置显式路径。

需要聊天或建议时启动完整 `football-assistant-backend`；`football-assistant-reader-server` 是不加载模型的只读服务，建议路由返回 404。模型地址、模型名、密钥和调用额度只配置在 backend，不能放入 renderer 或提交 Git。runtime 令牌仅由主进程读取。

完整数据接口见 [Companion / reader 交接](companion-reader-handoff.md)。游戏二进制身份采集可使用 `modules/game-bridge/scripts/inspect_windows_binary.py`；它只读显式文件路径，绝不加载/执行 DLL，也不证明该构建已被 reader 支持。

## 已执行验证与剩余边界

- Python 离线及真实本机 HTTP 测试：333 passed，1 个 Windows 原生专用测试在 Linux 上跳过。
- Node 语法与单元/传输测试：49 passed。
- 已运行临时 Python backend → Node adapter → companion runtime：真实 HTTP 返回 blocked 建议，未生成假卡片，模型/SDK/额度调用均为零。
- 修正 Edge TTS 测试的同步/异步路径规范化不一致；保留固定程序、禁用 shell 和文本文件输入断言。该修改不代表生产 TTS 存在故障。
- 上述验证不等于完整 GUI 手工验收、真实模型建议、真实 FM27 读取或目标电脑安装成功。目标 Windows CI 与实机验收应单独记录。
- 原有 Windows Python 测试仍有四项默认字符编码导致的 fixture 读取失败，不能将全套 CI 称为全绿。
